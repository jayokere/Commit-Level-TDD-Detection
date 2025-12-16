import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from repo_miner import Repo_miner, VALID_CODE_EXTENSIONS

# --- Fixtures to mock external dependencies ---

@pytest.fixture
def mock_db():
    """Mocks the database functions to prevent real DB connections."""
    with patch('repo_miner.get_java_projects_to_mine') as mock_java, \
         patch('repo_miner.get_python_projects_to_mine') as mock_python, \
         patch('repo_miner.get_cpp_projects_to_mine') as mock_cpp, \
         patch('repo_miner.get_existing_commit_hashes') as mock_hashes, \
         patch('repo_miner.save_commit_batch') as mock_save:
        
        # Setup sample return values
        mock_java.return_value = [{'name': 'java-repo', 'url': 'http://github.com/test/java'}]
        mock_python.return_value = [{'name': 'py-repo', 'url': 'http://github.com/test/py'}]
        mock_cpp.return_value = [{'name': 'cpp-repo', 'url': 'http://github.com/test/cpp'}]
        mock_hashes.return_value = set() # No existing hashes by default
        
        yield {
            'java': mock_java,
            'hashes': mock_hashes,
            'save': mock_save
        }

@pytest.fixture
def mock_pydriller():
    """Mocks the Repository class to prevent actual git cloning."""
    with patch('repo_miner.Repository') as mock_repo:
        yield mock_repo

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

def test_is_valid_file_source_code():
    """Test that valid source extensions are accepted."""
    mock_file = MagicMock()
    mock_file.filename = "Main.java"
    assert Repo_miner.is_valid_file(mock_file) is True

    mock_file.filename = "script.py"
    assert Repo_miner.is_valid_file(mock_file) is True

def test_is_valid_file_tests():
    """Test that files with 'test' in the name are accepted regardless of extension."""
    mock_file = MagicMock()
    mock_file.filename = "MyTestFile.txt" # Weird extension, but name has 'test'
    assert Repo_miner.is_valid_file(mock_file) is True

def test_is_valid_file_ignored():
    """Test that non-code files are rejected."""
    mock_file = MagicMock()
    mock_file.filename = "readme.md"
    assert Repo_miner.is_valid_file(mock_file) is False

    mock_file.filename = "config.xml"
    assert Repo_miner.is_valid_file(mock_file) is False

def test_is_test_file():
    """Test that test files are correctly identified."""
    assert Repo_miner.is_test_file("shapes_test.py") is True
    assert Repo_miner.is_test_file("TestCalculator.java") is True
    assert Repo_miner.is_test_file("test_utils.py") is True
    assert Repo_miner.is_test_file("shapes.py") is False
    assert Repo_miner.is_test_file("Calculator.java") is False
    assert Repo_miner.is_test_file(None) is False

def test_extract_tested_files_from_methods():
    """Test extraction of tested files based on test method names."""
    # Setup mock files
    mock_files = []
    
    # Test file
    test_file = MagicMock()
    test_file.filename = "shapes_test.py"
    mock_files.append(test_file)
    
    # Source files
    shape_file = MagicMock()
    shape_file.filename = "shapes.py"
    mock_files.append(shape_file)
    
    square_file = MagicMock()
    square_file.filename = "square.py"
    mock_files.append(square_file)
    
    triangle_file = MagicMock()
    triangle_file.filename = "triangle.py"
    mock_files.append(triangle_file)
    
    # Test methods that reference square and triangle
    test_methods = ["test_square_area", "test_triangle_perimeter", "test_shape_color"]
    
    tested_files = Repo_miner.extract_tested_files_from_methods(test_methods, mock_files)
    
    # Should identify square.py, triangle.py, and shapes.py as tested
    assert "square.py" in tested_files
    assert "triangle.py" in tested_files
    assert "shapes.py" in tested_files
    assert "shapes_test.py" not in tested_files  # Test file itself should not be included

def test_analyze_test_coverage():
    """Test the analyze_test_coverage function."""
    # Setup mock files
    mock_files = []
    
    # Test file with test methods
    test_file = MagicMock()
    test_file.filename = "calculator_test.py"
    test_method1 = MagicMock()
    test_method1.name = "test_calculator_add"
    test_method2 = MagicMock()
    test_method2.name = "test_calculator_subtract"
    test_file.changed_methods = [test_method1, test_method2]
    mock_files.append(test_file)
    
    # Source file
    calc_file = MagicMock()
    calc_file.filename = "calculator.py"
    calc_method = MagicMock()
    calc_method.name = "add"
    calc_file.changed_methods = [calc_method]
    mock_files.append(calc_file)
    
    coverage = Repo_miner.analyze_test_coverage(mock_files)
    
    # Verify structure
    assert 'test_files' in coverage
    assert 'source_files' in coverage
    assert 'tested_files' in coverage
    
    # Verify test files identified
    assert len(coverage['test_files']) == 1
    assert coverage['test_files'][0]['filename'] == "calculator_test.py"
    
    # Verify source files identified
    assert len(coverage['source_files']) == 1
    assert coverage['source_files'][0]['filename'] == "calculator.py"
    
    # Verify tested files identified
    assert "calculator.py" in coverage['tested_files']

