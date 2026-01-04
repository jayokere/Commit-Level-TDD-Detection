import os
import sys
import signal  # Added for timeout handling
import time    # Added for sleep during retries
from multiprocessing import Manager
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED # Changed import for dynamic queue
from tqdm import tqdm
from pydriller import Repository
from urllib.parse import urlparse
import random
from datetime import datetime
import requests
from collections import defaultdict

# Internal Modules
from utils import measure_time
from db import (
    get_java_projects_to_mine,
    get_python_projects_to_mine,
    get_cpp_projects_to_mine, 
    ensure_indexes,
    get_completed_project_names,
    mark_project_as_completed
)
from miners import FileAnalyser, TestAnalyser, CommitProcessor
from miner_intro import ProgressMonitor
from miners.file_analyser import VALID_CODE_EXTENSIONS

"""
repo_miner.py

Description:
    This script orchestrates the mining of GitHub repositories to extract specific software 
    engineering metrics (DMM, Cyclomatic Complexity, and Changed Methods).

Key Features:
    1. Multiprocessing: Utilises all available CPU cores to mine repositories in parallel.
    2. Quota Management: Ensures exactly 60 projects per language are mined, skipping already 
       completed projects to prevent redundancy.
    3. Duplicate Prevention: Explicitly checks the database for existing commit hashes 
       to allow resumable execution.
    4. Metric Extraction: Extracts the Delta Maintainability Model (DMM) at the commit level 
       and Cyclomatic Complexity at the file level.
    5. Test Coverage Analysis: Analyzes test method names to identify which source files 
       are being tested, addressing GitHub Issue #4 for improved TDD detection.
    6. Language-Specific Mining: Restricts mining to files relevant to the project's language.
"""

# The number of commits to hold in memory before performing a bulk write to MongoDB.
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "250")) 
# Whether to print per-worker activity logs.
SHOW_WORKER_ACTIVITY = os.getenv("SHOW_WORKER_ACTIVITY", "0") == "1"

# --- NEW CONFIG ---
# Hard timeout for a single worker task (in seconds). Default: 45 minutes.
WORKER_TIMEOUT = int(os.getenv("WORKER_TIMEOUT", "2700"))
# Maximum number of times to retry a shard if it times out.
MAX_RETRIES = 3
# ------------------

class TimeoutException(Exception):
    """Custom exception for worker timeout."""
    pass

def timeout_handler(signum, frame):
    """Signal handler to raise a TimeoutException."""
    raise TimeoutException("Task exceeded maximum execution time.")

