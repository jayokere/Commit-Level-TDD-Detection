import os
import sys
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import PyMongoError, AutoReconnect, DocumentTooLarge
from pymongo.server_api import ServerApi
from typing import List, Dict, Set

# Load environment variables
load_dotenv(find_dotenv())

# Constants
DB_NAME = "mined-data"
REPO_COLLECTION = "mined-repos"
COMMIT_COLLECTION = "mined-commits"

# Module-level, per-process Mongo client (reused across calls)
_CLIENT = None
# Flag to ensure we only ask the user once per run
_CHOICE_MADE = False

def get_db_connection():
    """Establishes (or reuses) a per-process connection to the database."""
    global _CLIENT, _CHOICE_MADE

    if not _CHOICE_MADE and sys.stdin.isatty() and not os.getenv("DB_MODE_SELECTED"):
        print("\n" + "="*50)
        print("🔌 DATABASE CONNECTION SELECTION")
        print("="*50)
        print("1. 🐳 Local Docker (mongodb://localhost:27017/)")
        print("2. ☁️  Atlas Cloud (Credentials from .env)")
        print("="*50)
        
        try:
            choice = input("Select Database (1 or 2) [Default: 1]: ").strip()
        except EOFError:
            choice = "1" # Default if input fails
        
        if choice == "2":
            print("   -> Selected: Atlas Cloud")
            # Clear any local override to force fallback to Cloud creds
            if "MONGODB_CONNECTION_STRING" in os.environ:
                del os.environ["MONGODB_CONNECTION_STRING"]
        else:
            print("   -> Selected: Local Docker")
            # Set the env var so child processes know to use Local
            os.environ["MONGODB_CONNECTION_STRING"] = "mongodb://localhost:27017/"
            
        # Mark as done so we don't ask again
        os.environ["DB_MODE_SELECTED"] = "True"
        _CHOICE_MADE = True
        print("-" * 50 + "\n")

    # ---------------------------------------------------------
    # CONNECTION LOGIC
    # ---------------------------------------------------------
    if _CLIENT is None:
        # Check for a direct connection string (Localhost)
        connection_string = os.getenv('MONGODB_CONNECTION_STRING')
        
        # FALLBACK: If no string, use Atlas Cloud credentials
        if not connection_string:
            user = os.getenv('MONGODB_USER')
            pwd = os.getenv('MONGODB_PWD')
            if user and pwd:
                connection_string = (
                    f"mongodb+srv://{user}:{pwd}@mined-repos.gt9vypu.mongodb.net/?appName=Mined-Repos"
                )
            else:
                raise ValueError("No MONGODB_CONNECTION_STRING or MONGODB_USER/PWD found in .env")

        if _CHOICE_MADE: 
            print(f"[DB] Connecting to: {'Localhost' if 'localhost' in connection_string else 'Atlas Cloud'}...")
        
        _CLIENT = MongoClient(
            connection_string,
            server_api=ServerApi('1'),
            serverSelectionTimeoutMS=int(os.getenv('MONGO_SERVER_SELECTION_TIMEOUT_MS', '30000')),
            connectTimeoutMS=int(os.getenv('MONGO_CONNECT_TIMEOUT_MS', '30000')),
            socketTimeoutMS=int(os.getenv('MONGO_SOCKET_TIMEOUT_MS', '30000')),
        )

    return _CLIENT[DB_NAME]

def get_collection(collection_name):
    """Generic helper to get a collection."""
    db = get_db_connection()
    return db[collection_name]

# -------------------------------------------------------------------------
# Data Access Objects (DAO) - Repo Management
# -------------------------------------------------------------------------

def get_existing_repo_urls(collection_name: str = REPO_COLLECTION) -> Set[str]:
    """
    Returns a Set of repository URLs that are already stored in the DB.
    This is used to skip mining repos we already have.
    """
    col = get_collection(collection_name)
    # Fetch only the 'repo_url' field
    cursor = col.find({}, {'repo_url': 1, '_id': 0})
    return {doc['repo_url'] for doc in cursor if 'repo_url' in doc}

