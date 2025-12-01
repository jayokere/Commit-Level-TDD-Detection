# Import necessary libraries
from pydriller import Repository
from typing import Dict, List

# Internal Modules
from apache_web_miner import fetch_project_data
from utils import measure_time 
import miner_intro
    
# Main function
@measure_time
def main() -> None:
    miner_intro.runAll()

    # Fetch project data either from local file or by mining from Apache.
    projects: Dict[str, List[str]] = fetch_project_data()
    print(f"Ready to process {len(projects)} projects.")

if __name__ == "__main__":
    main()
