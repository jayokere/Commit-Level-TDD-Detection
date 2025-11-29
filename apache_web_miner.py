import requests
from typing import List

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
    
    # Extract GitHub links from the fetched data and store them in a dictionary.
    def get_github_links(self):
        clean_list = {}

        for project_id, details in self.data.items():
            if 'repository' in details:
                repos = details['repository']
                github_links: List[str] = []

                for link in repos:
                    if 'github.com' in link:
                        github_links.append(link)

                if len(github_links) > 0:
                    name = details.get('name', project_id)
                    clean_list[name] = github_links

        return clean_list

if __name__ == "__main__":
    apache_url = "https://projects.apache.org/json/foundation/projects.json"
    my_miner = Apache_web_miner(apache_url)
    my_miner.fetch_data()
    print(my_miner.get_github_links())