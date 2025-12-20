import sys
import types
import importlib
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def enrich_module():
    """
    Import enrich_commits with a mocked config module so tests do not require real env/config.
    Mirrors the mocking approach used in your miner tests.
    """
    # Provide a fake `config` module so `from config import MONGO_URI` works.
    config_mod = types.ModuleType("config")
    config_mod.MONGO_URI = "mongodb://fake-uri-for-tests"
    sys.modules["config"] = config_mod

    import enrich_commits
    importlib.reload(enrich_commits)
    return enrich_commits


def test_is_test_path(enrich_module):
    assert enrich_module.is_test_path("src/test/java/org/apache/Foo.java") is True
    assert enrich_module.is_test_path("FooTest.java") is True
    assert enrich_module.is_test_path("FooTests.java") is True
    assert enrich_module.is_test_path("FooIT.java") is True

    assert enrich_module.is_test_path("src/main/java/org/apache/Foo.java") is False
    assert enrich_module.is_test_path("README.md") is False
    assert enrich_module.is_test_path("") is False
    assert enrich_module.is_test_path(None) is False


def test_extract_paths_prefers_filename(enrich_module):
    # Matches how repo_miner stores modified_files items: { "filename": ..., ... }.
    modified_files = [
        {"filename": "src/test/java/org/apache/FooTest.java", "complexity": 5, "changed_methods": []},
        {"filename": "src/main/java/org/apache/Foo.java", "complexity": 7, "changed_methods": ["m1"]},
    ]
    paths = enrich_module.extract_paths(modified_files)
    assert paths == [
        "src/test/java/org/apache/FooTest.java",
        "src/main/java/org/apache/Foo.java",
    ]


def test_main_enriches_and_bulk_writes(enrich_module):
    """
    End-to-end (mocked) test of main():
    - reads commits via find()
    - classifies commit_kind correctly
    - writes UpdateOne ops via bulk_write()
    """
    # Fake docs representing the four buckets
    docs = [
        {"_id": 1, "modified_files": [{"filename": "src/test/java/AwesomeTest.java"}]},  # TEST_ONLY
        {"_id": 2, "modified_files": [{"filename": "src/main/java/Awesome.java"}]},      # PROD_ONLY
        {"_id": 3, "modified_files": [{"filename": "src/test/java/A.java"}, {"filename": "src/main/java/A.java"}]},  # MIXED
        {"_id": 4, "modified_files": []},  # NO_CODE
    ]

    commits_col = MagicMock()
    commits_col.find.return_value = docs

    # MongoClient()[DB_NAME][COMMIT_COLLECTION] chaining
    db_mock = MagicMock()
    db_mock.__getitem__.return_value = commits_col  # db[COMMIT_COLLECTION] -> commits_col

    client_mock = MagicMock()
    client_mock.__getitem__.return_value = db_mock  # client[DB_NAME] -> db_mock

    # Capture UpdateOne calls in an inspectable form
    class FakeUpdateOne:
        def __init__(self, flt, upd):
            self.filter = flt
            self.update = upd

    with patch.object(enrich_module, "MongoClient", return_value=client_mock), \
         patch.object(enrich_module, "UpdateOne", FakeUpdateOne):

        enrich_module.main()

    # Verify query shape (only unenriched docs, project only needs modified_files)
    commits_col.find.assert_called_once()
    find_args, find_kwargs = commits_col.find.call_args
    assert find_args[0] == {"tdd_enriched": {"$ne": True}}
    assert find_args[1] == {"modified_files": 1}

    # Verify bulk_write was called and ops have expected classifications
    assert commits_col.bulk_write.called, "Expected bulk_write to be called at least once"
    ops_passed = commits_col.bulk_write.call_args[0][0]
    assert len(ops_passed) == 4

    # Inspect the $set payloads (using FakeUpdateOne)
    payloads = [op.update["$set"] for op in ops_passed]

    assert payloads[0]["commit_kind"] == "TEST_ONLY"
    assert payloads[1]["commit_kind"] == "PROD_ONLY"
    assert payloads[2]["commit_kind"] == "MIXED"
    assert payloads[3]["commit_kind"] == "NO_CODE"

    for p in payloads:
        assert p["tdd_enriched"] is True
        assert "has_test_changes" in p
        assert "has_prod_changes" in p
        assert "test_files_touched" in p
        assert "prod_files_touched" in p
