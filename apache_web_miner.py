import requests
from typing import List, Optional, Dict

# Define a class to fetch data from the Apache Foundation's projects JSON API and extract GitHub links.
class Apache_web_miner:
    def __init__(self, target_url: str):
        self.url = target_url
        self.data = {}
    
    # Fetch data from the specified URL and store it in the 'data' attribute.
    def fetch_data(self):
        try:
            response = requests.get(self.url)
            self.data = response.json()
            print(f"Data fetched successfully from {self.url}")
        except Exception as e:
            print(f"An error occurred: {e}")

    # Resolve redirects for a given link and return the final URL if it's a GitHub link.
    def resolve_redirect(self, link: str) -> Optional[str]:
        try:
            if not isinstance(link, str): return None
            if not link.startswith(('http:', 'https:')): return None

            print(f"Resolving redirect for {link}...")

            # Make a HEAD request to follow redirects
            response = requests.head(link, allow_redirects=True, timeout=5)
            
            # Check if the final URL is github.com
            if 'github.com' in response.url: return response.url
                
        # Handle any other exceptions that might occur during the request.
        except requests.RequestException: return None
        return None
    
    # Extract GitHub links from the fetched data and store them in a dictionary.
    def get_github_links(self):
        clean_list = {}

        for project_id, details in self.data.items():
            if 'repository' in details:
                repos = details['repository']
                github_links: List[str] = []

                for link in repos:
                    if not isinstance(link, str): continue

                    if 'github.com' in link and link not in github_links:
                        github_links.append(link)
                    else:
                        resolved_link = self.resolve_redirect(link)
                        if resolved_link:
                            # Avoid duplicates if the resolved link is already in the list
                            if resolved_link not in github_links:
                                github_links.append(resolved_link)

                if len(github_links) > 0:
                    name = details.get('name', project_id)
                    clean_list[name] = github_links

        return clean_list

if __name__ == "__main__":
    apache_url = "https://projects.apache.org/json/foundation/projects.json"
    my_miner = Apache_web_miner(apache_url)
    my_miner.fetch_data()
    print("Mining links (this might take a while)...")
    results = my_miner.get_github_links()
    print(f"Done. Found {len(results)} projects.")