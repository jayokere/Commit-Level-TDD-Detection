import os
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.server_api import ServerApi

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
# Data Access Objects (DAO) - Specific Queries
# -------------------------------------------------------------------------

def get_projects_to_mine():
    """
    Fetches the list of projects from 'mined-repos', sorted by commit count (Smallest first).
    """
    col = get_collection(REPO_COLLECTION)
    cursor = col.find(
        {"commit_count": {"$exists": True}},
        {"name": 1, "urls": 1, "commit_count": 1, "_id": 0}
    ).sort("commit_count", ASCENDING)
    return list(cursor)

def get_existing_commit_hashes(project_name):
    """
    Returns a Python Set containing all commit hashes already saved for a project.
    Used for gap-filling to ensure 100% data completeness.
    """
    col = get_collection(COMMIT_COLLECTION)
    # Projection: Only return the hash field to save bandwidth
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
    # Index for fast project lookups
    col.create_index([("project", ASCENDING)])
    # Index for checking existing hashes (Vital for get_existing_commit_hashes)
    col.create_index([("hash", ASCENDING)])
    # Index for time-based analysis
    col.create_index([("date", DESCENDING)])
    print("[DB] Indexes verified.")