def save_repo_batch(repos: List[Dict], collection_name: str = REPO_COLLECTION):
    """
    Performs a bulk upsert (update or insert) for a list of repository dictionaries.
    Using bulk_write is much faster than inserting one by one.
    """
    if not repos:
        return

    col = get_collection(collection_name)
    operations = []

    for repo in repos:
        # Handle transition: If input has 'url', remap it to 'repo_url'
        if 'url' in repo and 'repo_url' not in repo:
            repo['repo_url'] = repo.pop('url')
            
        # Skip if no URL found
        if 'repo_url' not in repo:
            continue
        
        # Update the record if 'url' matches, otherwise insert it.
        # This ensures we update commit counts for existing repos instead of duplicating them.
        operations.append(
            UpdateOne({"repo_url": repo["repo_url"]}, {"$set": repo}, upsert=True)
        )
    
    if operations:
        col.bulk_write(operations)
        # Ensure we have an index on commits for sorting later
        col.create_index([("commits", -1)])

# -------------------------------------------------------------------------
# Data Access Objects (DAO) - Commit Management
# -------------------------------------------------------------------------

def get_projects_to_mine():
    """
    Fetches the list of projects from 'mined-repos', sorted by commit count (Smallest first).
    """
    col = get_collection(REPO_COLLECTION)
    cursor = col.find().sort("commit_count", ASCENDING)
    return list(cursor)

def get_java_projects_to_mine():
    """
    Fetches the list of projects from 'mined-repos', sorted by commit count (Smallest first).
    """
    col = get_collection(REPO_COLLECTION)
    cursor = col.find({"language":"Java"}).sort("commit_count", ASCENDING)
    return list(cursor)  

def get_python_projects_to_mine():
    """
    Fetches the list of projects from 'mined-repos', sorted by commit count (Smallest first).
    """
    col = get_collection(REPO_COLLECTION)
    cursor = col.find({"language":"Python"}).sort("commit_count", ASCENDING)
    return list(cursor)   

def get_cpp_projects_to_mine():
    """
    Fetches the list of projects from 'mined-repos', sorted by commit count (Smallest first).
    """
    col = get_collection(REPO_COLLECTION)
    cursor = col.find({"language":"C++"}).sort("commit_count", ASCENDING)
    return list(cursor) 
def get_existing_commit_hashes(project_name):
    """
    Returns a Python Set containing all commit hashes already saved for a project.
    """
    col = get_collection(COMMIT_COLLECTION)
    cursor = col.find({"project": project_name}, {"hash": 1, "_id": 0})
    return {doc["hash"] for doc in cursor}

def save_commit_batch(commits):
    """
    Inserts a list of commit dictionaries into the database.
    Uses unordered insert to improve throughput and reduce tail latency.
    """
    if not commits:
        return
    col = get_collection(COMMIT_COLLECTION)
    try:
        # Try to insert the whole batch at once
        col.insert_many(commits, ordered=False)
        
    except (AutoReconnect, PyMongoError, OSError) as e:
        # If the batch is too large (Errno 34) or connection drops, we split it.
        # This is the "Divide and Conquer" strategy.
        size = len(commits)
        
        # Base case: If we are down to 1 commit and it still fails, log and skip it.
        if size <= 1:
            # Check if it's specifically a document size issue (MongoDB limit is 16MB)
            if isinstance(e, DocumentTooLarge) or "Result too large" in str(e):
                print(f"[DB WARN] Skipped single commit due to size limit: {commits[0].get('hash', 'unknown')}")
            else:
                print(f"[DB ERROR] Failed to save commit: {e}")
            return

        # Recursive step: Split batch into two halves
        mid = size // 2
        left_batch = commits[:mid]
        right_batch = commits[mid:]
        
        # Retry both halves recursively
        save_commit_batch(left_batch)
        save_commit_batch(right_batch)

def ensure_indexes():
    """
    Creates indexes to optimise future queries.
    """
    col = get_collection(COMMIT_COLLECTION)
    print("[DB] Ensuring indexes...")
    col.create_index([("project", ASCENDING)])
    col.create_index([("hash", ASCENDING)])
    # Align index with stored field name in commit docs
    col.create_index([("committer_date", DESCENDING)])
    print("[DB] Indexes verified.")
    
def get_all_mined_project_names():
    """
    Returns a set of project names that already exist in the mined-commits collection.
    Used to calculate quotas.
    """
    col = get_collection(COMMIT_COLLECTION)
    # .distinct() is very efficient for getting unique values
    return set(col.distinct("project"))

def get_project(project_name):
    """
    Fetches a single project document by name.
    """
    col = get_collection(REPO_COLLECTION)
    return col.find_one({"name": project_name})

def update_project(project_name, updates: Dict):
    """
    Updates fields of a project document.
    """
    col = get_collection(REPO_COLLECTION)
    col.update_one({"name": project_name}, {"$set": updates})