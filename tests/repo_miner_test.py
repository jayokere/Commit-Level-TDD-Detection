import pytest
from unittest.mock import MagicMock, patch, PropertyMock, ANY
from datetime import datetime
from repo_miner import Repo_miner

# --- Fixtures to mock external dependencies ---

@pytest.fixture
def mock_db():
    """Mocks the database functions to prevent real DB connections."""
    with patch('repo_miner.get_java_projects_to_mine') as mock_java, \
         patch('repo_miner.get_python_projects_to_mine') as mock_python, \
         patch('repo_miner.get_cpp_projects_to_mine') as mock_cpp, \
         patch('repo_miner.get_completed_project_names') as mock_completed_names, \
         patch('repo_miner.mark_project_as_completed') as mock_mark_completed, \
         patch('miners.commit_processor.get_existing_commit_hashes') as mock_hashes, \
         patch('miners.commit_processor.save_commit_batch') as mock_save, \
         patch('repo_miner.ensure_indexes') as mock_indexes:
        
        # Setup sample return values
        mock_java.return_value = [{'name': 'java-repo', 'url': 'http://github.com/test/java', 'language': 'Java'}]
        mock_python.return_value = [{'name': 'py-repo', 'url': 'http://github.com/test/py', 'language': 'Python'}]
        mock_cpp.return_value = [{'name': 'cpp-repo', 'url': 'http://github.com/test/cpp', 'language': 'C++'}]
        mock_completed_names.return_value = set()
        mock_hashes.return_value = set() 
        
        yield {
            'java': mock_java,
            'python': mock_python,
            'cpp': mock_cpp,
            'completed_names': mock_completed_names,
            'mark_completed': mock_mark_completed,
            'hashes': mock_hashes,
            'save': mock_save
        }

@pytest.fixture
def mock_pydriller():
    """Mocks the Repository class to prevent actual git cloning."""
    with patch('repo_miner.Repository') as mock_repo:
        yield mock_repo

@pytest.fixture
def mock_file_analyser():
    """
    Mocks the FileAnalyser. 
    CRITICAL FIX: We patch 'repo_miner.FileAnalyser' because it is imported 
    into the repo_miner namespace. Patching the source definition wouldn't 
    affect the already imported class.
    """
    with patch('repo_miner.FileAnalyser') as mock_fa:
        mock_fa.get_extensions_for_language.return_value = {'.java'}
        yield mock_fa

@pytest.fixture
def mock_executor():
    """Mocks the ProcessPoolExecutor to prevent spawning real processes."""
    with patch('repo_miner.ProcessPoolExecutor') as mock_pool:
        executor_instance = MagicMock()
        mock_pool.return_value.__enter__.return_value = executor_instance
        yield executor_instance

# --- Unit Tests ---

def test_clean_url_valid():
    assert Repo_miner.clean_url("https://github.com/user/repo") == "https://github.com/user/repo"

def test_clean_url_correction():
    malformed = "https://github.com:user/repo"
    expected = "https://github.com/user/repo"
    assert Repo_miner.clean_url(malformed) == expected

def test_clean_url_none():
    assert Repo_miner.clean_url(None) is None

def test_miner_initialisation_sampling(mock_db):
    """Test that the miner samples 60 projects from each language."""
    # Setup enough items to sample from
    mock_db['java'].return_value = [{'name': f'p{i}', 'url': 'u', 'language': 'Java'} for i in range(100)]
    mock_db['python'].return_value = [{'name': f'p{i}', 'url': 'u', 'language': 'Python'} for i in range(100)]
    mock_db['cpp'].return_value = [{'name': f'p{i}', 'url': 'u', 'language': 'C++'} for i in range(100)]
    
    with patch('random.sample', side_effect=lambda pop, k: pop[:k]) as mock_sample:
        miner = Repo_miner()
        assert mock_sample.call_count == 3
        mock_sample.assert_any_call(ANY, 60)
        assert len(miner.projects) == 180

# --- Integration / Logic Tests (Mocked) ---

