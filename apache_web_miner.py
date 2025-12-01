# Import necessary libraries
import requests, os, json, miner_intro
from utils import measure_time
from typing import List, Optional, Dict
from multiprocessing.pool import ThreadPool

# Constants
DATA_FILE: str = 'data/apache_projects.json'
APACHE_URL: str = "https://projects.apache.org/json/foundation/projects.json"

# Define a class to fetch data from the Apache Foundation's projects JSON API and extract GitHub links.
class Apache_web_miner:
    def __init__(self, target_url: str, num_threads: int = 150):
        self.url = target_url
        self.data = {}
        self.num_threads = num_threads
    
    # Fetch data from the specified URL and store it in the 'data' attribute.
    def fetch_data(self):
        try:
            response = requests.get(self.url)
            self.data = response.json()
            print(f"Data fetched successfully from {self.url}")
        except Exception as e:
            print(f"An error occurred: {e}\n")

    # Resolve redirects for a given link and return the final URL if it's a GitHub link.
    def resolve_redirect(self, link: str) -> Optional[str]:
        try:
            if not isinstance(link, str): return None
            if not link.startswith(('http:', 'https:')): return None

            # Make a HEAD request to follow redirects
            response = requests.head(link, allow_redirects=True, timeout=5)
            
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

        results = []
        with ThreadPool(self.num_threads) as pool:
            # Use imap to preserve order and update progress bar
            for i, result in enumerate(pool.imap(self.resolve_redirect, links_to_check)):
                results.append(result)
                # Update the progress bar
                miner_intro.update_progress(i + 1, total_links)
        
        print("\n")

        # Create a "Lookup Table" (Dictionary) for resolved links.
        resolved_cache = dict(zip(links_to_check, results))

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
    # Load data from local file if it exists. Otherwise, fetch data from Apache.
    if os.path.exists(DATA_FILE):
        print(f"Loading data from local file: {DATA_FILE}...")
        with open(DATA_FILE, 'r') as f:
            data: Dict[str, List[str]] = json.load(f)
            return data
    else:
        print("Local file not found. Mining data from Apache...")
        
        # Fetch data from Apache's projects JSON API and extract GitHub links.
        miner = Apache_web_miner(APACHE_URL)
        miner.fetch_data()
        links: Dict[str, List[str]] = miner.get_github_links()

        # Save the fetched data to a local file for future use.
        print(f"Saving new data to {DATA_FILE}...")
        folder_path = os.path.dirname(DATA_FILE)
        if folder_path: 
            os.makedirs(folder_path, exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(links, f, indent=4)
            
        return links

if __name__ == "__main__":
    fetch_project_data()