# Import necessary libraries
from pydriller import Repository

# Internal Modules
from utilities.miner_intro import run_all as miner_intro
from mining.apache_miner import run_all as apache_miner
from database.db import get_collection
from utilities.utils import measure_time
from mining.repo_miner import Repo_miner 
from analysis.run_analysis import main as run_analysis

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

    # Run Analysis Modules
    run_analysis()

if __name__ == "__main__":
    main()