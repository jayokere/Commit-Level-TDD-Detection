import pytest
import sys
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
# 1. Mock Internal Modules
# -------------------------------------------------------------------------
sys.modules["miner_intro"] = MagicMock()
sys.modules["utils"] = MagicMock()

# Mock the new db module
mock_db_module = MagicMock()
sys.modules["db"] = mock_db_module

def mock_measure_time(func):
    return func
sys.modules["utils"].measure_time = mock_measure_time

from sort_projects import sort_projects, RateLimitExceededError

# -------------------------------------------------------------------------
# 2. Test Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def mock_cursor_data():
    """Sample data resembling MongoDB documents"""
    return [
        {"name": "Project A", "urls": ["https://github.com/apache/project-a"]},
        {"name": "Project B", "urls": ["https://github.com/apache/project-b"]},
        {"name": "Project C", "urls": ["https://gitbox.apache.org/repos/asf/project-c.git"]}
    ]

@pytest.fixture
def sorter(mock_cursor_data):
    """
    Initialises the sort_projects class with a mocked MongoDB connection.
    """
    mock_collection = MagicMock()
    mock_db_module.get_collection.return_value = mock_collection
    
    # Mock the initial find() call in __init__
    mock_collection.find.return_value = iter(mock_cursor_data)
    
    sorter_instance = sort_projects()
    # Explicitly attach the mock collection to the instance for assertion checks later
    sorter_instance.collection = mock_collection
    
    return sorter_instance

# -------------------------------------------------------------------------
# 3. Unit Tests
# -------------------------------------------------------------------------

def test_init_loads_db_data_correctly(sorter):
    """Test if data from MongoDB is loaded into memory on init."""
    assert "Project A" in sorter.apache_projects
    assert len(sorter.apache_projects) == 3
    # Verify we queried with projection
    sorter.collection.find.assert_called_with({}, {"name": 1, "urls": 1, "_id": 0})

def test_get_commit_count_non_github(sorter):
    url = "https://gitbox.apache.org/repos/asf/test.git"
    assert sorter.get_commit_count(url) == 0

@patch("requests.Session.get")
def test_get_commit_count_pagination(mock_get, sorter):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Link': '<https://api.github.com/repos/x/y/commits?per_page=1&page=50>; rel="last"'
    }
    mock_get.return_value = mock_response
    
    count = sorter.get_commit_count("https://github.com/apache/test")
    assert count == 50

@patch("requests.Session.get")
def test_rate_limit_exceeded(mock_get, sorter):
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "rate limit exceeded"
    mock_response.headers = {'X-RateLimit-Remaining': '0'}
    mock_get.return_value = mock_response

    with pytest.raises(RateLimitExceededError):
        sorter.get_commit_count("https://github.com/apache/test")

def test_analyze_project_logic(sorter):
    project_name = "Test Project"
    links = ["link1"]
    
    with patch.object(sorter, 'get_commit_count', return_value=10):
        result = sorter._analyze_project((project_name, links))
        
        # FIX: Unpack 4 values: (Name, Links, Count, Errors)
        p_name, _, total, errors = result
        
        assert p_name == "Test Project"
        assert total == 10
        assert len(errors) == 0

# -------------------------------------------------------------------------
# 4. Integration Test (Mocking the ThreadPool & DB Write)
# -------------------------------------------------------------------------

@patch("sort_projects.ThreadPool") 
def test_sort_by_commit_count_db_update(mock_pool_cls, sorter):
    """
    Test the full flow:
    1. Analysis runs via ThreadPool.
    2. DB is updated via bulk_write.
    3. Index is created.
    """
    mock_pool = mock_pool_cls.return_value
    
    # FIX: Fake results must match the tuple size: (Name, Links, Count, Errors)
    fake_results = [
        ("Project A", ["url"], 50, []),
        ("Project B", ["url"], 100, []),
        ("Project C", ["url"], 0, [])
    ]
    mock_pool.imap_unordered.return_value = iter(fake_results)

    # Mock bulk_write result
    mock_write_result = MagicMock()
    mock_write_result.modified_count = 3
    sorter.collection.bulk_write.return_value = mock_write_result

    # Run function
    count = sorter.sort_by_commit_count()

    assert count == 3
    
    # VERIFY DB WRITES
    # 1. bulk_write should be called
    sorter.collection.bulk_write.assert_called_once()
    
    # 2. Check the updates passed to bulk_write
    args, _ = sorter.collection.bulk_write.call_args
    updates = args[0]
    assert len(updates) == 3
    
    # 3. Verify Index Creation
    sorter.collection.create_index.assert_called_with([("commit_count", -1)])

@patch("sort_projects.ThreadPool")
def test_sort_aborts_on_rate_limit(mock_pool_cls, sorter):
    """Test that the DB is NOT updated if RateLimitError occurs."""
    mock_pool = mock_pool_cls.return_value
    mock_pool.imap_unordered.side_effect = RateLimitExceededError("Boom")
    
    result = sorter.sort_by_commit_count()
    
    assert result == 0
    
    # Verify DB was NOT touched
    sorter.collection.bulk_write.assert_not_called()
    sorter.collection.create_index.assert_not_called()