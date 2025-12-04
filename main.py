# Import necessary libraries
from pydriller import Repository

# Internal Modules
import miner_intro
from db import get_collection
from apache_web_miner import fetch_project_data
from sort_projects import sort_projects
from utils import measure_time 

# Main function
@measure_time
def main() -> None:
    miner_intro.run_all()

    # Fetch project data either from DB or by mining from Apache.
    fetch_project_data()

    # Update projects in MongoDB with their GitHub commit activity.
    sort_projects().sort_by_commit_count()

    # Get summary from Database
    project_count = get_collection("mined-repos").count_documents({})
    print(f"\nReady to process {project_count} projects...")

if __name__ == "__main__":
    main()