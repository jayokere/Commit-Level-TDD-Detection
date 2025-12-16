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
    get_existing_commit_hashes, 
    save_commit_batch, 
    ensure_indexes,
    # Note: Ensure this function is added to db.py as discussed
    get_all_mined_project_names 
)

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
BATCH_SIZE = 2000 

# Whitelist of file extensions to classify as "Source Code" or "Test Code".
# Non-functional files (e.g., .md, .txt, .xml) are excluded to optimise storage and processing time.
VALID_CODE_EXTENSIONS = {
    '.java', '.py', '.js', '.ts', '.c', '.cpp', '.h', '.hpp', 
    '.cs', '.go', '.rb', '.php', '.scala', '.kt', '.rs', '.swift', 
    '.m', '.mm', '.groovy', '.clj'
}

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
        if not file.filename: return False
        
        # 1. Identify Test files explicitly by filename conventions (e.g., 'CalculatorTest.java')
        if "test" in file.filename.lower():
            return True

        # 2. Identify Source Code by checking the file extension against the approved whitelist
        _, ext = os.path.splitext(file.filename)
        if ext.lower() in VALID_CODE_EXTENSIONS:
            return True
            
        return False
    
    @staticmethod
    def is_test_file(filename):
        """
        Determines if a file is a test file based on naming conventions.
        
        Args:
            filename (str): The name of the file to check.
            
        Returns:
            bool: True if the file is a test file, False otherwise.
        """
        if not filename:
            return False
        
        lower_filename = filename.lower()
        # Common test file patterns
        test_patterns = ['test', 'tests', 'spec', 'specs']
        return any(pattern in lower_filename for pattern in test_patterns)
    
    @staticmethod
    def extract_tested_files_from_methods(test_methods, all_files):
        """
        Identifies which source files are being tested based on test method names.
        
        This function analyzes test method names to extract the class/module names
        being tested, then matches them against the list of modified files.
        
        Common patterns recognized:
        - testMethodName / test_method_name
        - TestClassName / test_class_name
        - Method names containing the tested class name
        
        Args:
            test_methods (list): List of test method names.
            all_files (list): List of all file objects in the commit.
            
        Returns:
            list: List of filenames that are likely being tested.
        """
        if not test_methods or not all_files:
            return []
        
        tested_files = set()
        
        # Extract potential class/module names from test methods
        # Example: testCalculatorAdd -> Calculator
        # Example: test_square_area -> square
        tested_components = set()
        
        for method_name in test_methods:
            if not method_name:
                continue
            
            method_lower = method_name.lower()
            
            # Remove common test prefixes/suffixes
            cleaned = method_lower
            for prefix in ['test_', 'test', 'should_', 'should', 'when_', 'when']:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
                    break
            
            for suffix in ['_test', 'test', '_spec', 'spec']:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[:-len(suffix)]
                    break
            
            # Split by underscores or camelCase to extract component names
            # Example: calculate_area -> ['calculate', 'area']
            parts = cleaned.split('_')
            tested_components.update(parts)
            
            # Also handle camelCase: calculateArea -> ['calculate', 'Area']
            import re
            camel_parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', method_name)
            tested_components.update([p.lower() for p in camel_parts if len(p) > 2])
        
        # Match extracted components against source files
        for file_obj in all_files:
            if not file_obj.filename:
                continue
            
            # Skip test files themselves
            if Repo_miner.is_test_file(file_obj.filename):
                continue
            
            # Extract base filename without path and extension
            base_filename = os.path.basename(file_obj.filename)
            filename_without_ext = os.path.splitext(base_filename)[0].lower()
            
            # Check if any tested component matches this filename
            for component in tested_components:
                if component and len(component) > 2:  # Ignore very short matches
                    if component in filename_without_ext or filename_without_ext in component:
                        tested_files.add(file_obj.filename)
                        break
        
        return list(tested_files)
    
    @staticmethod
    def analyze_test_coverage(modified_files):
        """
        Analyzes a commit to determine which files are tests and which are being tested.
        
        Args:
            modified_files (list): List of ModifiedFile objects from a commit.
            
        Returns:
            dict: A dictionary containing:
                - 'test_files': List of test file information
                - 'source_files': List of source file information
                - 'tested_files': List of source files that have associated tests
        """
        test_files = []
        source_files = []
        all_test_methods = []
        
        # First pass: categorize files and collect test methods
        for f in modified_files:
            if not f.filename:
                continue
            
            file_info = {
                'filename': f.filename,
                'changed_methods': [m.name for m in f.changed_methods] if f.changed_methods else []
            }
            
            if Repo_miner.is_test_file(f.filename):
                test_files.append(file_info)
                all_test_methods.extend(file_info['changed_methods'])
            else:
                source_files.append(file_info)
        
        # Second pass: identify which source files are being tested
        tested_files = Repo_miner.extract_tested_files_from_methods(
            all_test_methods,
            modified_files
        )
        
        return {
            'test_files': test_files,
            'source_files': source_files,
            'tested_files': tested_files
        }

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
            # --- DUPLICATE PREVENTION ---
            # Retrieve all commit hashes already stored for this project.
            # This allows the miner to skip previously processed commits, enabling 
            # resumable execution if the script is interrupted.
            existing_hashes = get_existing_commit_hashes(project_name)
            initial_count = len(existing_hashes)
            
            # Initialise the Pydriller Repository object
            repo_miner = Repository(repo_url)
            commits_buffer = []
            new_commits_mined = 0
            
            # Traverse the git history of the repository
            for commit in repo_miner.traverse_commits():
                if stop_event.is_set(): return None
                
                # Check: If hash exists in the DB, skip processing entirely
                if commit.hash in existing_hashes: 
                    continue

                # Filter: Only keep relevant files (Source/Tests) based on criteria
                relevant_files_objs = [f for f in commit.modified_files if Repo_miner.is_valid_file(f)]
                
                if not relevant_files_objs:
                    continue

                # --- METRIC EXTRACTION ---
                # Note: DMM is a commit-level metric in PyDriller, representing the 
                # maintainability risk profile of the change.
                dmm_unit_size = commit.dmm_unit_size

                # Process individual files to extract complexity and method changes
                processed_files = []
                for f in relevant_files_objs:
                    processed_files.append({
                        "filename": f.filename,
                        # Cyclomatic Complexity (MCC)
                        "complexity": f.complexity, 
                        # Extract only the method names from the Method objects list
                        "changed_methods": [m.name for m in f.changed_methods]
                    })
                
                # Analyze test coverage to identify tested files
                test_coverage = Repo_miner.analyze_test_coverage(relevant_files_objs)

                # Construct the document object for MongoDB
                commit_info = {
                    'project': project_name,
                    'repo_url': repo_url,
                    'hash': commit.hash,
                    'committer_date': commit.committer_date,
                    'dmm_unit_size': dmm_unit_size, 
                    'modified_files': processed_files,
                    'test_coverage': test_coverage
                }
                
                commits_buffer.append(commit_info)
                new_commits_mined += 1

                # Batch write to DB to avoid hitting database connection limits
                if len(commits_buffer) >= BATCH_SIZE:
                    save_commit_batch(commits_buffer)
                    commits_buffer = []

            # Save any remaining commits in the buffer after the loop concludes
            if commits_buffer:
                save_commit_batch(commits_buffer)
        
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
        
        # Determine number of workers based on available CPU cores to ensure full performance
        # Allow modest oversubscription to better hide I/O latency; safe for I/O-heavy tasks
        max_workers = (os.cpu_count() or 4) * 2
        max_workers = min(total_jobs, max_workers)
        
        print(f"[INFO] Using {max_workers} worker processes")
        
        # 'Manager' creates a shared state (Event) to allow synchronised stopping across processes
        with Manager() as manager:
            stop_event = manager.Event()
            futures = []

            # tqdm provides a visual progress bar in the console
            with ProcessPoolExecutor(max_workers=max_workers) as executor, \
                 tqdm(total=total_jobs, desc="TOTAL PROGRESS", unit="repo") as overall_pbar:
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
                            tqdm.write(f"❌ {p_name}: {error}")
                        elif added > 0:
                            tqdm.write(f"✅ {p_name}: Added {added} rich commits.")
                        else:
                            tqdm.write(f"💤 {p_name}: No new commits.")

                except KeyboardInterrupt:
                    # Graceful shutdown on Ctrl+C while manager is still alive
                    tqdm.write("\n🛑 STOPPING MINER! Terminating processes...")
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