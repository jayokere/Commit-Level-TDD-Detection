# Testing Guide for Apache TDD Detector

This guide explains how to run tests and verify the TDD detection implementation.

## Quick Start

### Run All Tests
```bash
# Run all 69 tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=. --cov-report=html
```

### Run Specific Test Modules
```bash
# TDD Detection (Static Analysis)
pytest tests/test_static_analysis.py -v

# Lifecycle Analysis
pytest tests/test_lifecycle_analysis.py -v

# Creation Timing Analysis
pytest tests/test_creation_analysis.py -v

# Mining Tests
pytest tests/repo_miner_test.py -v
pytest tests/apache_miner_test.py -v

# Component Tests
pytest tests/test_file_analyser.py -v
pytest tests/test_test_analyser.py -v
```

### Run Interactive Demo
See the test detection algorithm in action:
```bash
python analysis/demo_test_detection.py
```

## Test Modules Overview

### 1. Static Analysis Tests (`test_static_analysis.py`)
Tests the core TDD pattern detection:

- **`test_detect_same_commit_tdd`**: Verifies detection when test and source are in the same commit
- **`test_detect_diff_commit_tdd`**: Verifies detection when test precedes source
- **`test_no_tdd_unrelated_files`**: Ensures unrelated files aren't flagged
- **`test_is_related_file_logic`**: Tests file name matching algorithm

### 2. Lifecycle Analysis Tests (`test_lifecycle_analysis.py`)
Tests TDD adoption across project lifecycle:

- **`test_run_lifecycle_study_stage_division`**: Verifies correct stage division and percentage calculation

### 3. Creation Analysis Tests (`test_creation_analysis.py`)
Tests test/source file timing analysis:

- Verifies correct counting of before/same/after relationships
- Tests method-based and name-based pairing

### 4. Mining Tests (`repo_miner_test.py`, `apache_miner_test.py`)
Tests repository mining functionality:

- **`test_mine_repo_success`**: Standard mining path
- **`test_mine_repo_skips_existing_commits`**: Duplicate detection
- **`test_run_logic_splits_on_timeout`**: Timeout handling and job splitting
- **`test_run_success_flow`**: Apache miner end-to-end flow

### 5. Component Tests
- **`test_file_analyser.py`**: File type detection
- **`test_test_analyser.py`**: Test coverage extraction
- **`test_clean_db.py`**: Database cleanup operations

## TDD Detection Algorithm

### How It Works

1. **Identify Test Files**
   - Files with "test", "tests", "spec", or "specs" in the name
   - Detected by `FileAnalyser.is_test_file()`

2. **Extract Test Method Names**
   - Collect changed methods from test files in each commit

3. **Parse Method Names**
   - Remove prefixes: `test_`, `should_`, `when_`, `given_`
   - Split by underscores: `test_square_area` → `['square', 'area']`
   - Split camelCase: `testCalculatorAdd` → `['calculator', 'add']`

4. **Match Against Source Files**
   - Compare test file names to source file names
   - Check method token overlap between test and source
   - Example: `CalculatorTest.java` matches `Calculator.java`

5. **Detect TDD Patterns**
   - **Same-Commit TDD**: Test and source in same commit with related names
   - **Diff-Commit TDD**: Test committed before source file

### Key Methods

| Method | Location | Purpose |
|--------|----------|---------|
| `detect_tdd_in_commits()` | `analysis/static_analysis.py` | Main TDD detection |
| `_is_related_file()` | `analysis/static_analysis.py` | File name matching |
| `_methods_indicate_relation()` | `analysis/static_analysis.py` | Method-based matching |
| `is_test_file()` | `mining/components/file_analyser.py` | Test file detection |
| `analyze_test_coverage()` | `mining/components/test_analyser.py` | Coverage extraction |

## Project Structure for Tests

```
tests/
├── __init__.py
├── test_static_analysis.py      # TDD detection tests
├── test_lifecycle_analysis.py   # Lifecycle analysis tests
├── test_creation_analysis.py    # Creation timing tests
├── test_file_analyser.py        # File type detection tests
├── test_test_analyser.py        # Test coverage tests
├── test_source_file_calculator.py
├── test_clean_db.py             # Database cleanup tests
├── test_coverage_demo.py        # Coverage demo tests
├── repo_miner_test.py           # Mining tests
└── apache_miner_test.py         # Apache API tests
```

## Writing New Tests

### Mocking Database Connections
All tests mock database connections to avoid real DB calls:

```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def analyzer():
    commits_col = MagicMock()
    repos_col = MagicMock()
    return Static_Analysis(commits_col, repos_col, "Java", write_to_db=False)
```

### Creating Mock Commits
Use helper functions to create test data:

```python
def create_mock_commit(hash_val, date, test_files=None, source_files=None):
    tf_list = [{"filename": f, "changed_methods": []} for f in (test_files or [])]
    sf_list = [{"filename": f, "changed_methods": []} for f in (source_files or [])]
    
    return {
        "hash": hash_val,
        "committer_date": date,
        "test_coverage": {
            "test_files": tf_list,
            "source_files": sf_list,
            "tested_files": [f["filename"] for f in sf_list]
        }
    }
```

### Testing Return Types
Note that `detect_tdd_in_commits()` returns a tuple:

```python
# Correct - unpack the tuple
patterns, log_string = analyzer.detect_tdd_in_commits([commit])

# Then assert on patterns
assert len(patterns) == 1
assert patterns[0]['mode'] == 'same_commit'
```

## Expected Test Results

When you run all tests, you should see:

```
tests/test_static_analysis.py ....                                    [  6%]
tests/test_lifecycle_analysis.py .                                    [  7%]
tests/test_creation_analysis.py ....                                  [ 13%]
tests/apache_miner_test.py ............                               [ 30%]
tests/repo_miner_test.py ..............                               [ 50%]
...
========================= 69 passed in X.XXs =========================
```

## Troubleshooting

### Tests Pass But MongoDB Fails
If unit tests pass but `main.py` fails with MongoDB errors:
- The test suite uses mocks and doesn't require a real database
- Check your `.env` file has correct MongoDB credentials
- Verify your internet connection

### Import Errors
If you see `ModuleNotFoundError`:
- Ensure you're running from the project root directory
- Check that all `__init__.py` files exist in package directories
- Verify the package structure matches the imports

### Mock Configuration Issues
If tests fail with "expected call not found":
- Check that patch paths use the new package structure (e.g., `mining.worker.Repository` not `worker.Repository`)
- Ensure mock return values match expected types (e.g., tuples for `detect_tdd_in_commits`)

### False Positives in Detection
If you see files incorrectly marked as tested:
- Check the test method names
- Very generic names like `test_data()` might match multiple files
- The algorithm ignores tokens < 3 characters to reduce false positives

### False Negatives
If tested files are not detected:
- Verify test method names contain the source filename
- Check that file extensions match supported languages
- Review the `_is_related_file()` matching logic

## Manual Verification Checklist

- [ ] Run `pytest tests/ -v` - all 69 tests pass
- [ ] Run `python analysis/demo_test_detection.py` - see correct output
- [ ] Verify no import errors when running analysis scripts
- [ ] Check that `analysis-output/` files are generated correctly
- [ ] Confirm percentages in output are ≤ 100%
