#checking why python TDD rates are very low, maybe because not many tdd commits?
from db import get_collection, COMMIT_COLLECTION

commits = get_collection(COMMIT_COLLECTION)

pipeline = [
    {"$match": {"tdd_enriched": True, "commit_kind": {"$ne": "NO_CODE"}}},
    {"$lookup": {"from": "mined-repos", "localField": "repo_url", "foreignField": "url", "as": "repo"}},
    {"$unwind": "$repo"},
    {"$group": {
        "_id": "$repo.language",
        "total": {"$sum": 1},
        "tdd": {"$sum": {"$cond": [{"$in": ["$commit_kind", ["TEST_ONLY", "MIXED"]]}, 1, 0]}}
    }},
    {"$addFields": {"tdd_percentage": {"$multiply": [{"$divide": ["$tdd", "$total"]}, 100]}}},
    {"$sort": {"total": -1}}
]

print(list(commits.aggregate(pipeline, allowDiskUse=True)))
