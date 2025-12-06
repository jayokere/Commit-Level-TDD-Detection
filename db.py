import os
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne
from pymongo.server_api import ServerApi
from typing import List, Dict, Set

# Load environment variables
load_dotenv(find_dotenv())

# Constants
DB_NAME = "mined-data"
REPO_COLLECTION = "mined-repos"
COMMIT_COLLECTION = "mined-commits"

def get_db_connection():
    """Establishes connection to the database."""
    user = os.getenv('MONGODB_USER')
    pwd = os.getenv('MONGODB_PWD')
    
    if not user or not pwd:
        raise ValueError("MongoDB credentials not found in environment variables.")

    connection_string = f"mongodb+srv://{user}:{pwd}@mined-repos.gt9vypu.mongodb.net/?appName=Mined-Repos"
    client = MongoClient(connection_string, server_api=ServerApi('1'))
    return client[DB_NAME]

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
    # Fetch only the 'url' field
    cursor = col.find({}, {'url': 1, '_id': 0})
    return {doc['url'] for doc in cursor if 'url' in doc}

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
        # Update the record if 'url' matches, otherwise insert it.
        # This ensures we update commit counts for existing repos instead of duplicating them.
        operations.append(
            UpdateOne({"url": repo["url"]}, {"$set": repo}, upsert=True)
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
    """
    if not commits:
        return
    col = get_collection(COMMIT_COLLECTION)
    col.insert_many(commits)

def ensure_indexes():
    """
    Creates indexes to optimise future queries.
    """
    col = get_collection(COMMIT_COLLECTION)
    print("[DB] Ensuring indexes...")
    col.create_index([("project", ASCENDING)])
    col.create_index([("hash", ASCENDING)])
    col.create_index([("date", DESCENDING)])
    print("[DB] Indexes verified.")