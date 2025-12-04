from concurrent.futures import Executor, ProcessPoolExecutor, as_completed, TimeoutError
from pathlib import Path
import json
import os
import concurrent
from pydriller import Repository
from utils import measure_time
from tqdm import tqdm

"""
repo_miner.py

Utilities to load local data from ./data and to mine a git repository using PyDriller.
"""
def efficient_file_record(f):
    return {
        "filename": f.filename,
        "added": f.added_lines,
        "removed": f.deleted_lines,
        "change_type": f.change_type.name
    }

class Repo_miner:
    # Load Apache projects JSON into a module variable
    APACHE_PROJECTS_PATH = Path(__file__).resolve().parent / "data" / "apache_projects.json"
    if APACHE_PROJECTS_PATH.exists():
        with open(APACHE_PROJECTS_PATH, "r", encoding="utf-8") as _f:
            apache_projects = json.load(_f)
    else:
        apache_projects = {}

    @measure_time
    def mine_repo(self, repo_url):
        """
        Mine a git repository using PyDriller to extract commit data.
        
        Args:
            repo_url (str): The URL of the git repository to mine.
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing commit data.
        """
        # First pass: count commits (cheap)
        total_commits = sum(1 for _ in Repository(repo_url).traverse_commits())

        commits_data = []
        progress = tqdm(
            total=total_commits,
            desc=f"Mining {repo_url}",
            unit="commit",
            leave=False
        )
        
        # Use PyDriller to traverse the repository
        for commit in Repository(repo_url).traverse_commits():
            commit_info = {
                'hash': commit.hash,
                'date': commit.committer_date.strftime("%Y-%m-%d %H:%M:%S"),
                'files_changed': {f.filename : f.diff for f in commit.modified_files},
                'size': commit.dmm_unit_size
            }
            commits_data.append(commit_info)
            progress.update(1)
        progress.close()
        
        return (repo_url, commits_data)


if __name__ == "__main__":
    miner = Repo_miner()
    repo_jobs = [(project, link) for project, links in miner.apache_projects.items() for link in links]

    print(f"[INFO] Mining {len(repo_jobs)} repositories using multithreading...")

    results_by_project = {}

    # Master progress bar for repositories
    with tqdm(total=len(repo_jobs), desc="Overall Progress", unit="repo") as repo_pbar:
        with ProcessPoolExecutor(max_workers=min(len(repo_jobs), 8)) as executor:

            future_to_job = {
                executor.submit(miner.mine_repo, repo_url): (project, repo_url)
                for (project, repo_url) in repo_jobs
            }

            for future in as_completed(future_to_job):
                project, repo_url = future_to_job[future]

                try:
                    url, commits_data = future.result(timeout=90)  

                    results_by_project.setdefault(project, []).append({
                        "repo_url": url,
                        "commits": commits_data
                    })

                    tqdm.write(f"[DONE] Finished mining: {url}")
                except TimeoutError:
                    tqdm.write(f"[TIMEOUT] Skipped {repo_url} after 10 minutes.")
                    continue

                except Exception as e:
                    tqdm.write(f"[ERROR] Failed to mine {repo_url}: {e}")

                repo_pbar.update(1)

    # Save results
    for project, repo_results in results_by_project.items():
        file_path = f"data/repos/{project}.json"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(repo_results, f, indent=4)

        print(f"[SAVED] {project} → {file_path}")

