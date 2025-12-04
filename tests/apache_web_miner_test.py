import pytest
import sys
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
# 1. Mock Internal Modules BEFORE Import
# -------------------------------------------------------------------------
sys.modules["miner_intro"] = MagicMock()
sys.modules["utils"] = MagicMock()

# Mock the new db module
mock_db_module = MagicMock()
sys.modules["db"] = mock_db_module

# Mock the measure_time decorator
def mock_measure_time(func):
    return func
sys.modules["utils"].measure_time = mock_measure_time

# -------------------------------------------------------------------------
# 2. Import the Main Script
# -------------------------------------------------------------------------
from apache_web_miner import Apache_web_miner, fetch_project_data

# -------------------------------------------------------------------------
# 3. Test Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def mock_apache_json():
    """Sample JSON structure returned by the Apache API."""
    return {
        "project_1": {
            "name": "Apache Foo",
            "repository": [
                "https://github.com/apache/foo",
                "https://gitbox.apache.org/repos/asf/foo.git"
            ]
        },
        "project_2": {
            "name": "Apache Bar",
            "repository": [
                "https://git-wip-us.apache.org/repos/asf/bar.git"
            ]
        },
        "project_3": {
            "name": "Apache Baz",
            "repository": ["https://svn.apache.org/repos/asf/baz"]
        }
    }

@pytest.fixture
def miner_instance():
    """Returns an instance of Apache_web_miner with a mocked session."""
    instance = Apache_web_miner("http://fake-url.com", num_threads=1)
    instance.session = MagicMock()
    return instance

# -------------------------------------------------------------------------
# 4. Unit Tests: Apache_web_miner Class
# -------------------------------------------------------------------------

def test_fetch_data_success(miner_instance, mock_apache_json):
    """Test successful data retrieval from the API."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_apache_json
    miner_instance.session.get.return_value = mock_response

    miner_instance.fetch_data()

    assert miner_instance.data == mock_apache_json
    miner_instance.session.get.assert_called_once_with("http://fake-url.com")

def test_fetch_data_exception(miner_instance, capsys):
    """Test graceful handling of network errors during fetch."""
    miner_instance.session.get.side_effect = Exception("Network Boom")
    
    miner_instance.fetch_data()
    
    assert miner_instance.data == {}
    captured = capsys.readouterr()
    assert "An error occurred" in captured.out

def test_resolve_redirect_valid(miner_instance):
    """Test resolving a non-GitHub link that redirects to a GitHub link."""
    mock_response = MagicMock()
    mock_response.url = "https://github.com/apache/bar"
    miner_instance.session.head.return_value = mock_response

    result = miner_instance.resolve_redirect("http://redirect.me")
    assert result == "https://github.com/apache/bar"

def test_resolve_redirect_invalid(miner_instance):
    """Test resolving a link that does NOT redirect to GitHub."""
    mock_response = MagicMock()
    mock_response.url = "https://bitbucket.org/apache/bar"
    miner_instance.session.head.return_value = mock_response

    result = miner_instance.resolve_redirect("http://redirect.me")
    assert result is None

def test_resolve_redirect_bad_input(miner_instance):
    assert miner_instance.resolve_redirect(None) is None
    assert miner_instance.resolve_redirect(123) is None

# -------------------------------------------------------------------------
# 5. Integration Logic: get_github_links
# -------------------------------------------------------------------------

@patch("apache_web_miner.ThreadPool")
def test_get_github_links_logic(mock_pool_cls, miner_instance, mock_apache_json):
    miner_instance.data = mock_apache_json
    
    mock_pool = mock_pool_cls.return_value
    mock_pool.__enter__.return_value = mock_pool
    mock_pool.__exit__.return_value = None

    fake_thread_results = [
        ("https://gitbox.apache.org/repos/asf/foo.git", None),
        ("https://git-wip-us.apache.org/repos/asf/bar.git", "https://github.com/apache/bar"),
        ("https://svn.apache.org/repos/asf/baz", None)
    ]
    mock_pool.imap_unordered.return_value = iter(fake_thread_results)

    result_dict = miner_instance.get_github_links()

    assert "https://github.com/apache/foo" in result_dict["Apache Foo"]
    assert "https://github.com/apache/bar" in result_dict["Apache Bar"]
    assert "Apache Baz" not in result_dict

# -------------------------------------------------------------------------
# 6. Tests for fetch_project_data (Database Interactions)
# -------------------------------------------------------------------------

def test_fetch_project_data_db_has_data():
    """
    If the database is populated, it should return data from DB
    and NOT trigger the miner.
    """
    # Setup mock collection
    mock_collection = MagicMock()
    mock_db_module.get_collection.return_value = mock_collection
    
    # 1. Simulate DB has documents
    mock_collection.count_documents.return_value = 10 
    
    # 2. Simulate cursor return
    fake_doc = {"name": "Project X", "urls": ["http://github.com/x"]}
    mock_collection.find.return_value = iter([fake_doc])

    with patch("apache_web_miner.Apache_web_miner") as MockMiner:
        result = fetch_project_data()
        
        # Verify it parsed the DB doc correctly
        assert result["Project X"] == ["http://github.com/x"]
        
        # Verify Miner was NOT called
        MockMiner.assert_not_called()
        
        # Verify we queried the DB
        mock_collection.count_documents.assert_called_once()

def test_fetch_project_data_db_empty():
    """
    If DB is empty, it should:
    1. Initialize Miner
    2. Mine Data
    3. Insert data into DB
    """
    mock_collection = MagicMock()
    mock_db_module.get_collection.return_value = mock_collection
    
    # 1. Simulate empty DB
    mock_collection.count_documents.return_value = 0
    
    # 2. Mock return data from miner
    fake_mined_data = {"Mined Project": ["https://github.com/mined"]}

    with patch("apache_web_miner.Apache_web_miner") as MockMinerCls:
        mock_instance = MockMinerCls.return_value
        mock_instance.get_github_links.return_value = fake_mined_data
        
        result = fetch_project_data()

        assert result == fake_mined_data
        
        # Verify insertion called
        mock_collection.insert_many.assert_called_once()
        
        # Check arguments passed to insert_many
        args, _ = mock_collection.insert_many.call_args
        inserted_docs = args[0]
        assert inserted_docs[0]["name"] == "Mined Project"
        assert inserted_docs[0]["urls"] == ["https://github.com/mined"]