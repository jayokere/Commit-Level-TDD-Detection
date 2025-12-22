import sys
from db import get_db_connection

def migrate_collections():
    """
    Renames the current 'mined-repos' to 'apache-repos' and creates a new
    'mined-repos' containing only the projects that actually have mined commits.
    """
    print("🔌 Connecting to database...")
    db = get_db_connection()
    
    # Collection names
    OLD_REPO_COLL = "mined-repos"
    NEW_ARCHIVE_COLL = "apache-repos"
    COMMITS_COLL = "mined-commits"

    # Rename existing collection (mined-repos -> apache-repos)
    # Check if the rename has already happened to avoid errors
    existing_collections = db.list_collection_names()
    
    if OLD_REPO_COLL in existing_collections and NEW_ARCHIVE_COLL not in existing_collections:
        if NEW_ARCHIVE_COLL in existing_collections:
            print(f"⚠️  Target collection '{NEW_ARCHIVE_COLL}' already exists.")
            print("   Aborting rename to prevent data loss.")
            return
        
        print(f"📦 Renaming '{OLD_REPO_COLL}' to '{NEW_ARCHIVE_COLL}'...")
        db[OLD_REPO_COLL].rename(NEW_ARCHIVE_COLL)
        print("   ✅ Rename successful.")
    elif NEW_ARCHIVE_COLL in existing_collections:
        print(f"ℹ️  '{OLD_REPO_COLL}' not found, but '{NEW_ARCHIVE_COLL}' exists.")
        print("   Assuming rename was already done. Proceeding to filter...")
    else:
        print(f"❌ Error: Could not find source collection '{OLD_REPO_COLL}'.")
        return

    # Identify which projects were actually mined
    print(f"\n🔍 Scanning '{COMMITS_COLL}' for active projects...")
    active_project_names = db[COMMITS_COLL].distinct("project")
    print(f"   Found {len(active_project_names)} projects with mined commits.")

    # Populate the new 'mined-repos' collection
    print(f"\n🚀 Creating new '{OLD_REPO_COLL}' with selected projects...")
    
    # Fetch the full repository documents from the archive (apache-repos)
    # matching the names found in mined-commits
    cursor = db[NEW_ARCHIVE_COLL].find({"name": {"$in": active_project_names}})
    selected_repos = list(cursor)

    if not selected_repos:
        print("   ⚠️  No matching repositories found in the archive.")
        return

    # Insert into the fresh 'mined-repos' collection
    # Note: simple insert_many is fine here as we are creating a fresh collection
    try:
        db[OLD_REPO_COLL].insert_many(selected_repos)
        print(f"   ✅ Successfully migrated {len(selected_repos)} repositories to '{OLD_REPO_COLL}'.")
        
        # Verify counts
        print("\n📊 Migration Summary:")
        print(f"   - {NEW_ARCHIVE_COLL} (Total Candidates): {db[NEW_ARCHIVE_COLL].count_documents({})}")
        print(f"   - {OLD_REPO_COLL} (Actually Mined):   {db[OLD_REPO_COLL].count_documents({})}")
        
    except Exception as e:
        print(f"   ❌ Error inserting documents: {e}")

if __name__ == "__main__":
    # Safety confirmation
    confirm = input("This might modify your DB. Are you sure you want to continue? (y/n): ")
    if confirm.lower() == 'y':
        migrate_collections()
    else:
        print("Operation cancelled.")