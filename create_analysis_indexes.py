from pymongo import ASCENDING, DESCENDING
from db import get_collection, COMMIT_COLLECTION

commits = get_collection(COMMIT_COLLECTION)

commits.create_index([("project", ASCENDING), ("committer_date", DESCENDING)])
commits.create_index([("project", ASCENDING), ("commit_kind", ASCENDING)])  # from enrichment
commits.create_index([("repo_url", ASCENDING), ("committer_date", DESCENDING)])
commits.create_index([("hash", ASCENDING)])

print("Indexes created.")
