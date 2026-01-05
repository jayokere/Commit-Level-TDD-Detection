import pytest
from unittest.mock import MagicMock, patch, PropertyMock, ANY
from datetime import datetime
from utilities import config

# Imports
from mining.repo_miner import Repo_miner
from mining.worker import mine_repo, clean_url
from mining import partitioner # Import module explicitly for patch.object

# --- Fixtures ---

@pytest.fixture
def mock_db():
    """Mocks the database functions to prevent real DB connections."""
    with patch('mining.repo_miner.get_java_projects_to_mine') as mock_java, \
         patch('mining.repo_miner.get_python_projects_to_mine') as mock_python, \
         patch('mining.repo_miner.get_cpp_projects_to_mine') as mock_cpp, \
         patch('mining.repo_miner.get_completed_project_names') as mock_completed_names, \
         patch('mining.repo_miner.mark_project_as_completed') as mock_mark_completed, \
         patch('mining.components.commit_processor.get_existing_commit_hashes') as mock_hashes, \
         patch('mining.components.commit_processor.save_commit_batch') as mock_save, \
         patch('mining.repo_miner.ensure_indexes') as mock_indexes:
        
        mock_java.return_value = []
        mock_python.return_value = []
        mock_cpp.return_value = []
        mock_completed_names.return_value = set()
        mock_hashes.return_value = set() 
        
        yield {
            'java': mock_java, 'python': mock_python, 'cpp': mock_cpp,
            'completed_names': mock_completed_names, 'mark_completed': mock_mark_completed,
            'hashes': mock_hashes, # FIX: Added missing key here
            'save': mock_save
        }

@pytest.fixture
def mock_pydriller():
    with patch('mining.worker.Repository') as mock_repo:
        yield mock_repo

@pytest.fixture
def mock_file_analyser():
    with patch('mining.components.file_analyser.FileAnalyser') as mock_fa:
        mock_fa.get_extensions_for_language.return_value = {'.java'}
        yield mock_fa

@pytest.fixture
def mock_executor():
    with patch('mining.repo_miner.ProcessPoolExecutor') as mock_pool:
        executor_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = executor_instance
        yield executor_instance

# --- 1. Worker & Utility Tests ---

def test_clean_url_valid():
    assert clean_url("https://github.com/user/repo") == "https://github.com/user/repo"

def test_clean_url_correction():
    assert clean_url("https://github.com:user/repo") == "https://github.com/user/repo"

def test_mine_repo_success(mock_db, mock_pydriller, mock_file_analyser):
    """Test standard worker success path."""
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.insertions = 10
    mock_commit.deletions = 5
    # FIX: Add a modified file so CommitProcessor doesn't skip it
    mock_file = MagicMock()
    mock_file.filename = "A.java"
    mock_commit.modified_files = [mock_file]
    
    mock_pydriller.return_value.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    # Input now includes DEPTH (0)
    args = ("test", "url", datetime(2023,1,1), datetime(2024,1,1), "Java", 0, stop_event)
    result = mine_repo(args)

    assert result is not None
    assert result[1] == 1  # 1 new commit
    assert result[3] is None # No error

def test_mine_repo_skips_existing_commits(mock_db, mock_pydriller, mock_file_analyser):
    """Test that commits already in DB are skipped."""
    mock_db['hashes'].return_value = {"hash123"}
    
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.modified_files = [MagicMock(filename="A.java")]
    
    mock_pydriller.return_value.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", None, None, "Java", 0, stop_event)
    result = mine_repo(args)
    
    assert result is not None
    assert result[1] == 0 
    mock_db['save'].assert_not_called()

def test_mine_repo_handles_error(mock_db, mock_pydriller):
    """Test that exceptions are caught and returned safely."""
    mock_pydriller.return_value.traverse_commits.side_effect = Exception("Git Error")
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", None, None, "Java", 0, stop_event)
    result = mine_repo(args)
    
    assert result is not None
    assert result[3] == "Git Error"

def test_stop_signal_check():
    """Test that the worker returns None immediately if stop_event is set."""
    stop_event = MagicMock()
    stop_event.is_set.return_value = True
    args = ("test", "url", None, None, "Java", 0, stop_event)
    result = mine_repo(args)
    assert result is None

# --- 2. Scheduler Logic Tests ---

def test_scheduler_prepare_job_java():
    """Test simple Java job creation (no date splitting, depth=0)."""
    project = {'name': 'J', 'repo_url': 'http://u', 'language': 'Java'}
    jobs = partitioner.prepare_job(project)
    
    assert len(jobs) == 1
    assert jobs[0] == ('J', 'http://u', None, None, 'Java', 0)

