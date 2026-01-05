import pytest
from unittest.mock import MagicMock, patch, PropertyMock, ANY
from datetime import datetime, timedelta
import config

# Modules to test
from repo_miner import Repo_miner
from worker import mine_repo, clean_url
from partitioner import prepare_job

# --- Fixtures ---

@pytest.fixture
def mock_db():
    with patch('repo_miner.get_java_projects_to_mine') as mock_java, \
         patch('repo_miner.get_python_projects_to_mine') as mock_python, \
         patch('repo_miner.get_cpp_projects_to_mine') as mock_cpp, \
         patch('repo_miner.get_completed_project_names') as mock_completed_names, \
         patch('repo_miner.mark_project_as_completed') as mock_mark_completed, \
         patch('miners.commit_processor.get_existing_commit_hashes') as mock_hashes, \
         patch('miners.commit_processor.save_commit_batch') as mock_save, \
         patch('repo_miner.ensure_indexes') as mock_indexes:
        
        mock_java.return_value = []
        mock_python.return_value = []
        mock_cpp.return_value = []
        mock_completed_names.return_value = set()
        mock_hashes.return_value = set() 
        
        yield {
            'java': mock_java, 'python': mock_python, 'cpp': mock_cpp,
            'completed_names': mock_completed_names, 'mark_completed': mock_mark_completed,
            'save': mock_save
        }

@pytest.fixture
def mock_pydriller():
    with patch('worker.Repository') as mock_repo:
        yield mock_repo

@pytest.fixture
def mock_file_analyser():
    with patch('miners.file_analyser.FileAnalyser') as mock_fa:
        mock_fa.get_extensions_for_language.return_value = {'.java'}
        yield mock_fa

@pytest.fixture
def mock_executor():
    with patch('repo_miner.ProcessPoolExecutor') as mock_pool:
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
    mock_commit.hash, mock_commit.insertions = "hash123", 10
    mock_commit.modified_files = []
    
    mock_pydriller.return_value.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    # Input now includes DEPTH (0)
    args = ("test", "url", datetime(2023,1,1), datetime(2024,1,1), "Java", 0, stop_event)
    result = mine_repo(args)

    # FIX: Guard assertion to satisfy Pylance
    assert result is not None 
    assert result[1] == 1  # 1 new commit
    assert result[3] is None # No error

def test_mine_repo_skips_existing_commits(mock_db, mock_pydriller, mock_file_analyser):
    """Test that commits already in DB are skipped."""
    mock_db['hashes'].return_value = {"hash123"}
    
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.modified_files = [] 
    
    mock_pydriller.return_value.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", None, None, "Java", 0, stop_event)
    result = mine_repo(args)
    
    # FIX: Guard assertion
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
    
    # FIX: Guard assertion
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
    jobs = prepare_job(project)
    
    assert len(jobs) == 1
    # Check tuple: (name, url, start, end, lang, DEPTH)
    assert jobs[0] == ('J', 'http://u', None, None, 'Java', 0)

@patch('scheduler.requests.get')
def test_scheduler_prepare_job_cpp_api_success(mock_get):
    """Test C++ splitting with successful GitHub API date fetch."""
    project = {'name': 'C', 'repo_url': 'https://github.com/o/r', 'language': 'C++'}
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"created_at": "2022-01-01T00:00:00Z"}
    mock_get.return_value = mock_response
    
    with patch('scheduler.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1)
        mock_datetime.strptime = datetime.strptime 
        
        jobs = prepare_job(project)

    assert len(jobs) >= 2 
    assert jobs[0][4] == 'C++'
    assert jobs[0][5] == 0 # Initial depth must be 0
    assert jobs[0][2] == datetime(2022, 1, 1)

# --- 3. Orchestrator Logic Tests (Split & Retry) ---

def test_run_logic_splits_on_timeout(mock_db, mock_executor):
    """
    CRITICAL TEST: Verifies that after 2 timeouts, the miner splits the job
    and increments the depth.
    """
    job_initial = ('repo1', 'url', datetime(2020,1,1), datetime(2021,1,1), 'C++', 0)
    
    f_initial = MagicMock()
    f_retry1 = MagicMock()
    f_split_subtask = MagicMock()

    f_initial.result.return_value = ('repo1', 0, 0, "TIMED OUT")
    f_retry1.result.return_value  = ('repo1', 0, 0, "TIMED OUT") 
    f_split_subtask.result.return_value = ('repo1', 5, 0, None)

    mock_executor.submit.side_effect = [
        f_initial,       # 1. Initial submission
        f_retry1,        # 2. First retry submission
        *[f_split_subtask] * 12 # 3. Split submissions
    ]
    
    def side_effect_wait(futures, return_when):
        f = list(futures)[0]
        return {f}, set()

    with patch('repo_miner.wait', side_effect=side_effect_wait), \
         patch('repo_miner.prepare_job', return_value=[job_initial]), \
         patch('repo_miner.ThreadPoolExecutor'): 
        
        miner = Repo_miner()
        miner.run()

        # Check Depth increment on split
        args_split = mock_executor.submit.call_args_list[2][0]
        assert args_split[5] == 1 

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

    with patch('repo_miner.wait', side_effect=side_effect_wait), \
         patch('repo_miner.prepare_job', return_value=[job_max_depth]), \
         patch('repo_miner.ThreadPoolExecutor'):
        
        miner = Repo_miner()
        miner.run()
        
        for call in mock_executor.submit.call_args_list:
            args = call[0]
            depth_arg = args[5]
            assert depth_arg == 3 # Should never increment to 4