import os
import sys
from multiprocessing import Manager
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from tqdm import tqdm
from pydriller import Repository
from urllib.parse import urlparse
import random
from datetime import datetime
import requests

# Internal Modules
from utils import measure_time
from db import (
    get_java_projects_to_mine,
    get_python_projects_to_mine,
    get_cpp_projects_to_mine, 
    ensure_indexes,
    get_all_mined_project_names 
)
from miners import FileAnalyser, TestAnalyser, CommitProcessor
from miner_intro import ProgressMonitor

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
"""

# The number of commits to hold in memory before performing a bulk write to MongoDB.
# Larger batches reduce network latency but increase memory consumption.
# Make this tunable via env var BATCH_SIZE (default set to 100 for safety with large C++ files)
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "250")) 
# Whether to print per-worker activity logs. Default off to avoid progress bar churn; enable with SHOW_WORKER_ACTIVITY=1.
SHOW_WORKER_ACTIVITY = os.getenv("SHOW_WORKER_ACTIVITY", "0") == "1"

class Repo_miner:
    """
    Main controller class for the repository mining programme.
    """
    def __init__(self):
        """
        Initialises the miner by calculating quotas and sampling projects.
        It checks the database to see how many projects of each language have already
        been mined to ensure the total does not exceed the target of 60.
        """
        print("Fetching project list and checking existing quotas...")
        
        # Retrieve the set of project names already stored in the DB
        # This allows for O(1) lookups to check if a project is done.
        already_mined = get_all_mined_project_names()
        self.projects = []
        
        def fill_quota(candidates, language_name, target_quota=60):
            """
            Helper function to calculate remaining quota and sample new projects.
            """
            # Check which projects are already done
            completed = [p for p in candidates if p['name'] in already_mined]
            current_count = len(completed)
            
            print(f"[{language_name}] Status: {current_count}/{target_quota} repositories mined.")
            
            # If we have reached the limit, do not queue any more projects for this language
            if current_count >= target_quota:
                print(f"   -> Quota met. Skipping {language_name}.")
                return []
            
            # Calculate how many new projects we need to reach the target
            needed = target_quota - current_count
            # Filter the candidate list to exclude already mined projects
            available = [p for p in candidates if p['name'] not in already_mined]
            
            # Safety check: ensure we do not try to sample more than what is available
            count_to_take = min(len(available), needed)
            
            if count_to_take == 0:
                print(f"   -> No new candidates available for {language_name}.")
                return []
                
            print(f"   -> Queuing {count_to_take} new {language_name} repositories...")
            return random.sample(available, count_to_take)

        # Apply quota logic to each language category
        self.projects.extend(fill_quota(get_java_projects_to_mine(), "Java"))
        self.projects.extend(fill_quota(get_python_projects_to_mine(), "Python"))
        self.projects.extend(fill_quota(get_cpp_projects_to_mine(), "C++"))

        print(f"\n[Job Summary] Mining {len(self.projects)} new repositories in this run.\n")

    @staticmethod
    def clean_url(url):
        """
        Sanitises the repository URL to prevent Git cloning errors.
        
        Args:
            url (str): The raw URL retrieved from the database.
            
        Returns:
            str: A clean, valid URL, or None if the input is invalid or empty.
        """
        if not url: return None
        url = url.strip().rstrip('/')

        # Specific correction for malformed GitHub URLs that include port numbers (e.g., :443)
        # These can occur when mining data from certain API proxies.
        if "github.com:" in url and "github.com:443" not in url:
            url = url.replace("github.com:", "github.com/")
        return url
    
    @staticmethod
    def _prepare_job(project):
        """
        Helper function to calculate shards for a single project.
        OPTIMISED: Uses GitHub API to find start year instantly (no cloning).
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

        # Default fallback
        start_year = 2000
        
        # LOGIC: If C++, use GitHub API to get the real start year without cloning
        if language == 'C++':

            try:
                if not raw_url:
                    return []
            
                parsed_url = urlparse(raw_url)
                # Check if the hostname (domain) is exactly github.com (optionally allowing www.github.com)
                hostname = parsed_url.hostname.lower() if parsed_url.hostname else None
                if hostname and hostname in ("github.com", "www.github.com"):
                    # Convert raw URL to API URL
                    parts = raw_url.strip("/").split("/")
                    if len(parts) >= 2:
                        owner, repo = parts[-2], parts[-1]
                        api_url = f"https://api.github.com/repos/{owner}/{repo}"
                        
                        # Get token from environment variables
                        token = os.getenv('GITHUB_TOKEN') 
                        headers = {}
                        if token:
                            headers['Authorization'] = f'token {token}'

                        # Makes a lightweight API call (Time: ~0.5s)
                        response = requests.get(api_url, headers=headers, timeout=5)
                        
                        if response.status_code == 200:
                            data = response.json()
                            created_at = data.get("created_at") # Format: "2016-02-17T15:47:32Z"
                            if created_at:
                                start_year = int(created_at[:4])
            except Exception:
                # If API fails (rate limit or network), fail silently and use default 2000
                print(f"⚠️ Warning: Could not fetch creation date for {name}. Using default start year {start_year}.")
                pass

            # Create the shards based on the year found
            shard_years = list(range(start_year, current_year + 2))

            for i in range(len(shard_years) - 1):
                s_date = datetime(shard_years[i], 1, 1)
                e_date = datetime(shard_years[i+1], 1, 1)
                if s_date > datetime.now(): break
                jobs.append((name, raw_url, s_date, e_date))
        else:
            # Non-C++ projects don't need sharding
            jobs.append((name, raw_url, None, None))
            
        return jobs

    @staticmethod
    def mine_repo(args):
        """
        Worker function to mine a single repository. 
        Executed in a separate process via ProcessPoolExecutor.
        
        Args:
            args (tuple): A tuple containing (project_name, raw_url, start_date, end_date, stop_event).
            
        Returns:
            tuple: (project_name, new_commits_count, existing_count, error_message)
        """
        project_name, raw_url, start_date, end_date, stop_event = args
        
        # Guard clause: Return immediately if the global stop signal (Ctrl+C) is set
        if stop_event.is_set(): return None

        repo_url = Repo_miner.clean_url(raw_url)
        if not repo_url:
            return (project_name, 0, 0, "Skipped: Invalid or missing URL")

        try:
            # Create a label for logging (e.g., "Apache/Arrow [2015]")

            year_str = f""
            if SHOW_WORKER_ACTIVITY:
                # Format dates for logging
                s_str = start_date.strftime('%Y-%m') if start_date else "START"
                e_str = end_date.strftime('%Y-%m') if end_date else "NOW"
                year_str = f"({s_str} to {e_str})"
                tqdm.write(f"🚀 [Start] {project_name} {year_str}")

            # Import the extension list for filtering
            from miners.file_analyser import VALID_CODE_EXTENSIONS
            
            # Initialise PyDriller with Date Partitioning (if dates provided)
            # This is the key to speeding up C++
            repo_obj = Repository(
                repo_url,
                since=start_date,
                to=end_date,
                only_modifications_with_file_types=list(VALID_CODE_EXTENSIONS)
            )
            
            # Use CommitProcessor to traverse and extract metrics
            processor = CommitProcessor(batch_size=BATCH_SIZE)
            new_commits_mined, initial_count = processor.process_commits(
                repo_obj, 
                project_name, 
                repo_url
            )
            
            if SHOW_WORKER_ACTIVITY:
                worker_id = os.getpid()
                if new_commits_mined > 0:
                    tqdm.write(f"✅ [Done] {project_name} {year_str}: {new_commits_mined} commits.")
        
            return (project_name, new_commits_mined, initial_count, None)
            
        except Exception as e:
            # Capture errors (e.g., Network issues, deleted repos) and return them safely
            # without crashing the worker process.
            return (project_name, 0, 0, str(e))

    @measure_time
    def run(self):
        """
        Main execution flow using custom 'miner_intro' progress bars.
        """
        jobs = []
        total_projects = len(self.projects)

        # --- PHASE 1: PREPARATION (Multithreaded) ---
        print(f"[INFO] Analysing {total_projects} repositories to determine shard dates...\n")
        
        monitor = ProgressMonitor(total_projects, label="PREPARING SHARDS")
        monitor.start()

        # Use ThreadPoolExecutor for I/O bound date checking
        with ThreadPoolExecutor(max_workers=20) as preparer:
            future_to_project = {preparer.submit(self._prepare_job, p): p for p in self.projects}
            
            completed_prep = 0
            
            # Process results as they come in
            for future in as_completed(future_to_project):
                try:
                    result_jobs = future.result()
                    jobs.extend(result_jobs)
                except Exception as exc:
                    print(f"\n[WARN] Exception during preparation: {exc}")
                
                # Update Custom Progress Bar
                completed_prep += 1
                monitor.update(completed_prep)

        monitor.stop()

        if not jobs:
            print("No new projects found to mine (Quotas may be full).")
            return

        # --- PHASE 2: MINING (Multiprocessing) ---
        total_jobs = len(jobs)
        print(f"\n[INFO] Preparation complete. Starting parallel mining with {total_jobs} segments.")
        
        env_max = os.getenv("MAX_WORKERS")
        if env_max and env_max.isdigit():
            max_workers = int(env_max)
        else:
            max_workers = (os.cpu_count() or 6) * 2
        max_workers = max(1, min(total_jobs, max_workers))
        
        print(f"[INFO] Using {max_workers} worker processes\n")

        monitor = ProgressMonitor(total_jobs, label="MINING PROGRESS")
        monitor.start()
        
        with Manager() as manager:
            stop_event = manager.Event()
            futures = []

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                try:
                    # Submit all jobs
                    for p_name, url, start, end in jobs:
                        futures.append(executor.submit(
                            self.mine_repo, 
                            (p_name, url, start, end, stop_event)
                        ))

                    completed_mining = 0
                    
                    # Track progress
                    for future in as_completed(futures):
                        result = future.result()

                        if result is None: continue

                        p_name, added, existing, error = result
                        
                        if added > 0:
                            monitor.log(f"✅ {p_name}: {added} new commits mined.")
                        
                        if error and "No commits found" not in str(error):
                            monitor.log(f"❌ {p_name}: {error}")
                        
                        completed_mining += 1
                        monitor.update(completed_mining)

                except KeyboardInterrupt:
                    monitor.stop()
                    print("\n\n🛑 STOPPING MINER! Terminating processes...")
                    stop_event.set()
                    for f in futures: f.cancel()
            
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