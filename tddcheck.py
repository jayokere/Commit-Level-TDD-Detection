from typing import Tuple, Dict, Any, Optional
from pymongo import UpdateOne
from pymongo.errors import PyMongoError
from db import get_collection, COMMIT_COLLECTION

FIELD_NAME = "TDD-Same"
PCT_FIELD = "TDDpct"

def classify(test_n: int, source_n: int, tested_n: int) -> str:
    # True if (test >= tested AND test != 0) OR (test > 0 AND source == 0)
    if ((test_n >= tested_n and test_n != 0) or (test_n > 0 and source_n == 0)):
        return "True"

    # Semi if test > 0 but test < tested
    if test_n > 0 and test_n < tested_n:
        return "Semi"

    # False if test == 0 and (source > 0 or tested > 0)
    if test_n == 0 and (source_n > 0 or tested_n > 0):
        return "False"

    return "False"

def get_counts(doc: Dict[str, Any]) -> Tuple[int, int, int]:
    tc = doc.get("test_coverage") or {}
    test_files = tc.get("test_files") or doc.get("test_files") or []
    source_files = tc.get("source_files") or doc.get("source_files") or []
    tested_files = tc.get("tested_files") or doc.get("tested_files") or []
    return len(test_files), len(source_files), len(tested_files)

def compute_pct(test_n: int, tested_n: int) -> Optional[float]:
    # (test / tested) * 100, with divide-by-zero guard
    if tested_n <= 0:
        return None  # stored as null in MongoDB
    return (test_n / tested_n) * 100.0

def main(batch_size: int = 500) -> None:
    col = get_collection(COMMIT_COLLECTION)

    projection = {
        "_id": 1,
        "test_coverage.test_files": 1,
        "test_coverage.source_files": 1,
        "test_coverage.tested_files": 1,
        "test_files": 1,
        "source_files": 1,
        "tested_files": 1,
    }

    cursor = col.find({}, projection=projection, batch_size=batch_size)

    ops = []
    processed = 0
    modified_total = 0

    try:
        for doc in cursor:
            processed += 1
            test_n, source_n, tested_n = get_counts(doc)

            tdd_same_val = classify(test_n, source_n, tested_n)
            tdd_pct_val = compute_pct(test_n, tested_n)

            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {FIELD_NAME: tdd_same_val, PCT_FIELD: tdd_pct_val}},
                )
            )

            if len(ops) >= batch_size:
                res = col.bulk_write(ops, ordered=False)
                modified_total += res.modified_count
                print(f"Processed: {processed}, Batch modified: {res.modified_count}, Total modified: {modified_total}")
                ops = []

        if ops:
            res = col.bulk_write(ops, ordered=False)
            modified_total += res.modified_count
            print(f"Processed: {processed}, Batch modified: {res.modified_count}, Total modified: {modified_total}")

        print(f"[DONE] Processed: {processed}, Total modified: {modified_total}")

    except PyMongoError as e:
        print(f"[ERROR] Mongo operation failed: {e}")
        raise

if __name__ == "__main__":
    main(batch_size=10000)
