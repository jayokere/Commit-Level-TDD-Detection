import os
from pymongo import UpdateOne
from db import get_collection, REPO_COLLECTION, COMMIT_COLLECTION

def sync_commit_counts():
    """
    Calculates the actual number of commits per project in the commit collection
    and updates the repo collection to reflect these totals.
    """
    repo_col = get_collection(REPO_COLLECTION)
    commit_col = get_collection(COMMIT_COLLECTION)

    print("📊 Calculating commit counts from database...")

    # 1. Aggregate commit counts per project
    pipeline = [
        {
            "$group": {
                "_id": "$project", 
                "actual_count": {"$sum": 1}
            }
        }
    ]
    
    results = list(commit_col.aggregate(pipeline))
    
    if not results:
        print("ℹ️ No commits found in the database to count.")
        return

    print(f"📝 Preparing updates for {len(results)} projects...")

    # 2. Prepare bulk updates for the repo collection
    operations = []
    for entry in results:
        project_name = entry["_id"]
        count = entry["actual_count"]

        # We update the 'commit_count' field in mined-repos
        operations.append(
            UpdateOne(
                {"name": project_name}, 
                {"$set": {"commits": count}}
            )
        )

    # 3. Execute bulk write
    if operations:
        result = repo_col.bulk_write(operations)
        print(f"✅ Successfully updated {result.modified_count} repository records.")
    else:
        print("ℹ️ No records required updating.")

def run_sync_counts():
    """Wrapper to run the sync_commit_counts function."""
    try:
        sync_commit_counts()
    except Exception as e:
        print(f"❌ An error occurred during synchronisation: {e}")

if __name__ == "__main__":
    run_sync_counts()