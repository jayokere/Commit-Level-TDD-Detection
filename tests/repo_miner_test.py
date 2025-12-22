import pytest
from unittest.mock import MagicMock, patch, PropertyMock, ANY
from datetime import datetime
from repo_miner import Repo_miner
from miners.test_analyser import TestAnalyser

# --- Fixtures to mock external dependencies ---

@pytest.fixture
def mock_db():
    """Mocks the database functions to prevent real DB connections."""
    with patch('repo_miner.get_java_projects_to_mine') as mock_java, \
         patch('repo_miner.get_python_projects_to_mine') as mock_python, \
         patch('repo_miner.get_cpp_projects_to_mine') as mock_cpp, \
         patch('repo_miner.get_all_mined_project_names') as mock_mined_names, \
         patch('miners.commit_processor.get_existing_commit_hashes') as mock_hashes, \
         patch('miners.commit_processor.save_commit_batch') as mock_save, \
         patch('repo_miner.ensure_indexes') as mock_indexes:
        
        # Setup sample return values
        mock_java.return_value = [{'name': 'java-repo', 'url': 'http://github.com/test/java', 'language': 'Java'}]
        mock_python.return_value = [{'name': 'py-repo', 'url': 'http://github.com/test/py', 'language': 'Python'}]
        mock_cpp.return_value = [{'name': 'cpp-repo', 'url': 'http://github.com/test/cpp', 'language': 'C++'}]
        mock_mined_names.return_value = set()
        mock_hashes.return_value = set() # No existing hashes by default
        
        yield {
            'java': mock_java,
            'python': mock_python,
            'cpp': mock_cpp,
            'mined_names': mock_mined_names,
            'hashes': mock_hashes,
            'save': mock_save
        }

@pytest.fixture
def mock_pydriller():
    """Mocks the Repository class to prevent actual git cloning."""
    with patch('repo_miner.Repository') as mock_repo:
        yield mock_repo

@pytest.fixture
def mock_executor():
    """Mocks the ProcessPoolExecutor to prevent spawning real processes."""
    with patch('repo_miner.ProcessPoolExecutor') as mock_pool:
        # Create a mock executor instance
        executor_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = executor_instance
        yield executor_instance

# --- Unit Tests ---

def test_clean_url_valid():
    """Test that URLs are cleaned correctly."""
    assert Repo_miner.clean_url("https://github.com/user/repo") == "https://github.com/user/repo"
    assert Repo_miner.clean_url("https://github.com/user/repo/") == "https://github.com/user/repo"

def test_clean_url_correction():
    """Test that malformed port-style URLs are fixed."""
    malformed = "https://github.com:user/repo"
    expected = "https://github.com/user/repo"
    assert Repo_miner.clean_url(malformed) == expected

def test_clean_url_none():
    """Test that None input returns None."""
    assert Repo_miner.clean_url(None) is None

def test_miner_initialisation_sampling(mock_db):
    """Test that the miner samples 60 projects from each language."""
    # Setup enough items to sample from
    mock_db['java'].return_value = [{'name': f'p{i}', 'url': 'u', 'language': 'Java'} for i in range(100)]
    mock_db['python'].return_value = [{'name': f'p{i}', 'url': 'u', 'language': 'Python'} for i in range(100)]
    mock_db['cpp'].return_value = [{'name': f'p{i}', 'url': 'u', 'language': 'C++'} for i in range(100)]
    
    # Patch random.sample to avoid errors and verify calls
    with patch('random.sample', side_effect=lambda pop, k: pop[:k]) as mock_sample:
        miner = Repo_miner()
        
        # Should call sample 3 times (Java, Python, C++)
        assert mock_sample.call_count == 3
        # Should verify the sample size is 60
        mock_sample.assert_any_call(ANY, 60)
        # Verify projects list is populated
        assert len(miner.projects) == 180

# --- Integration / Logic Tests (Mocked) ---