def test_miner_initialisation_sampling(mock_db):
    """Test that the miner samples 60 projects from each language."""
    # We need enough items to sample from, or random.sample throws an error
    mock_db['java'].return_value = [{'name': f'p{i}', 'url': 'u'} for i in range(100)]
    
    # We patch random.sample to just return the list so we can verify the calls
    with patch('random.sample', side_effect=lambda pop, k: pop[:k]) as mock_sample:
        miner = Repo_miner()
        
        # Should call sample 3 times (Java, Python, C++)
        assert mock_sample.call_count == 3
        # Should verify the sample size is 60
        mock_sample.assert_any_call(mock_db['java'].return_value, 60)

# --- Integration / Logic Tests (Mocked) ---

def test_mine_repo_success(mock_db, mock_pydriller):
    """
    Test the core logic: 
    1. Iterates commits
    2. Extracts DMM and Complexity
    3. Saves data
    """
    # 1. Setup Mock Commit
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    mock_commit.committer_date = "2023-01-01"
    
    # Mock the DMM property on the commit
    type(mock_commit).dmm_unit_size = PropertyMock(return_value=0.5)

    # 2. Setup Mock File
    mock_file = MagicMock()
    mock_file.filename = "Test.java"
    mock_file.complexity = 10
    
    # Mock changed methods
    mock_method = MagicMock()
    mock_method.name = "doSomething"
    mock_file.changed_methods = [mock_method]
    
    mock_commit.modified_files = [mock_file]
    
    # 3. Configure Pydriller to return this commit
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.return_value = [mock_commit]

    # 4. Run the worker function
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", stop_event)
    result = Repo_miner.mine_repo(args)

    # 5. Assertions
    # FIX: Explicitly assert result is not None to satisfy Pylance static analysis
    assert result is not None, "Result should not be None when stop_event is not set"

    project_name, new, existing, error = result
    
    assert project_name == "test-project"
    assert new == 1
    assert error is None
    
    # Check if save was called with correct structure
    mock_db['save'].assert_called()
    saved_data = mock_db['save'].call_args[0][0][0] # First arg, first item in list
    
    assert saved_data['hash'] == "hash123"
    assert saved_data['dmm_unit_size'] == 0.5
    assert saved_data['modified_files'][0]['filename'] == "Test.java"
    assert saved_data['modified_files'][0]['complexity'] == 10
    assert saved_data['modified_files'][0]['changed_methods'] == ["doSomething"]
    
    # Verify test_coverage is included
    assert 'test_coverage' in saved_data
    assert 'test_files' in saved_data['test_coverage']
    assert 'source_files' in saved_data['test_coverage']
    assert 'tested_files' in saved_data['test_coverage']

def test_mine_repo_skips_existing(mock_db, mock_pydriller):
    """Test that commits already in DB are skipped."""
    # Setup DB to say "hash123" already exists
    mock_db['hashes'].return_value = {"hash123"}
    
    mock_commit = MagicMock()
    mock_commit.hash = "hash123"
    
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.return_value = [mock_commit]
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", stop_event)
    result = Repo_miner.mine_repo(args)
    
    # FIX: Explicit assertion for type safety
    assert result is not None

    # Should have 0 new commits
    assert result[1] == 0 
    # save_commit_batch should NOT be called
    mock_db['save'].assert_not_called()

def test_mine_repo_handles_error(mock_db, mock_pydriller):
    """Test that exceptions are caught and returned safely."""
    # Force Pydriller to raise an exception
    # This mimics the behaviour of a network failure
    mock_repo_instance = mock_pydriller.return_value
    mock_repo_instance.traverse_commits.side_effect = Exception("Git Error")
    
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    args = ("test-project", "http://github.com/test", stop_event)
    result = Repo_miner.mine_repo(args)
    
    # FIX: Explicit assertion for type safety
    assert result is not None

    # Check error message is returned
    assert result[3] == "Git Error"