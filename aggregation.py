from db import get_collection, COMMIT_COLLECTION

commits = get_collection(COMMIT_COLLECTION)

pipeline = [
    # Exclude NO_CODE from the population entirely
    {"$match": {"tdd_enriched": True, "commit_kind": {"$ne": "NO_CODE"}}},

    {"$group": {"_id": {"repo_url": "$repo_url", "kind": "$commit_kind"}, "count": {"$sum": 1}}},

    {"$group": {
        "_id": "$_id.repo_url",
        "total_commits": {"$sum": "$count"},
        "tdd_commits": {
            "$sum": {
                "$cond": [
                    {"$in": ["$_id.kind", ["TEST_ONLY", "MIXED"]]},
                    "$count",
                    0
                ]
            }
        }
    }},

    {"$addFields": {
        "project_adoption_rate": {
            "$cond": [
                {"$gt": ["$total_commits", 0]},
                {"$divide": ["$tdd_commits", "$total_commits"]},
                0
            ]
        }
    }},

    {"$lookup": {"from": "mined-repos", "localField": "_id", "foreignField": "url", "as": "repo"}},
    {"$unwind": "$repo"},

    {"$group": {
        "_id": "$repo.language",
        "projects": {"$sum": 1},
        "avg_project_adoption": {"$avg": "$project_adoption_rate"},
        "total_commits": {"$sum": "$total_commits"},
        "total_tdd_commits": {"$sum": "$tdd_commits"}
    }},

    {"$addFields": {
        "weighted_adoption": {
            "$cond": [
                {"$gt": ["$total_commits", 0]},
                {"$divide": ["$total_tdd_commits", "$total_commits"]},
                0
            ]
        }
    }},

    {"$sort": {"total_commits": -1}},
]

print(list(commits.aggregate(pipeline, allowDiskUse=True)))


pipeline_overall = [
    {"$match": {"tdd_enriched": True, "commit_kind": {"$ne": "NO_CODE"}}},
    {"$group": {
        "_id": None,
        "total": {"$sum": 1},
        "tdd": {"$sum": {"$cond": [{"$in": ["$commit_kind", ["TEST_ONLY", "MIXED"]]}, 1, 0]}}
    }},
    {"$addFields": {"tdd_percentage": {"$multiply": [{"$divide": ["$tdd", "$total"]}, 100]}}},
    {"$project": {"_id": 0, "total": 1, "tdd": 1, "tdd_percentage": 1}}
]

print("Overall TDD adoption (excluding NO_CODE):")
print(list(commits.aggregate(pipeline_overall, allowDiskUse=True)))

