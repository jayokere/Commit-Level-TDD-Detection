import os
import sys
from multiprocessing import Manager
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from pydriller import Repository

# Internal Modules
from utils import measure_time
from db import (
    get_projects_to_mine, 
    get_existing_commit_hashes, 
    save_commit_batch, 
    ensure_indexes
)

"""
repo_miner.py

Features:
1. SOURCE CODE MINING: Captures Tests AND Production code.
2. DUPLICATE PROTECTION: Checks DB before adding any commit.
3. TYPE SAFETY: Handling None URLs correctly.
4. FULL PERFORMANCE: Uses all available CPU cores.
"""

BATCH_SIZE = 2000 

# Whitelist of extensions to consider as "Source" or "Test" code.
VALID_CODE_EXTENSIONS = {
    '.java', '.py', '.js', '.ts', '.c', '.cpp', '.h', '.hpp', 
    '.cs', '.go', '.rb', '.php', '.scala', '.kt', '.rs', '.swift', 
    '.m', '.mm', '.groovy', '.clj'
}

class Repo_miner:
    def __init__(self):
        print("Fetching project list from database...")
        self.projects = get_projects_to_mine()

    @staticmethod
    def clean_url(url):
        """Fixes malformed URLs to prevent git errors."""
        if not url: return None
        url = url.strip().rstrip('/')
        if "github.com:" in url and "github.com:443" not in url:
            url = url.replace("github.com:", "github.com/")
        return url

    @staticmethod
    def identify_files(modified_files):
        """
        Filters files to keep ONLY Source Code and Tests.
        """
        kept_files = []

        for f in modified_files:
            if not f.filename: continue
            
            # 1. Check if it's explicitly a Test file (by name)
            if "test" in f.filename.lower():
                kept_files.append(f.filename)
                continue

            # 2. Check if it's Source Code (by extension)
            _, ext = os.path.splitext(f.filename)
            if ext.lower() in VALID_CODE_EXTENSIONS:
                kept_files.append(f.filename)

        return kept_files

    @staticmethod
    def mine_repo(args):
        project_name, raw_url, stop_event = args
        
        repo_url = Repo_miner.clean_url(raw_url)
        
        # --- FIX: GUARD CLAUSE FOR TYPE SAFETY ---
        # If clean_url returns None, we must stop here.
        # This satisfies Pylance that 'repo_url' is a string below.
        if not repo_url:
            return (project_name, 0, 0, "Skipped: Invalid or missing URL")
        
        if stop_event.is_set(): return None

        try:
            # 1. FETCH EXISTING HASHES (Duplicate Prevention)
            existing_hashes = get_existing_commit_hashes(project_name)
            initial_count = len(existing_hashes)
            
            # Now repo_url is guaranteed to be a string
            repo_miner = Repository(repo_url)
            commits_buffer = []
            new_commits_mined = 0
            
            for commit in repo_miner.traverse_commits():
                if stop_event.is_set(): return None
                
                # 2. STRICT DUPLICATE CHECK
                if commit.hash in existing_hashes: 
                    continue

                # Apply the relaxed filter (Tests OR Source)
                relevant_files = Repo_miner.identify_files(commit.modified_files)
                
                if not relevant_files:
                    continue

                commit_info = {
                    'project': project_name,
                    'repo_url': repo_url,
                    'hash': commit.hash,
                    'msg': commit.msg[:200], 
                    'date': commit.committer_date,
                    'files': relevant_files
                }
                commits_buffer.append(commit_info)
                new_commits_mined += 1

                if len(commits_buffer) >= BATCH_SIZE:
                    save_commit_batch(commits_buffer)
                    commits_buffer = []

            if commits_buffer:
                save_commit_batch(commits_buffer)
        
            return (project_name, new_commits_mined, initial_count, None)
            
        except Exception as e:
            return (project_name, 0, 0, str(e))

    @measure_time
    def run(self):
        jobs = []
        for p in self.projects:
            if 'urls' in p and p['urls']:
                jobs.append((p['name'], p['urls'][0]))

        if not jobs:
            print("No projects found to mine.")
            return

        total_jobs = len(jobs)
        print(f"[INFO] Starting CODE-ONLY mining cycle for {total_jobs} repositories...")
        
        # --- FULL PERFORMANCE ---
        max_workers = os.cpu_count() or 4
        max_workers = min(total_jobs, max_workers)
        
        print(f"[INFO] Using {max_workers} worker processes (Full Power)")
        print("\n" * (max_workers + 1)) 
        
        with Manager() as manager:
            stop_event = manager.Event()
            executor = ProcessPoolExecutor(max_workers=max_workers)
            futures = []

            with tqdm(total=total_jobs, desc="TOTAL PROGRESS", unit="repo",
                      bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} Repos processed [{elapsed}]",
                      file=sys.stdout) as overall_pbar:

                try:
                    for p_name, url in jobs:
                        futures.append(executor.submit(
                            self.mine_repo, 
                            (p_name, url, stop_event)
                        ))

                    for future in as_completed(futures):
                        result = future.result()
                        overall_pbar.update(1)
                        if result is None: continue

                        p_name, added, existing, error = result
                        
                        if error:
                            tqdm.write(f"❌ {p_name}: {error}")
                        elif added > 0:
                            tqdm.write(f"✅ {p_name}: Added {added} code commits (Skipped {existing} existing).")
                        else:
                            tqdm.write(f"💤 {p_name}: No new code commits.")

                except KeyboardInterrupt:
                    tqdm.write("\n\n🛑 STOPPING MINER! Please wait...")
                    stop_event.set()
                    if sys.version_info >= (3, 9):
                        executor.shutdown(wait=False, cancel_futures=True)
                    else:
                        executor.shutdown(wait=False)
                    sys.exit(1)
            
        ensure_indexes()
        print("[SUCCESS] Cycle complete.")

if __name__ == "__main__":
    miner = Repo_miner()
    miner.run()