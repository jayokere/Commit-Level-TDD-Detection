import os
from dotenv import load_dotenv, find_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi

# Load env variables once when the module is imported
load_dotenv(find_dotenv())

DB_NAME = "mined-data"

def get_db_connection():
    """Establishes and returns the MongoDB client and database object."""
    user = os.getenv('MONGODB_USER')
    pwd = os.getenv('MONGODB_PWD')

    if not user or not pwd:
        raise ValueError("MongoDB credentials not found in environment variables.")

    connection_string = f"mongodb+srv://{user}:{pwd}@mined-repos.gt9vypu.mongodb.net/?appName=Mined-Repos"
    
    # Create a new client and connect to the server
    client = MongoClient(connection_string, server_api=ServerApi('1'))
    
    # Return the specific database object
    return client[DB_NAME]

def get_collection(collection_name: str):
    """Helper to get a specific collection from the database."""
    db = get_db_connection()
    return db[collection_name]

# Only run this if executing db.py directly (for testing connection)
if __name__ == "__main__":
    try:
        db = get_db_connection()
        # rapid check to see if we can talk to the server
        db.client.admin.command('ping')
        print(f"Successfully connected to database: {DB_NAME}")
        print(f"Collections: {db.list_collection_names()}")
    except Exception as e:
        print(f"Connection failed: {e}")