def test_mine_repo_success(mock_db, mock_pydriller, mock_file_analyser):
    """Test the core mining worker logic returns success."""
    # 1. Setup Mock Commit and File
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.committer_date = datetime(2023, 1, 1)
    mock_commit.insertions = 10
    mock_commit.deletions = 5
    
    mock_file = MagicMock()
    mock_file.filename = "Main.java"
    mock_file.changed_methods = []
    type(mock_file).complexity = PropertyMock(return_value=10)
    mock_commit.modified_files = [mock_file]
    
    # 2. Configure Pydriller
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.return_value = [mock_commit]

    # 3. Define Arguments
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2024, 1, 1)
    language = "Java"
    
    args = ("test-project", "http://github.com/test", start_date, end_date, language, stop_event)
    
    # 4. Run the worker
    result = Repo_miner.mine_repo(args)

    # 5. Assertions
    assert result is not None
    project_name, new, existing, error = result
    
    assert project_name == "test-project"
    assert new == 1
    assert error is None
    
    mock_pydriller.assert_called_with(
        "http://github.com/test",
        since=start_date,
        to=end_date,
        only_modifications_with_file_types=ANY
    )
    
    # This should now pass because we patched 'repo_miner.FileAnalyser'
    mock_file_analyser.get_extensions_for_language.assert_called_with("Java")
    mock_db['save'].assert_called()

def test_mine_repo_skips_existing_commits(mock_db, mock_pydriller, mock_file_analyser):
    """Test that commits already in DB are skipped."""
    mock_db['hashes'].return_value = {"hash123"}
    
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.modified_files = [] 
    
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", None, None, "Java", stop_event)
    result = Repo_miner.mine_repo(args)
    
    assert result is not None
    assert result[1] == 0 
    mock_db['save'].assert_not_called()

def test_mine_repo_handles_error(mock_db, mock_pydriller):
    """Test that exceptions are caught and returned safely."""
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.side_effect = Exception("Git Error")
    
    stop_event = MagicMock()
    # FIX: Explicitly set return value to False so the miner doesn't quit early
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", None, None, "Java", stop_event)
    result = Repo_miner.mine_repo(args)
    
    # Now result will be the tuple (name, 0, 0, error) instead of None
    assert result is not None
    assert result[3] == "Git Error"

def test_run_logic_completes_project(mock_db, mock_executor):
    """
    Test that the run method correctly tracks shards and marks the project 
    as complete when all shards finish.
    """
    # --- PHASE 2 FUTURES (Mining) ---
    f1 = MagicMock()
    f1.result.return_value = ('java-repo', 10, 0, None)
    
    f2 = MagicMock()
    f2.result.return_value = ('cpp-repo', 5, 0, None)
    
    f3 = MagicMock()
    f3.result.return_value = ('cpp-repo', 5, 0, None)
    
    # --- PHASE 1 FUTURES (Preparation) ---
    # These must be Mocks that have a .result() method returning the list of jobs
    p1_f1 = MagicMock()
    p1_f1.result.return_value = [('java-repo', 'url', None, None, 'Java')]
    
    p1_f2 = MagicMock()
    p1_f2.result.return_value = [
         ('cpp-repo', 'url', datetime(2023,1,1), datetime(2024,1,1), 'C++'),
         ('cpp-repo', 'url', datetime(2024,1,1), datetime(2025,1,1), 'C++')
    ]

    # Patch internals
    with patch('random.sample', side_effect=lambda pop, k: pop[:k]), \
         patch('repo_miner.as_completed') as mock_as_completed, \
         patch('repo_miner.Repo_miner._prepare_job'):
         
        # Mock ThreadPoolExecutor (Phase 1)
        with patch('repo_miner.ThreadPoolExecutor') as mock_thread_pool:
            mock_thread_pool.return_value.__enter__.return_value = MagicMock()
            
            # Setup Phase 2 (Mining) submit calls
            mock_executor.submit.side_effect = [f1, f2, f3]
            
            # Define as_completed behavior for both phases
            def side_effect_as_completed(futures):
                input_list = list(futures)
                # If checking Phase 2 futures
                if input_list and input_list[0] in [f1, f2, f3]:
                     return [f1, f2, f3]
                
                # Else checking Phase 1 futures -> Return the MOCK futures (p1_f1, p1_f2)
                return [p1_f1, p1_f2]

            mock_as_completed.side_effect = side_effect_as_completed
            
            miner = Repo_miner()
            miner.run()
            
            # ASSERTIONS
            mock_db['mark_completed'].assert_any_call('java-repo')
            mock_db['mark_completed'].assert_any_call('cpp-repo')
            
            assert mock_executor.submit.call_count == 3
            args_used = mock_executor.submit.call_args_list[0][0][1]
            assert len(args_used) == 6 
            assert args_used[4] == 'Java'

def test_stop_signal_check():
    stop_event = MagicMock()
    stop_event.is_set.return_value = True
    args = ("test", "url", None, None, "Java", stop_event)
    result = Repo_miner.mine_repo(args)
    assert result is None