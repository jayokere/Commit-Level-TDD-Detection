# Import necessary libraries
from pydriller import Repository

# Internal Modules
from miner_intro import run_all as miner_intro
from apache_miner import run_all as apache_miner
from clean_db import run as clean_db
from db import get_collection
from utils import measure_time
from repo_miner import Repo_miner 
from sync_counts import run_sync_counts
from source_file_calculator import run_calculator

# Main function
@measure_time
def main() -> None:
    miner_intro()

    # Run Apache GitHub Miner
    apache_miner()

    # Get summary from Database
    project_count = get_collection("mined-repos").count_documents({})
    print(f"\nReady to process {project_count} projects...")

    # Run Repository Miner
    Repo_miner().run()

    # Clean duplicate commits from Database
    clean_db()

    run_calculator()

    run_sync_counts()

if __name__ == "__main__":
    main()