# Import necessary libraries
from pydriller import Repository

# Internal Modules
import miner_intro
import apache_miner
import clean_db
from db import get_collection
from utils import measure_time
from repo_miner import Repo_miner 

# Main function
@measure_time
def main() -> None:
    miner_intro.run_all()

    # Run Apache GitHub Miner
    apache_miner.run_all()

    # Get summary from Database
    project_count = get_collection("mined-repos").count_documents({})
    print(f"\nReady to process {project_count} projects...")

    # Run Repository Miner
    Repo_miner().run()

    # Clean duplicate commits from Database
    clean_db.run()

if __name__ == "__main__":
    main()