def test_scheduler_prepare_job_cpp_api_success():
    """Test C++ splitting with successful GitHub API date fetch."""
    project = {'name': 'C', 'repo_url': 'https://github.com/o/r', 'language': 'C++'}
    
    # FIX: Use patch.object to avoid ModuleNotFoundError on import resolution
    with patch.object(partitioner.requests, 'get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"created_at": "2020-01-01T00:00:00Z"}
        mock_get.return_value = mock_response
        
        # We rely on the real datetime.now(). Since created_at is 2020, 
        # and now is > 2020, it should generate multiple yearly shards.
        jobs = partitioner.prepare_job(project)

        assert len(jobs) > 1 
        assert jobs[0][4] == 'C++'
        assert jobs[0][5] == 0 # Initial depth must be 0
        assert jobs[0][2] == datetime(2020, 1, 1)

# --- 3. Orchestrator Logic Tests (Split & Retry) ---

# Inside repo_miner_test.py

def test_run_logic_splits_on_timeout(mock_db, mock_executor):
    """
    CRITICAL TEST: Verifies that after 2 timeouts, the miner splits the job
    and increments the depth.
    """
    # 1. SETUP: Ensure we have at least one project
    mock_db['cpp'].return_value = [{'name': 'repo1', 'url': 'url', 'language': 'C++'}]
    
    job_initial = ('repo1', 'url', datetime(2020,1,1), datetime(2021,1,1), 'C++', 0)
    
    # 2. SETUP: Mock Execution Results
    f_initial = MagicMock()
    f_retry1 = MagicMock()
    f_split_subtask = MagicMock()

    f_initial.result.return_value = ('repo1', 0, 0, "TIMED OUT")
    f_retry1.result.return_value  = ('repo1', 0, 0, "TIMED OUT") 
    f_split_subtask.result.return_value = ('repo1', 5, 0, None)

    # Sequence: 1. Initial (fail) -> 2. Retry (fail) -> 3...Split (success)
    # We need enough side effects for: Initial + Retry + All Sub Shards
    mock_executor.submit.side_effect = [f_initial, f_retry1] + [f_split_subtask] * config.SUB_SHARDS
    
    def side_effect_wait(futures, return_when):
        f = list(futures)[0]
        return {f}, set()

    with patch('mining.repo_miner.wait', side_effect=side_effect_wait), \
         patch('mining.repo_miner.as_completed') as mock_as_completed, \
         patch('mining.repo_miner.prepare_job', return_value=[job_initial]), \
         patch('mining.repo_miner.ThreadPoolExecutor') as mock_thread_pool:
         
        # Mock Phase 1
        mock_prep_future = MagicMock()
        mock_prep_future.result.return_value = [job_initial]
        mock_thread_pool.return_value.__enter__.return_value.submit.return_value = mock_prep_future
        mock_as_completed.return_value = iter([mock_prep_future])
        
        miner = Repo_miner()
        miner.run()

        # 4. ASSERTIONS
        # FIX: Use config.SUB_SHARDS instead of hardcoded 12/14
        expected_calls = 2 + config.SUB_SHARDS
        assert mock_executor.submit.call_count == expected_calls
        
        # Check Depth increment on split (The 3rd call is the first split shard)
        args_split = mock_executor.submit.call_args_list[2][0]
        
        # Access the Worker Argument Tuple (index 1), then Depth (index 5)
        worker_args = args_split[1]
        assert worker_args[5] == 1

def test_run_logic_stops_splitting_at_max_depth(mock_db, mock_executor):
    """
    Verifies that if depth is already MAX (3), it does NOT split.
    """
    job_max_depth = ('repo1', 'url', datetime(2020,1,1), datetime(2021,1,1), 'C++', 3)
    
    f_timeout = MagicMock()
    f_timeout.result.return_value = ('repo1', 0, 0, "TIMED OUT")
    mock_executor.submit.return_value = f_timeout
    
    def side_effect_wait(futures, return_when):
        f = list(futures)[0]
        return {f}, set()

    with patch('mining.repo_miner.wait', side_effect=side_effect_wait), \
         patch('mining.repo_miner.prepare_job', return_value=[job_max_depth]), \
         patch('mining.repo_miner.ThreadPoolExecutor'):
        
        miner = Repo_miner()
        miner.run()
        
        # Verify no job was ever submitted with depth 4
        for call in mock_executor.submit.call_args_list:
            args = call[0]
            # args is (function, (arg_tuple))
            # FIX: Unpack the tuple argument (index 1) BEFORE accessing depth
            worker_args = args[1]
            depth_arg = worker_args[5]
            assert depth_arg == 3