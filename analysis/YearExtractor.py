import csv
from pathlib import Path
from typing import Any, Dict, List

from database.db import get_collection  

COMMITS_COLLECTION_NAME = "mined-commits"  
OUTPUT_PATH = Path(__file__).resolve().parent / "analysis-output" / "project_years.csv"


def main() -> None:
    commits = get_collection(COMMITS_COLLECTION_NAME)

    pipeline: List[Dict[str, Any]] = [
        {
            "$project": {
                "project": 1,
                "committer_date_dt": {
                    "$cond": [
                        {"$eq": [{"$type": "$committer_date"}, "date"]},
                        "$committer_date",
                        {"$toDate": "$committer_date"},
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": "$project",
                "first_commit": {"$min": "$committer_date_dt"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "project": "$_id",
                "start_year": {"$year": "$first_commit"},
            }
        },
        {"$sort": {"project": 1}},
    ]

    results = list(commits.aggregate(pipeline, allowDiskUse=True))

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["project", "start_year"])
        w.writeheader()
        for r in results:
            w.writerow({"project": r.get("project"), "start_year": int(r.get("start_year"))})

    print(f"Wrote {len(results)} rows to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
