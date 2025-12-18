import os
import sys
from multiprocessing import Manager
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from pydriller import Repository
import random

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
# Make this tunable via env var BATCH_SIZE (default 1000).
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))

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
            # Identify which of our candidates are already in the DB
            completed = [p for p in candidates if p['name'] in already_mined]
            current_count = len(completed)
            
            print(f"[{language_name}] Status: {current_count}/{target_quota} repositories mined.")
            
            # If we have reached the limit, do not queue any more projects for this language
            if current_count >= target_quota:
                print(f"   -> Quota met. Skipping {language_name}.")
                return []
            
            # Calculate how many new ones we need to reach the target
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
    def is_valid_file(file):
        """
        Filters files to ensure we only analyse Source Code or Test files.
        
        Args:
            file (ModifiedFile): A Pydriller file object.
            
        Returns:
            bool: True if the file should be mined, False otherwise.
        """
        return FileAnalyser.is_valid_file(file)
    
    @staticmethod
    def is_test_file(filename):
        """
        Determines if a file is a test file based on naming conventions.
        
        Args:
            filename (str): The name of the file to check.
            
        Returns:
            bool: True if the file is a test file, False otherwise.
        """
        return TestAnalyser.is_test_file(filename)
    
    @staticmethod
    def analyze_test_coverage(modified_files):
        """
        Analyzes a commit to determine which files are tests and which are being tested.
        
        Args:
            modified_files (list): List of ModifiedFile objects from a commit.
            
        Returns:
            dict: A dictionary containing test_files, source_files, and tested_files.
        """
        return TestAnalyser.analyze_test_coverage(modified_files)

    @staticmethod
    def mine_repo(args):
        """
        Worker function to mine a single repository. 
        Executed in a separate process via ProcessPoolExecutor.
        
        Args:
            args (tuple): A tuple containing (project_name, raw_url, stop_event).
            
        Returns:
            tuple: (project_name, new_commits_count, existing_count, error_message)
        """
        project_name, raw_url, stop_event = args
        
        # Guard clause: Return immediately if the global stop signal (Ctrl+C) is set
        if stop_event.is_set(): 
            return None

        repo_url = Repo_miner.clean_url(raw_url)
        if not repo_url:
            return (project_name, 0, 0, "Skipped: Invalid or missing URL")

        try:
            # Log worker activity only when explicitly enabled to avoid bar flicker in multiprocessing
            if SHOW_WORKER_ACTIVITY:
                worker_id = os.getpid()
                tqdm.write(f"[WORKER {worker_id}] ⚙️  Starting {project_name}...")
            
            if SHOW_WORKER_ACTIVITY:
                worker_id = os.getpid()
                tqdm.write(f"[WORKER {worker_id}] 📥 Cloning {project_name}...")
            
            # Initialise the Pydriller Repository object
            from miners.file_analyser import VALID_CODE_EXTENSIONS
            repo_obj = Repository(
                repo_url,
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
                tqdm.write(f"[WORKER {worker_id}] ✅ Completed {project_name} ({new_commits_mined} new commits).")
        
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
        for p in self.projects:
            raw_url_val = p.get('url')
            
            # Robust extraction: Handle cases where 'url' might be a list (from different scrapers)
            if isinstance(raw_url_val, list) and len(raw_url_val) > 0:
                raw_url_val = raw_url_val[0]
            
            if isinstance(raw_url_val, str) and raw_url_val:
                jobs.append((p['name'], raw_url_val))

        if not jobs:
            print("No new projects found to mine (Quotas may be full).")
            return

        total_jobs = len(jobs)
        print(f"[INFO] Starting RICH-METRIC mining cycle for {total_jobs} repositories...")
        
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
                tqdm(total=total_jobs, desc="TOTAL PROGRESS", unit="repo", position=0, leave=True, dynamic_ncols=True) as overall_pbar:
                try:
                    # Submit all mining jobs to the pool
                    for p_name, url in jobs:
                        futures.append(executor.submit(
                            self.mine_repo, 
                            (p_name, url, stop_event)
                        ))

                    # Process results as they complete (as_completed)
                    for future in as_completed(futures):
                        result = future.result()
                        overall_pbar.update(1)

                        # Explicit check for None to satisfy type safety checks
                        if result is None:
                            continue

                        # Unpack results for logging
                        p_name, added, existing, error = result
                        
                        if error:
                            overall_pbar.write(f"❌ {p_name}: {error}")
                        elif added > 0:
                            overall_pbar.write(f"✅ {p_name}: Added {added} rich commits.")
                        else:
                            overall_pbar.write(f"💤 {p_name}: No new commits.")

                except KeyboardInterrupt:
                    # Graceful shutdown on Ctrl+C while manager is still alive
                    overall_pbar.write("\n🛑 STOPPING MINER! Terminating processes...")
                    stop_event.set()
                    for f in futures:
                        f.cancel()
                finally:
                    # Ensure all outstanding futures are cancelled before manager exits
                    stop_event.set()
                    for f in futures:
                        if not f.done():
                            f.cancel()
            
        # Create DB indexes after data insertion to ensure fast querying later
        print("[DB] Optimising database indices...")
        ensure_indexes()
        print("[SUCCESS] Cycle complete.")

if __name__ == "__main__":
    miner = Repo_miner()
    miner.run()