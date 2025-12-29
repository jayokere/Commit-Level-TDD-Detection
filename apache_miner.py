import os
import requests
import re
import datetime
import math 
import threading

from typing import List, Dict, Any, Optional
from collections import Counter
from multiprocessing.pool import ThreadPool
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Internal Utils
import db
import miner_intro 
from utils import measure_time, ping_target

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Constants
TARGET_ORG = "apache"
TARGET_LANGUAGES = {"Java", "Python", "C++"}
COLLECTION_NAME = "apache-repos"

class RateLimitExceededError(Exception):
    pass

class ApacheGitHubMiner:
    def __init__(self, num_threads: int = 50):
        self.num_threads = num_threads
        self.session = requests.Session()
        # Event flag to stop all threads instantly if a critical error occurs
        self._stop_event = threading.Event()
        self._setup_session()

    def _setup_session(self):
        token = os.getenv("GITHUB_TOKEN")
        if token:
            self.session.headers.update({"Authorization": f"token {token}"})
        
        retry_strategy = Retry(
            total=3, backoff_factor=1,
            status_forcelist=[500, 502, 503, 504], # Removed 429 from retry, we want to fail fast
            allowed_methods=["HEAD", "GET"]
        )
        adapter = HTTPAdapter(pool_connections=self.num_threads, pool_maxsize=self.num_threads, max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _check_rate_limit(self, response: requests.Response):
        """Checks headers for rate limits and raises a critical error if exceeded."""
        if self._stop_event.is_set():
            raise RateLimitExceededError("Global stop signal received.")

        remaining = response.headers.get('X-RateLimit-Remaining')
        
        is_limited = (response.status_code in [403, 429]) or (remaining is not None and int(remaining) == 0)
        
        if is_limited:
            reset_val = response.headers.get('X-RateLimit-Reset')
            reset_time = datetime.datetime.fromtimestamp(int(reset_val), datetime.timezone.utc) if reset_val else "Unknown"
            
            # Set the global stop event to silence other threads
            self._stop_event.set()
            raise RateLimitExceededError(f"RATE LIMIT REACHED! Resets at {reset_time}")

    def get_total_org_repos(self) -> int:
        """Fetches the total number of public repos for the org."""
        try:
            url = f"https://api.github.com/orgs/{TARGET_ORG}"
            resp = self.session.get(url, timeout=10)
            
            # Check for rate limit explicitly here too
            self._check_rate_limit(resp)
            
            if resp.status_code == 200:
                return resp.json().get("public_repos", 0)
        except RateLimitExceededError:
            raise # Re-raise to be caught in main loop
        except Exception as e:
            print(f"⚠️ Error getting repo count: {e}")
        return 0

    def _fetch_page(self, page_num: int) -> List[Dict[str, Any]]:
        """Worker function to fetch a single page of repositories."""
        # 1. Check if we should stop before doing anything
        if self._stop_event.is_set():
            return []

        url = f"https://api.github.com/orgs/{TARGET_ORG}/repos"
        params = {"type": "public", "per_page": 100, "page": page_num}
        candidates = []

        try:
            response = self.session.get(url, params=params, timeout=10)
            self._check_rate_limit(response)
            response.raise_for_status()
            
            repos = response.json()
            if isinstance(repos, list):
                for repo in repos:
                    lang = repo.get("language")
                    if lang in TARGET_LANGUAGES:
                        candidates.append({
                            "name": repo["name"],
                            "url": repo["html_url"],     
                            "api_url": repo["url"],      
                            "language": lang
                        })
        except RateLimitExceededError as e:
            # We assume the main thread or the first thread to hit this has already printed the error
            # We silently return empty list to exit gracefully
            pass 
        except Exception as e:
            # Only print unexpected errors if we aren't stopping
            if not self._stop_event.is_set():
                print(f"\n⚠️ Error fetching page {page_num}: {e}")
            
        return candidates

    def fetch_candidate_repos(self) -> List[Dict[str, Any]]:
        # 1. PING CHECK
        target_api = f"https://api.github.com/orgs/{TARGET_ORG}"
        print(f"🔍 Checking connection to {target_api}...")
        
        # Modified utils.ping_target returns False on 403/429
        if not ping_target(target_api):
            print("🛑 Aborting mining operation. Cannot reach GitHub API (Check Internet or Rate Limit).")
            return []

        # 2. Get total count
        try:
            total_repos = self.get_total_org_repos()
        except RateLimitExceededError as e:
            print(f"\n❌ {e}")
            return []

        # STRICT CHECK: If we can't get the count, we don't know the pages. Abort.
        if total_repos == 0:
            print("❌ Error: Received 0 repositories from GitHub. This usually indicates an authentication issue or empty org.")
            return []
        
        # 3. Calculate Pages
        total_pages = math.ceil(total_repos / 100)
        page_list = range(1, total_pages + 1)
        all_candidates = []
        fetched_count = 0
        
        print(f"⚡ Parallel fetching initialised: Retrieving {total_pages} pages using {self.num_threads} threads...\n")
        miner_intro.update_progress(0, total_repos, label="FETCHING LIST")

        # 4. Fetch Pages
        with ThreadPool(self.num_threads) as pool:
            for page_results in pool.imap_unordered(self._fetch_page, page_list):
                # If stop event was triggered by a worker, break the main loop
                if self._stop_event.is_set():
                    break

                all_candidates.extend(page_results)
                
                fetched_count += 100
                if fetched_count > total_repos: fetched_count = total_repos
                miner_intro.update_progress(fetched_count, total_repos, label="FETCHING REPOS")

        print("\n")
        
        # Final Check after loop
        if self._stop_event.is_set():
            print("❌ Process aborted due to Rate Limit.")
            return []

        if len(all_candidates) == 0:
            print("⚠️ No matching repositories found (Java/Python/C++).")
        else:
            print(f"✅ Found {len(all_candidates)} matching repositories.")
            
        return all_candidates

    def get_commit_count(self, api_url: str) -> int:
        if self._stop_event.is_set(): return 0
        
        try:
            response = self.session.get(f"{api_url}/commits?per_page=1", timeout=10)
            self._check_rate_limit(response)
            
            if response.status_code == 200:
                link_header = response.headers.get('Link')
                if link_header:
                    match = re.search(r'&page=(\d+)>; rel="last"', link_header)
                    if match: return int(match.group(1))
                
                data = response.json()
                return len(data) if isinstance(data, list) else 0
            return 0 
        except RateLimitExceededError:
            return 0 # Stop event is set inside check_rate_limit
        except Exception:
            return 0

    def process_repo(self, repo_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self._stop_event.is_set():
            return None

        commits = self.get_commit_count(repo_data["api_url"])
        return {
            "name": repo_data["name"],
            "url": repo_data["url"],
            "language": repo_data["language"],
            "commits": commits
        }

    @measure_time
    def run(self):
        # 1. Fetch Candidates
        candidates = self.fetch_candidate_repos()
        if not candidates:
            return

        print(f"🚀 Analysing and Storing {len(candidates)} repositories...")
        print("") 

        # 2. Process Mining
        results = []
        total = len(candidates)
        miner_intro.update_progress(0, total, label="ANALYSING")
        
        with ThreadPool(self.num_threads) as pool:
            for i, result in enumerate(pool.imap_unordered(self.process_repo, candidates)):
                if self._stop_event.is_set():
                    break
                
                if result: # Check if result is not None
                    results.append(result)
                
                miner_intro.update_progress(i + 1, total, label="ANALYSING")
        
        print("\n") 

        if self._stop_event.is_set():
            print("❌ Mining aborted early due to Rate Limit.")
            if not results:
                return

        # 3. Save
        print(f"💾 Saving {len(results)} records to MongoDB...")
        db.save_repo_batch(results, COLLECTION_NAME)
        
        # 4. Breakdown
        counts = Counter(r['language'] for r in results)
        print(f"✅ Successfully processed {counts['Java']} Java projects, {counts['Python']} Python projects, and {counts['C++']} C++ projects.")

def run_all():
    miner = ApacheGitHubMiner(num_threads=50)
    miner.run()

if __name__ == "__main__":
    miner_intro.run_all()
    run_all()