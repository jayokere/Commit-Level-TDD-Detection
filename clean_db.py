import sys
from tqdm import tqdm
from pymongo import DeleteOne
from db import get_collection, COMMIT_COLLECTION

def clean_duplicates():
    """
    Finds and removes duplicate commits in the database based on the 'hash' and 'project' fields.
    Keeps one instance and removes the rest.
    """
    col = get_collection(COMMIT_COLLECTION)
    
    print("Analysing database for duplicate commits...")
    
    # Aggregation Pipeline to find duplicates
    # Grouped by project and hash, then count them.
    pipeline = [
        {
            "$group": {
                "_id": {"project": "$project", "hash": "$hash"},
                "count": {"$sum": 1},
                "ids": {"$push": "$_id"} # Stores the _ids of the duplicates
            }
        },
        {
            "$match": {
                "count": {"$gt": 1} # Only keeps groups with more than 1 document
            }
        }
    ]
    
    duplicates = list(col.aggregate(pipeline, allowDiskUse=True))
    total_duplicates_groups = len(duplicates)
    
    if total_duplicates_groups == 0:
        print("✅ No duplicate commits found.")
        return

    print(f"⚠️ Found {total_duplicates_groups} groups of duplicate commits.")
    
    bulk_ops = []
    removed_count = 0
    
    # Iterate and Prepare Delete Operations
    for group in tqdm(duplicates, desc="Processing duplicates"):
        # We have a list of _ids. We keep the first one and delete the rest.
        # Ideally, we might want to keep the one with the most info, 
        # but usually duplicates are identical.
        ids_to_remove = group["ids"][1:] # Skip the first one
        
        for _id in ids_to_remove:
            bulk_ops.append(DeleteOne({"_id": _id}))
            removed_count += 1
            
            # Execute in batches of 1000 to be safe
            if len(bulk_ops) >= 1000:
                col.bulk_write(bulk_ops)
                bulk_ops = []

    # 3. Final Flush
    if bulk_ops:
        col.bulk_write(bulk_ops)
        
    print(f"\n✅ Cleanup complete. Removed {removed_count} duplicate documents.")

def run():
    clean_duplicates()

if __name__ == "__main__":
    confirm = input("Are you sure you want to scan and delete duplicate commits from your DB. Type 'clean' to proceed: ")
    if confirm.lower() == "clean":
        clean_duplicates()
    else:
        print("Operation cancelled.")