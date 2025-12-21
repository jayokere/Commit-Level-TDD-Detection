from pymongo import UpdateOne
import re

from db import get_collection, COMMIT_COLLECTION  # reuse your existing DB connector


TEST_PATTERNS = [
    # --- Generic test directories (language-agnostic) ---
    re.compile(r"(^|.*/)(test|tests|testing|spec|specs)(/|/.*)", re.IGNORECASE),

    # --- Java / JVM conventions ---
    re.compile(r".*/src/test/.*", re.IGNORECASE),
    re.compile(r".*Test(s|Case)?\.java$", re.IGNORECASE),
    re.compile(r".*IT\.java$", re.IGNORECASE),
    re.compile(r".*Spec\.java$", re.IGNORECASE),

    # --- Python conventions (pytest/unittest common naming) ---
    re.compile(r".*/tests/.*\.py$", re.IGNORECASE),
    re.compile(r".*/test/.*\.py$", re.IGNORECASE),
    re.compile(r".*/testing/.*\.py$", re.IGNORECASE),
    re.compile(r"(^|.*/)(test_.*|.*_test)\.py$", re.IGNORECASE),

    # --- C / C++ conventions (common layouts and naming) ---
    re.compile(r".*/(gtest|googletest|catch2|doctest)(/|/.*)", re.IGNORECASE),
    re.compile(r"(^|.*/)(test_.*|.*_test)\.(c|cc|cpp|cxx|h|hpp|hh|hxx)$", re.IGNORECASE),
]

# Optional: exclude known non-test directories that contain "test" as substring.
# (Keep conservative; false negatives are worse than false positives for adoption rate.)
EXCLUDE_PATTERNS = [
    re.compile(r".*/contest/.*", re.IGNORECASE),
]

def is_test_path(path: str) -> bool:
    if not path:
        return False

    p = path.replace("\\", "/")

    if any(rx.match(p) for rx in EXCLUDE_PATTERNS):
        return False

    return any(rx.match(p) for rx in TEST_PATTERNS)


def extract_paths(modified_files):
    """
    Your mined schema stores per-file data as objects containing 'filename'.
    Fall back to string entries if present.
    """
    paths = []
    for f in (modified_files or []):
        if isinstance(f, str):
            paths.append(f)
        elif isinstance(f, dict):
            paths.append(f.get("filename") or "")
    return [p for p in paths if p]

def main():
    commits = get_collection(COMMIT_COLLECTION)

    BATCH = 500
    ops = []

    cursor = commits.find(
        {"tdd_enriched": {"$ne": True}},
        {"modified_files": 1}
    )

    n = 0
    for c in cursor:
        paths = extract_paths(c.get("modified_files"))
        test_touched = sum(1 for p in paths if is_test_path(p))
        prod_touched = sum(1 for p in paths if not is_test_path(p))

        has_test = test_touched > 0
        has_prod = prod_touched > 0

        if has_test and has_prod:
            kind = "MIXED"
        elif has_test:
            kind = "TEST_ONLY"
        elif has_prod:
            kind = "PROD_ONLY"
        else:
            kind = "NO_CODE"

        ops.append(UpdateOne(
            {"_id": c["_id"]},
            {"$set": {
                "tdd_enriched": True,
                "commit_kind": kind,
                "has_test_changes": has_test,
                "has_prod_changes": has_prod,
                "test_files_touched": test_touched,
                "prod_files_touched": prod_touched,
            }}
        ))
        n += 1

        if len(ops) >= BATCH:
            commits.bulk_write(ops, ordered=False)
            ops.clear()

    if ops:
        commits.bulk_write(ops, ordered=False)

    print(f"Enriched {n} commits.")

if __name__ == "__main__":
    main()
