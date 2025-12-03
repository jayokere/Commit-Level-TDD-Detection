# Import necessary libraries
import json
from pydriller import Repository
from pathlib import Path

# Internal Modules
import miner_intro
from apache_web_miner import fetch_project_data
from sort_projects import sort_projects
from utils import measure_time 

# Constants
APACHE_PROJECTS_PATH = Path(__file__).resolve().parent / "data" / "apache_projects.json"

# Main function
@measure_time
def main() -> None:
    miner_intro.run_all()

    # Fetch project data either from local file or by mining from Apache.
    fetch_project_data()

    # Sort projects by GitHub commit activity and update the JSON file.
    sort_projects().sort_by_commit_count()

    # Print summary
    with open(APACHE_PROJECTS_PATH, "r", encoding="utf-8") as f:
        project_count: int = len(json.load(f))
    print(f"Ready to process {project_count} projects.")

if __name__ == "__main__":
    main()