def test_mine_repo_success(mock_db, mock_pydriller):
    """
    Test the core mining worker logic:
    1. Initialises Repository with correct dates
    2. Processes commits
    3. Returns success status
    """
    # 1. Setup Mock Commit and File
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.committer_date = datetime(2023, 1, 1)
    mock_commit.insertions = 10
    mock_commit.deletions = 5
    
    mock_file = MagicMock()
    mock_file.filename = "Main.java"
    mock_file.changed_methods = []
    # Mock complexity being accessed inside CommitProcessor -> FileAnalyser
    # Since we set complexity=0 in FileAnalyser, we don't strictly need to mock the property on the file
    # but strictly speaking, PyDriller file objects have it.
    type(mock_file).complexity = PropertyMock(return_value=10)
    
    mock_commit.modified_files = [mock_file]
    
    # 2. Configure Pydriller
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.return_value = [mock_commit]

    # 3. Define Arguments (New Signature with Dates)
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2024, 1, 1)
    
    args = ("test-project", "http://github.com/test", start_date, end_date, stop_event)
    
    # 4. Run the worker
    result = Repo_miner.mine_repo(args)

    # 5. Assertions
    assert result is not None
    project_name, new, existing, error = result
    
    assert project_name == "test-project"
    assert new == 1
    assert error is None
    
    # Verify Repository was initialised with DATE SHARDING
    mock_pydriller.assert_called_with(
        "http://github.com/test",
        since=start_date,
        to=end_date,
        only_modifications_with_file_types=ANY
    )
    
    # Verify save was called
    mock_db['save'].assert_called()

def test_mine_repo_skips_existing_commits(mock_db, mock_pydriller):
    """Test that commits already in DB are skipped."""
    mock_db['hashes'].return_value = {"hash123"}
    
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.modified_files = [] 
    
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    # Args with None dates (should also work)
    args = ("test-project", "http://github.com/test", None, None, stop_event)
    result = Repo_miner.mine_repo(args)
    
    assert result is not None
    assert result[1] == 0  # 0 new commits
    mock_db['save'].assert_not_called()

def test_mine_repo_handles_error(mock_db, mock_pydriller):
    """Test that exceptions are caught and returned safely."""
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.side_effect = Exception("Git Error")
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", None, None, stop_event)
    result = Repo_miner.mine_repo(args)
    
    assert result is not None
    assert result[3] == "Git Error"

def test_run_creates_shards_for_cpp(mock_db, mock_executor):
    """
    Test the critical 'Sharding' logic in run().
    """
    # 1. Setup Data
    mock_db['cpp'].return_value = [{'name': 'cpp-repo', 'url': 'u', 'language': 'C++'}]
    mock_db['java'].return_value = [{'name': 'java-repo', 'url': 'u', 'language': 'Java'}]
    mock_db['python'].return_value = [] 

    # 2. Setup the Mock Future
    # This acts as the "result" of a single worker task.
    # We return a tuple of 4 Nones/Zeroes to satisfy the unpacking: p_name, added, existing, error
    mock_future = MagicMock()
    mock_future.result.return_value = ("mock-project", 0, 0, None) 

    # 3. Configure the Executor to return this mock future
    mock_executor.submit.return_value = mock_future

     # 4. Mock first commit from PyDriller
    fake_commit = MagicMock()
    fake_commit.author_date = datetime(2000, 1, 1)

    fake_repo = MagicMock()
    fake_repo.traverse_commits.return_value = [fake_commit]

    # 4. Patch 'as_completed' to immediately yield our mock future
    with patch('random.sample', side_effect=lambda pop, k: pop[:k]), \
         patch('repo_miner.as_completed') as mock_as_completed,\
         patch('repo_miner.Repository', return_value=fake_repo):

        # Make as_completed yield a list containing our mock future
        # (This mimics the executor finishing tasks instantly)
        mock_as_completed.side_effect = lambda futures: futures

        miner = Repo_miner()
        
        # Freezing time logic for assertion
        current_year = datetime.now().year
        first_year = 2000
        expected_shards = (current_year + 1) - first_year
        
        # 5. Run the method
        miner.run()
        
        # 6. Verify Logic
        total_calls = mock_executor.submit.call_count
        assert total_calls == 1 + expected_shards
        
        # Verify Java call (No Dates)
        java_calls = [c for c in mock_executor.submit.call_args_list if c[0][1][0] == 'java-repo']
        assert len(java_calls) == 1
        args_java = java_calls[0][0][1]
        assert args_java[2] is None 
        assert args_java[3] is None 
        
        # Verify C++ calls (With Dates)
        cpp_calls = [c for c in mock_executor.submit.call_args_list if c[0][1][0] == 'cpp-repo']
        assert len(cpp_calls) == expected_shards
        
        args_cpp = cpp_calls[0][0][1]
        assert isinstance(args_cpp[2], datetime)
        assert isinstance(args_cpp[3], datetime)

def test_stop_signal_check(mock_db):
    """Test that mine_repo returns immediately if stop_event is set."""
    stop_event = MagicMock()
    stop_event.is_set.return_value = True
    
    args = ("test", "url", None, None, stop_event)
    result = Repo_miner.mine_repo(args)
    
    assert result is None