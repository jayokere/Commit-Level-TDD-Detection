# Import necessary libraries
from pydriller import Repository

# Internal Modules
from utilities.miner_intro import run_all as miner_intro
from mining.apache_miner import run_all as apache_miner
from database.clean_db import run as clean_db
from database.db import get_collection
from utilities.utils import measure_time
from mining.repo_miner import Repo_miner 
from database.sync_counts import run_sync_counts
from analysis.source_file_calculator import run_calculator
from analysis.lifecycle_analysis import run as lifecycle_analysis
from analysis.creation_analysis import run as creation_analysis
from analysis.static_analysis import run as static_analysis

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

    static_analysis("4")

    lifecycle_analysis("4")

    creation_analysis("4")

if __name__ == "__main__":
    main()