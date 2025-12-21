import os
import sys
from multiprocessing import Manager
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from pydriller import Repository
import random
from datetime import datetime

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
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100")) 
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
        Configures the multiprocessing pool and manages the lifecycle of the mining operation.
        """
        # Prepare the jobs list, ensuring URLs are correctly formatted strings
        jobs = []
        
        current_year = datetime.now().year

        for p in self.projects:
            raw_url_val = p.get('url')

            # Define the years to shard C++ repos into (from the first commit year to present)
            for c in Repository(raw_url_val, order='reverse').traverse_commits():
                if c:
                    first_commit = c
                    first_year = first_commit.author_date.year
                    shard_years = list(range(first_year, current_year + 2))
                    break  # Only need the first commit
                else:
                    # If no commits found, default to last 5 years
                    shard_years = list(range(2000, current_year + 2))

            # Robust extraction: Handle cases where 'url' might be a list (from different scrapers)
            if isinstance(raw_url_val, list) and len(raw_url_val) > 0:
                raw_url_val = raw_url_val[0]
            
            if not (isinstance(raw_url_val, str) and raw_url_val):
                continue
                
            # LOGIC: If C++, split into 1-year chunks. If others, run as one block.
            # You can add 'or p.get("commits", 0) > 5000' if you want to shard large Java repos too.
            if p.get('language') == 'C++':
                for i in range(len(shard_years) - 1):
                    s_date = datetime(shard_years[i], 1, 1)
                    e_date = datetime(shard_years[i+1], 1, 1)
                    
                    # Stop creating future shards
                    if s_date > datetime.now(): break
                    
                    # Append Sharded Job
                    jobs.append((p['name'], raw_url_val, s_date, e_date))
            else:
                # Append Single Job (Dates = None)
                jobs.append((p['name'], raw_url_val, None, None))

        if not jobs:
            print("No new projects found to mine (Quotas may be full).")
            return

        total_jobs = len(jobs)
        print(f"[INFO] Starting parallel mining. Work split into {total_jobs} segments.")
        
        # Determine number of workers based on available CPU cores.
        # Allow overriding via MAX_WORKERS env var to cap concurrency for large repos.
        env_max = os.getenv("MAX_WORKERS")
        if env_max and env_max.isdigit():
            max_workers = int(env_max)
        else:
            # Default: modest oversubscription to hide I/O latency on small repos
            max_workers = (os.cpu_count() or 6) * 2
        max_workers = max(1, min(total_jobs, max_workers))
        
        print(f"[INFO] Using {max_workers} worker processes")
        
        # 'Manager' creates a shared state (Event) to allow synchronised stopping across processes
        with Manager() as manager:
            stop_event = manager.Event()
            futures = []

            # tqdm provides a visual progress bar in the console
            with ProcessPoolExecutor(max_workers=max_workers) as executor, \
                tqdm(total=total_jobs, desc="SHARDS PROGRESS", unit="shard") as overall_pbar:
                try:
                    # Submit all mining jobs to the pool
                    for p_name, url, start, end in jobs:
                        futures.append(executor.submit(
                            self.mine_repo, 
                            (p_name, url, start, end, stop_event)
                        ))

                    # Process results as they complete (as_completed)
                    for future in as_completed(futures):
                        result = future.result()
                        overall_pbar.update(1)

                        if result is None: continue

                        # Unpack results for logging
                        p_name, added, existing, error = result
                        
                        # Only print errors or significant updates to avoid clutter
                        if error:
                            overall_pbar.write(f"❌ {p_name}: {error}")
                        # Note: We don't print "Success" here for every shard to keep console clean,
                        # rely on SHOW_WORKER_ACTIVITY for detailed logs.

                except KeyboardInterrupt:
                    # Graceful shutdown on Ctrl+C while manager is still alive
                    overall_pbar.write("\n🛑 STOPPING MINER! Terminating processes...")
                    stop_event.set()
                    for f in futures: f.cancel()
                finally:
                    # Ensure all outstanding futures are cancelled before manager exits
                    stop_event.set()
                    for f in futures:
                        if not f.done(): f.cancel()
            
        # Create DB indexes after data insertion to ensure fast querying later
        print("[DB] Optimising database indices...")
        ensure_indexes()
        print("[SUCCESS] Cycle complete.")

if __name__ == "__main__":
    miner = Repo_miner()
    miner.run()