# Import necessary libraries
import json, os

# External Libraries
from pydriller import Repository
from typing import Dict, List

# Internal Modules
from apache_web_miner import Apache_web_miner 

# Constants
DATA_FILE: str = 'data/apache_projects.json'

# Function to fetch project data either from a local file or by mining from Apache
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
        apache_url: str = "https://projects.apache.org/json/foundation/projects.json"
        miner = Apache_web_miner(apache_url)
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
    
# Main function
def main() -> None:
    # Fetch project data either from local file or by mining from Apache.
    projects: Dict[str, List[str]] = fetch_project_data()
    print(f"Ready to process {len(projects)} projects.")

    # TODO: The TDD Analysis Logic 
    print("\n--- Starting TDD Analysis ---")


if __name__ == "__main__":
    main()