class Repo_miner:
    """
    Main controller class for the repository mining programme.
    """
    def __init__(self):
        """
        Initialises the miner by calculating quotas and sampling projects.
        """
        print("Fetching project list and checking existing quotas...")
        
        # Get list of already completed projects from DB to avoid re-mining
        already_mined = get_completed_project_names()
        
        self.projects = []
        
        def fill_quota(candidates, language_name, target_quota=60):
            completed = [p for p in candidates if p['name'] in already_mined]
            current_count = len(completed)
            print(f"[{language_name}] Status: {current_count}/{target_quota} repositories mined.")
            
            if current_count >= target_quota:
                print(f"   -> Quota met. Skipping {language_name}.")
                return []
            
            needed = target_quota - current_count
            available = [p for p in candidates if p['name'] not in already_mined]
            
            # If we have more available than needed, sample randomly. Otherwise take all.
            count_to_take = min(len(available), needed)
            
            if count_to_take == 0:
                print(f"   -> No new candidates available for {language_name}.")
                return []
                
            print(f"   -> Queuing {count_to_take} new {language_name} repositories...")
            return random.sample(available, count_to_take)

        # Fill quotas for each language
        self.projects.extend(fill_quota(get_java_projects_to_mine(), "Java"))
        self.projects.extend(fill_quota(get_python_projects_to_mine(), "Python"))
        self.projects.extend(fill_quota(get_cpp_projects_to_mine(), "C++"))

        print(f"\n[Job Summary] Mining {len(self.projects)} new repositories in this run.\n")

    @staticmethod
    def clean_url(url):
        if not url: return None
        url = url.strip().rstrip('/')
        if "github.com:" in url and "github.com:443" not in url:
            url = url.replace("github.com:", "github.com/")
        return url
    
    @staticmethod
    def _prepare_job(project):
        """
        Helper function to calculate shards for a single project.
        This is run in a thread pool to avoid blocking on network requests (for C++ API checks).
        """
        jobs = []
        current_year = datetime.now().year
        
        name = project.get('name')
        raw_url = project.get('repo_url') or project.get('url')
        language = project.get('language')

        if isinstance(raw_url, list) and len(raw_url) > 0:
            raw_url = raw_url[0]
        
        if not (isinstance(raw_url, str) and raw_url):
            return []

        start_year = 2000
        
        # Special handling for C++: Fetch creation date from API to avoid cloning ancient history
        if language == 'C++':
            try:
                if raw_url:
                    parsed_url = urlparse(raw_url)
                    hostname = parsed_url.hostname.lower() if parsed_url.hostname else None
                    if hostname in ("github.com", "www.github.com"):
                        parts = raw_url.strip("/").split("/")
                        if len(parts) >= 2:
                            owner, repo = parts[-2], parts[-1]
                            api_url = f"https://api.github.com/repos/{owner}/{repo}"
                            token = os.getenv('GITHUB_TOKEN') 
                            headers = {}
                            if token:
                                headers['Authorization'] = f'token {token}'

                            response = requests.get(api_url, headers=headers, timeout=5)
                            if response.status_code == 200:
                                data = response.json()
                                created_at = data.get("created_at")
                                if created_at:
                                    start_year = int(created_at[:4])
            except Exception:
                # If API fails, fallback to 2000
                print(f"⚠️ Warning: Could not fetch creation date for {name}. Using default start year {start_year}.")
                pass

            # Create the shards based on the year found
            shard_years = list(range(start_year, current_year + 2))

            for i in range(len(shard_years) - 1):
                s_date = datetime(shard_years[i], 1, 1)
                e_date = datetime(shard_years[i+1], 1, 1)
                
                # Stop creating future shards
                if s_date > datetime.now(): break
                
                jobs.append((name, raw_url, s_date, e_date, language))
        else:
            # Java/Python: Just one big job (PyDriller handles cloning efficiently usually)
            # OR we could shard them too, but currently logic kept as per original request/design
            # NOTE: If Java repos are huge, you might want to enable sharding for them too.
            jobs.append((name, raw_url, None, None, language))
            
        return jobs

    @staticmethod
    def mine_repo(args):
        """
        Worker function to mine a single repository (or shard of it).
        Executed in a separate process via ProcessPoolExecutor.
        """
        project_name, raw_url, start_date, end_date, language, stop_event = args
        
        # Check if we should stop early (e.g. CTRL+C)
        if stop_event.is_set(): return None

        # --- TIMEOUT SETUP ---
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(WORKER_TIMEOUT)
        # ---------------------

        repo_url = Repo_miner.clean_url(raw_url)
        if not repo_url:
            signal.alarm(0) # Disable alarm
            return (project_name, 0, 0, "Skipped: Invalid or missing URL")

        try:
            year_str = f""
            if SHOW_WORKER_ACTIVITY:
                s_str = start_date.strftime('%Y-%m') if start_date else "START"
                e_str = end_date.strftime('%Y-%m') if end_date else "NOW"
                year_str = f"({s_str} to {e_str})"
                tqdm.write(f"🚀 [Start] {project_name} {year_str} [{language}]")
            
            # Initialise PyDriller with Date Partitioning (if dates provided)
            repo_obj = Repository(
                repo_url,
                since=start_date,
                to=end_date,
                only_modifications_with_file_types=list(VALID_CODE_EXTENSIONS)
            )
            
            processor = CommitProcessor(batch_size=BATCH_SIZE)
            new_commits_mined, initial_count = processor.process_commits(
                repo_obj, 
                project_name, 
                repo_url,
                language=language
            )
            
            if SHOW_WORKER_ACTIVITY:
                if new_commits_mined > 0:
                    tqdm.write(f"✅ [Done] {project_name} {year_str}: {new_commits_mined} commits.")
        
            return (project_name, new_commits_mined, initial_count, None)
            
        except TimeoutException:
            # Return specific key string to trigger retry logic
            return (project_name, 0, 0, "TIMED OUT")
            
        except Exception as e:
            # Generic error (network, git clone fail, etc.)
            return (project_name, 0, 0, str(e))
            
        finally:
            # Ensure the alarm is disabled once the function exits
            signal.alarm(0)

    @measure_time
    def run(self):
        """
        Main execution flow using custom 'miner_intro' progress bars.
        """
        jobs = []
        total_projects = len(self.projects)

        # --- PHASE 1: PREPARATION (Multithreaded) ---
        # We prepare shard dates in parallel because network requests (GitHub API) are slow.
        print(f"[INFO] Analysing {total_projects} repositories to determine shard dates...\n")
        
        monitor = ProgressMonitor(total_projects, label="PREPARING SHARDS")
        monitor.start()

        with ThreadPoolExecutor(max_workers=20) as preparer:
            future_to_project = {preparer.submit(self._prepare_job, p): p for p in self.projects}
            completed_prep = 0
            for future in as_completed(future_to_project):
                try:
                    result_jobs = future.result()
                    jobs.extend(result_jobs)
                except Exception as exc:
                    print(f"\n[WARN] Exception during preparation: {exc}")
                completed_prep += 1
                monitor.update(completed_prep)

        monitor.stop()

        if not jobs:
            print("No new projects found to mine (Quotas may be full).")
            return

        # --- PHASE 2: MINING (Multiprocessing) ---
        total_jobs = len(jobs)
        shards_remaining = defaultdict(int)
        project_errors = defaultdict(bool) 

        # Track retry attempts: job_args_tuple -> attempt_count
        retry_counts = defaultdict(int)

        for j in jobs:
            p_name = j[0]
            shards_remaining[p_name] += 1

        print(f"\n[INFO] Preparation complete. Starting parallel mining with {total_jobs} segments.")
        print(f"[INFO] Worker Timeout: {WORKER_TIMEOUT}s | Max Retries: {MAX_RETRIES}")

        # Determine optimal worker count
        env_max = os.getenv("MAX_WORKERS")
        if env_max and env_max.isdigit():
            max_workers = int(env_max)
        else:
            # Default to 2x CPU count (IO bound-ish due to network/disk)
            max_workers = (os.cpu_count() or 6) * 2
        
        # Don't spawn more workers than jobs
        max_workers = max(1, min(total_jobs, max_workers))
        
        print(f"[INFO] Using {max_workers} worker processes\n")

        monitor = ProgressMonitor(total_jobs, label="MINING PROGRESS")
        monitor.start()
        
        with Manager() as manager:
            # Shared event to signal all workers to stop (e.g. on Ctrl+C)
            stop_event = manager.Event()
            
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # We use a dict to map Futures back to their job arguments
                # so we can re-submit them if they timeout.
                future_to_job = {}

                # 1. Submit initial jobs
                for job_args in jobs:
                    p_name, url, start, end, language = job_args
                    f = executor.submit(self.mine_repo, (p_name, url, start, end, language, stop_event))
                    future_to_job[f] = job_args

                completed_mining = 0
                
                try:
                    # 2. Dynamic loop to handle results as they arrive
                    while future_to_job:
                        # Wait for at least one future to complete
                        done, _ = wait(future_to_job.keys(), return_when=FIRST_COMPLETED)
                        
                        for future in done:
                            job_data = future_to_job.pop(future)
                            p_name = job_data[0]
                            
                            try:
                                result = future.result()
                                if result is None: continue

                                _, added, _, error = result
                                
                                # --- RETRY LOGIC START ---
                                if error and "TIMED OUT" in str(error):
                                    current_retries = retry_counts[job_data]
                                    
                                    if current_retries < MAX_RETRIES:
                                        retry_counts[job_data] += 1
                                        delay = 5 * retry_counts[job_data]
                                        
                                        monitor.log(f"⚠️ {p_name} TIMED OUT. Retrying ({retry_counts[job_data]}/{MAX_RETRIES}) in {delay}s...")
                                        time.sleep(delay)
                                        
                                        # Re-submit job
                                        p_name, url, start, end, language = job_data
                                        new_future = executor.submit(self.mine_repo, (p_name, url, start, end, language, stop_event))
                                        future_to_job[new_future] = job_data
                                        continue # Skip completion logic for this iteration
                                    else:
                                        monitor.log(f"❌ {p_name} TIMED OUT. Max retries reached. Dropping shard.")
                                        project_errors[p_name] = True
                                # --- RETRY LOGIC END ---

                                if added > 0:
                                    monitor.log(f"✅ {p_name}: {added} new commits mined.")
                                
                                # Any other error (or exhausted retries)
                                if error and "TIMED OUT" not in str(error) and "No commits found" not in str(error):
                                    monitor.log(f"❌ {p_name}: {error}")
                                    project_errors[p_name] = True
                                
                                shards_remaining[p_name] -= 1

                                # If 0 shards remain AND no errors occurred, mark as "completed" in DB
                                if shards_remaining[p_name] == 0:
                                    if not project_errors[p_name]:
                                        mark_project_as_completed(p_name)
                                        monitor.log(f"🏆 {p_name} FULLY COMPLETED.")
                                    else:
                                        monitor.log(f"⚠️ {p_name} finished with errors (not complete).")

                                completed_mining += 1
                                monitor.update(completed_mining)

                            except Exception as exc:
                                # Start logging critical worker failures
                                monitor.log(f"❌ Critical exception in worker for {p_name}: {exc}")
                                shards_remaining[p_name] -= 1
                                completed_mining += 1
                                monitor.update(completed_mining)

                except KeyboardInterrupt:
                    monitor.stop()
                    print("\n\n🛑 STOPPING MINER! Terminating processes...")
                    stop_event.set()
                    for f in future_to_job.keys():
                        f.cancel()
            
            # Stop monitor if not already stopped
            if monitor.running:
                monitor.stop()
        
        print("\n") 
        print("[DB] Optimising database indices...")
        ensure_indexes()
        print("[SUCCESS] Cycle complete.")

if __name__ == "__main__":
    miner = Repo_miner()
    miner.run()