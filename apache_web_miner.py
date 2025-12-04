# Import necessary libraries
import os
import json
import requests
import miner_intro

from utils import measure_time
from typing import List, Optional, Dict
from multiprocessing.pool import ThreadPool
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from db import get_collection

# Constants
APACHE_URL: str = "https://projects.apache.org/json/foundation/projects.json"
REPO_COLLECTION: str = "mined-repos"

# Define a class to fetch data from the Apache Foundation's projects JSON API and extract GitHub links.
class Apache_web_miner:
    def __init__(self, target_url: str, num_threads: int = 50):
        self.url = target_url
        self.data = {}
        self.num_threads = num_threads

        self.session = requests.Session()
        retry_strategy = Retry(
            total=1,                # Retry once
            backoff_factor=0.5,       
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    # Fetch data from the specified URL and store it in the 'data' attribute.
    def fetch_data(self):
        try:
            response = self.session.get(self.url)
            self.data = response.json()
            print(f"Data fetched successfully from {self.url}")
        except Exception as e:
            print(f"An error occurred fetching Apache registry: {e}\n")

    # Resolve redirects for a given link and return the final URL if it's a GitHub link.
    def resolve_redirect(self, link: str) -> Optional[str]:
        try:
            if not isinstance(link, str): return None
            if not link.startswith(('http:', 'https:')): return None

            # Make a HEAD request to follow redirects
            response = self.session.head(link, allow_redirects=True, timeout=5)
            
            # Check if the final URL is github.com
            if 'github.com' in response.url: return response.url
                
        # Handle any other exceptions that might occur during the request.
        except requests.RequestException: return None
        return None
    
    # Extract GitHub links from the fetched data and store them in a dictionary.
    def get_github_links(self) -> Dict[str, List[str]]:
        clean_list = {}

        # Search through all repository links to find non-GitHub links
        links_to_check = []
        for details in self.data.values():
            if 'repository' in details:
                for link in details['repository']:
                    # Only add strings that dont contain 'github.com'
                    if isinstance(link, str) and 'github.com' not in link:
                        links_to_check.append(link)

        total_links = len(links_to_check)
        print(f"Resolving {total_links} links using {self.num_threads} threads...\n")

        resolved_cache = {}
        with ThreadPool(self.num_threads) as pool:\
            # Define a helper to keep context
            def worker_wrapper(link):
                return link, self.resolve_redirect(link)
            
            # Use imap to preserve order and update progress bar
            for i, (original_link, result) in enumerate(pool.imap_unordered(worker_wrapper, links_to_check)):
                resolved_cache[original_link] = result
                # Update the progress bar
                miner_intro.update_progress(i + 1, total_links)
        
        print("\n")

        for project_id, details in self.data.items():
            if 'repository' in details:
                repos = details['repository']
                github_links: List[str] = []

                # Check if the link is already in the resolved_cache and add it if not.
                for link in repos:
                    if not isinstance(link, str): continue

                    if 'github.com' in link and link not in github_links:
                        github_links.append(link)
                    else:
                        resolved_link = resolved_cache.get(link)
                        if resolved_link and resolved_link not in github_links:
                                github_links.append(resolved_link)

                if len(github_links) > 0:
                    name = details.get('name', project_id)
                    clean_list[name] = github_links

        return clean_list
    
# Function to fetch project data either from a local file or by mining from Apache
@measure_time 
def fetch_project_data() -> Dict[str, List[str]]:
    # Connect to MongoDB and get the collection
    collection = get_collection(REPO_COLLECTION)
    
    # Check if the collection has existing documents
    if collection.count_documents({}) > 0:
        print(f"Loading data from MongoDB collection: {REPO_COLLECTION}...")

        data: Dict[str, List[str]] = {}
        mined_entries = collection.find({}, {'name': 1, 'urls': 1, '_id': 0})
        
        for entry in mined_entries:
            if 'name' in entry and 'urls' in entry:
                data[entry['name']] = entry['urls']
                
        return data
    else:
        print("No data found in Database. Mining data from Apache...")
        
        miner = Apache_web_miner(APACHE_URL)
        miner.fetch_data()
        links: Dict[str, List[str]] = miner.get_github_links()

        print(f"Saving new data to MongoDB collection {REPO_COLLECTION}...")
        
        documents = [{"name": name, "urls": urls} for name, urls in links.items()]
        
        if documents:
            collection.insert_many(documents)
            
        return links

if __name__ == "__main__":
    fetch_project_data()