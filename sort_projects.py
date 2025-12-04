import requests
import datetime
import json
import re
import os

from db import get_collection
from pymongo import UpdateOne
from typing import Dict, List, Tuple
from multiprocessing.pool import ThreadPool
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Internal Modules
import miner_intro
from utils import measure_time

"""
sort_projects.py

Utilities to sort Apache projects based on their GitHub commit activity.
"""

# Check if pyhton-dotenv is available to load environment variables from a .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, we assume the user has set variables in their system environment manually.
    pass

class RateLimitExceededError(Exception):
    """Custom exception raised when GitHub API rate limit is hit."""
    pass

class sort_projects:
    # Flag to ensure we only show the unauthenticated warning once
    is_warning_shown: bool = False
    def __init__(self) -> None:
        self.API_err: List[str] = []
        self.num_threads: int = 50

        # Initialise DB connection and get the collection for storing mined projects
        self.collection = get_collection("mined-repos")
        self.apache_projects: Dict[str, List[str]] = {}

        # Load existing projects from MongoDB into memory
        mined_entries = self.collection.find({}, {"name": 1, "urls": 1, "_id": 0})
        for entry in mined_entries:
            if "name" in entry and "urls" in entry:
                self.apache_projects[entry["name"]] = entry["urls"]
        
        self.session = requests.Session()
        
        # 1. Set Auth Headers once globally
        token = os.getenv("GITHUB_TOKEN")
        if token:
            self.session.headers.update({"Authorization": f"token {token}"})
        else:
            # Only print warning if not already shown (optional logic)
            if not self.is_warning_shown:
                print("💡 Running in unauthenticated mode (60 reqs/hr).")
                self.is_warning_shown = True

        # 2. Configure Retries (Try 3 times on 500/502/503 errors)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1, 
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"]
        )
        # Pool size 20 matches your thread count
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    def get_headers(self) -> Dict[str, str]:
        """
        Returns headers with auth if available, otherwise empty dict.
        """
        token = os.getenv("GITHUB_TOKEN")
        if token:
            # User has setup the token
            return {"Authorization": f"token {token}"}
        else:
            # User has NOT setup the token. 
            # We don't stop them, but they will be limited to 60 requests per hour.
            if  self.is_warning_shown is False:
                self.is_warning_shown = True
                print("💡 You are running in unauthenticated mode (60 reqs/hr).")
                print("   To fix this: Create a GITHUB_TOKEN and export it as an environment variable.")
                print("   This will increase your limit to 5,000 reqs/hr.\n")
            return {}

    def get_commit_count(self, repo_url: str) -> int:
        """
        Get the total number of commits in a git repository.

        Args:
            repo_url (str): The URL of the git repository.
        
        Returns:
            commit_count (int): The total number of commits in the repository.
        """
        # Remove trailing .git and trailing slashes to prevent 404s
        cleaned_url: str = repo_url.strip().rstrip("/")
        if cleaned_url.endswith(".git"):
            cleaned_url = cleaned_url[:-4]

        if "github.com" not in cleaned_url:
            return 0
        
        api_url: str = cleaned_url.replace("github.com", "api.github.com/repos") + "/commits?per_page=1"

        try:
            response = self.session.get(api_url, timeout=10)
            
            # --- RATE LIMIT CHECK ---
            # We check specific status codes OR the header value
            remaining = response.headers.get('X-RateLimit-Remaining')
            
            is_rate_limited = (
                response.status_code in [403, 429] and "rate limit" in response.text.lower()
            ) or (
                remaining is not None and int(remaining) == 0
            )

            if is_rate_limited:
                reset_val = response.headers.get('X-RateLimit-Reset')
                if reset_val:
                    reset_timestamp = int(reset_val)
                    reset_time = datetime.datetime.fromtimestamp(reset_timestamp, datetime.timezone.utc)
                    msg = f"RATE LIMIT REACHED! Resets at {reset_time}"
                else:
                    msg = "RATE LIMIT REACHED!"
                
                # Raise the custom exception to stop execution
                raise RateLimitExceededError(msg)
            # ------------------------
            
            if response.status_code == 200:
                # Check Link header for pagination
                link_header = response.headers.get('Link')
                if link_header:
                    match = re.search(r'&page=(\d+)>; rel="last"', link_header)
                    if match:
                        return int(match.group(1))
                
                # If no pagination, count the items in the response list
                data = response.json()
                if isinstance(data, list):
                    return len(data)
            else:
                return -response.status_code
            
        except RateLimitExceededError:
            # Re-raise this specific error so the main loop can catch it and stop
            raise
        except Exception as e:
            raise Exception(f"Connection Error: {e}")
        
        return 0
    
    def _analyze_project(self, args: Tuple[str, List[str]]) -> Tuple[str, List[str], int, List[str]]:
        """
        Worker function running in a separate thread.
        """
        project, links = args
        total_commits = 0
        errors = []

        for link in links:
            try:
                # Fetch commit count for each link
                count = self.get_commit_count(link)
                
                # Check for error codes (negative numbers)
                if count < 0:
                    status_code = abs(count)
                    errors.append(f"⚠️ API Error {status_code} for {link}")
                else:
                    total_commits += count
                    
            except RateLimitExceededError:
                raise 
            except Exception as e:
                # This catches the "Connection Error" raised above
                errors.append(str(e))
        
        return project, links, total_commits, errors

    @measure_time
    def sort_by_commit_count(self) -> int:
        """
        Sort Apache projects by their commit counts in descending order.

        Returns:
            len(sorted_dict) (int): The number of projects sorted.
        """

        # Temporary list to store (Name, Links, Count)
        scored_projects = []
        total_projects: int = len(self.apache_projects)

        print(f"🚀 Sorting {total_projects} projects by GitHub activity (Threads: {self.num_threads})...\n")

        projects_list = list(self.apache_projects.items())
        # Flag to track if the process was aborted
        aborted: bool = False 

        # Initialise ThreadPool
        pool = ThreadPool(self.num_threads)

        try:
            # imap_unordered yields results as soon as they finish
            for i, result in enumerate(pool.imap_unordered(self._analyze_project, projects_list)):
                
                # Unpack result from worker
                p_name, p_links, p_count, p_errors = result
                
                # Aggregate data
                scored_projects.append((p_name, p_links, p_count))
                self.API_err.extend(p_errors)
                
                # Update progress bar
                miner_intro.update_progress(i + 1, total_projects, label="ANALYZING")
        
        except RateLimitExceededError as e:
            print(f"\n\n🛑 {e}")
            print("❌ Execution stopped. Please try again later after the rate limit resets.")
            aborted = True
        except Exception as e:
            # Catch other unexpected errors in the thread pool
            print(f"\n\n⚠️ Unexpected error in thread pool: {e}")
            aborted = True
        finally:
            # Ensure threads are cleaned up
            pool.terminate()
            pool.join()

        print("\n")

        # If we hit rate limit, we abort without writing the file
        if aborted:
            print("⚠️  Process aborted due to Rate Limit.")
            print("   The database was NOT updated to preserve integrity.\n")
            return 0

        # Sort by commit count (index 2) in ascending order
        scored_projects.sort(key=lambda x: x[2], reverse=True)

        # Print API errors if any
        if self.API_err:
            print("\nAPI Errors encountered during sorting:")
            for err in self.API_err:
                print(err)
        
        # Update the DB with the sorted data
        print(f"\nUpdating projects in MongoDB...")
        updates = []
        for name, links, count in scored_projects:
            updates.append(UpdateOne({"name": name}, {"$set": {"commit_count": count}}))

        if updates:
            self.collection.bulk_write(updates)
            # Creates an index on commit_count (descending)
            # -1 means descending order (highest commits first)
            print("Creating index for fast sorting...")
            self.collection.create_index([("commit_count", -1)])
            
        print("✅ Done! The project list is now sorted by activity.")
        return len(scored_projects)

if __name__ == "__main__":
    sort_projects().sort_by_commit_count()