import sys
import os

# Ensure parent directory is in sys.path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database.clean_db import run as clean_db
from database.sync_counts import run_sync_counts
from source_file_calculator import run_calculator
from lifecycle_analysis import run as lifecycle_analysis
from creation_analysis import run as creation_analysis
from static_analysis import run as static_analysis


def main() -> None:
    # Run Analysis Modules
    clean_db()
    run_calculator()
    run_sync_counts()
    static_analysis("4")
    lifecycle_analysis("4")
    creation_analysis("4")

if __name__ == "__main__":
    main()