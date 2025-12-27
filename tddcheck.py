from typing import Tuple, Dict, Any, List, Optional, Set
from pymongo import UpdateOne
from pymongo.errors import PyMongoError
from db import get_collection, COMMIT_COLLECTION  # uses your Atlas connection

FIELD_NAME = "TDD-Same"
PCT_FIELD = "TDDpct"


def _filename_list(value: Any) -> List[str]:
    """
    Accepts:
      - [{"filename": "..."}] or ["..."]
    Returns list[str] filenames.
    """
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, dict):
            fn = item.get("filename", "")
        else:
            fn = item
        if isinstance(fn, str) and fn.strip():
            out.append(fn.strip())
    return out


def _base_no_ext(path: str) -> str:
    p = path.replace("\\", "/")
    name = p.split("/")[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name


def _test_base_candidates(test_filename: str) -> Set[str]:
    """
    Produce candidate source base-names from a test file base-name using the same
    conventions as TestAnalyser.is_test_file(): prefixes/suffixes + 'IT'. :contentReference[oaicite:2]{index=2}
    """
    base = _base_no_ext(test_filename)
    lower = base.lower()

    candidates: Set[str] = set()

    # Prefixes: test_, tests_
    for prefix in ("test_", "tests_"):
        if lower.startswith(prefix):
            candidates.add(lower[len(prefix):])
            break

    # Suffixes: test, tests, _test, _tests, spec, _spec
    suffixes = ("_test", "_tests", "test", "tests", "_spec", "spec")
    for suf in suffixes:
        if lower.endswith(suf):
            candidates.add(lower[: -len(suf)])
            break

    # Case-sensitive Integration Test pattern: endswith 'IT'
    # If you have FooIT -> Foo
    if base.endswith("IT") and len(base) > 2:
        candidates.add(base[:-2].lower())

    # Fallback: if it contains 'test' somewhere, try stripping it (common in some repos)
    if "test" in lower:
        candidates.add(lower.replace("test", "").strip("_"))

    # Clean empties
    candidates = {c for c in candidates if c}
    return candidates


def _is_related(test_file: str, candidate_file: str) -> bool:
    """
    Related if candidate base-name equals any derived candidate from the test file name.
    Example: TestFoo -> foo, foo_test -> foo, FooIT -> foo, FooSpec -> foo.
    """
    cand_base = _base_no_ext(candidate_file).lower()
    test_candidates = _test_base_candidates(test_file)
    return cand_base in test_candidates


def _counts_related(doc: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
    """
    Returns:
      test_n_raw, source_n_raw, tested_n_raw,
      source_n_related, tested_n_related
    """
    tc = doc.get("test_coverage") or {}

    test_files = _filename_list(tc.get("test_files")) or _filename_list(doc.get("test_files"))
    source_files = _filename_list(tc.get("source_files")) or _filename_list(doc.get("source_files"))
    tested_files = _filename_list(tc.get("tested_files")) or _filename_list(doc.get("tested_files"))

    test_n_raw = len(test_files)
    source_n_raw = len(source_files)
    tested_n_raw = len(tested_files)

    # Related source files: those that match at least one test file by naming
    related_sources: Set[str] = set()
    for sf in source_files:
        for tf in test_files:
            if _is_related(tf, sf):
                related_sources.add(sf)
                break

    # Related tested files: those that match at least one test file by naming
    related_tested: Set[str] = set()
    for tdf in tested_files:
        for tf in test_files:
            if _is_related(tf, tdf):
                related_tested.add(tdf)
                break

    return test_n_raw, source_n_raw, tested_n_raw, len(related_sources), len(related_tested)


def classify(
    test_n: int,
    source_related_n: int,
    tested_related_n: int,
    source_raw_n: int,
    tested_raw_n: int,
) -> str:
    # True if (test == tested_related AND test != 0) OR (test > 0 AND source_related == 0)
    if ((test_n == tested_related_n and test_n != 0) or (test_n > 0 and source_related_n == 0)):
        return "True"

    # Semi if test > 0 but test < tested_related
    if test_n > 0 and test_n < tested_related_n:
        return "Semi"

    # False if test == 0 and (source_raw > 0 or tested_raw > 0)
    if test_n == 0 and (source_raw_n > 0 or tested_raw_n > 0):
        return "False"

    return "False"


def compute_pct(test_n: int, tested_related_n: int) -> Optional[float]:
    # Percentage based on RELATED tested files (since you now require relatedness)
    if tested_related_n <= 0:
        return None
    return (test_n / tested_related_n) * 100.0


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

    ops: List[UpdateOne] = []
    processed = 0
    modified_total = 0

    try:
        for doc in cursor:
            processed += 1

            test_n, source_raw, tested_raw, source_related, tested_related = _counts_related(doc)

            tdd_same_val = classify(
                test_n=test_n,
                source_related_n=source_related,
                tested_related_n=tested_related,
                source_raw_n=source_raw,
                tested_raw_n=tested_raw,
            )
            tdd_pct_val = compute_pct(test_n, tested_related)

            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {FIELD_NAME: tdd_same_val, PCT_FIELD: tdd_pct_val}},
                )
            )

            if len(ops) >= batch_size:
                res = col.bulk_write(ops, ordered=False)
                modified_total += res.modified_count
                print(
                    f"Processed: {processed}, Batch modified: {res.modified_count}, "
                    f"Total modified: {modified_total}"
                )
                ops = []

        if ops:
            res = col.bulk_write(ops, ordered=False)
            modified_total += res.modified_count
            print(
                f"Processed: {processed}, Batch modified: {res.modified_count}, "
                f"Total modified: {modified_total}"
            )

        print(f"[DONE] Processed: {processed}, Total modified: {modified_total}")

    except PyMongoError as e:
        print(f"[ERROR] Mongo operation failed: {e}")
        raise


if __name__ == "__main__":
    main(batch_size=10000)
