# Testing Guide for Test File Detection (Issue #4)

This guide explains how to verify that the code correctly identifies test files and which source files are being tested.

## Quick Start

### 1. Run Unit Tests
The most reliable way to verify the implementation:

```bash
# Run all repo_miner tests (including the 3 new tests for Issue #4)
python3 -m pytest tests/repo_miner_test.py -v

# Run only the test coverage demonstration
python3 -m pytest tests/test_coverage_demo.py -v -s
```

### 2. Run Interactive Demo
See the algorithm in action with visual output:

```bash
python3 demo_test_detection.py
```

This will show you three scenarios:
- **Scenario 1**: The exact example from GitHub Issue #4 (shapes_test.py)
- **Scenario 2**: Java camelCase naming conventions
- **Scenario 3**: Python snake_case naming conventions

## What Gets Tested?

### Test Coverage Detection Tests

#### `test_is_test_file()`
Verifies that test files are correctly identified:
- ✅ `shapes_test.py` → Identified as test
- ✅ `TestCalculator.java` → Identified as test
- ✅ `test_utils.py` → Identified as test
- ❌ `shapes.py` → Not a test file
- ❌ `Calculator.java` → Not a test file

#### `test_extract_tested_files_from_methods()`
**This is the key test for Issue #4!**

Given these files:
- `shapes_test.py` (test file)
- `square.py` (source)
- `triangle.py` (source)
- `shapes.py` (source)

And these test methods:
- `test_square_area`
- `test_triangle_perimeter`
- `test_shape_color`

The algorithm should identify **ALL THREE** source files as tested:
- ✅ `square.py` (from "test_square_area")
- ✅ `triangle.py` (from "test_triangle_perimeter")
- ✅ `shapes.py` (from "test_shape_color")

#### `test_analyze_test_coverage()`
Validates the complete analysis structure returns:
- `test_files`: List of test files with their methods
- `source_files`: List of non-test source files
- `tested_files`: List of source files that have associated tests

## How It Works

### Algorithm Overview

1. **Identify Test Files**
   - Files with "test", "tests", "spec", or "specs" in the name

2. **Extract Test Method Names**
   - Collect all method names from test files

3. **Parse Method Names**
   - Remove prefixes: `test_`, `should_`, `when_`
   - Remove suffixes: `_test`, `_spec`
   - Split by underscores: `test_square_area` → `['square', 'area']`
   - Split camelCase: `testCalculatorAdd` → `['calculator', 'add']`

4. **Match Against Source Files**
   - Extract filename without extension
   - Check if any parsed component matches the filename
   - Example: `'square'` matches `square.py`

5. **Filter Results**
   - Ignore components < 3 characters (avoid false positives)
   - Exclude test files from "tested files" list

## Testing with Real Data

To test with actual repository data (requires MongoDB):

```python
from pydriller import Repository
from repo_miner import Repo_miner

# Mine a single commit
repo = Repository("https://github.com/some/repo")
for commit in repo.traverse_commits():
    coverage = Repo_miner.analyze_test_coverage(commit.modified_files)
    
    print(f"Commit: {commit.hash}")
    print(f"Test files: {[f['filename'] for f in coverage['test_files']]}")
    print(f"Tested files: {coverage['tested_files']}")
    break  # Just check one commit
```

## Expected Test Results

When you run the tests, you should see:

```
tests/repo_miner_test.py::test_is_test_file PASSED                    [ 53%]
tests/repo_miner_test.py::test_extract_tested_files_from_methods PASSED [ 61%]
tests/repo_miner_test.py::test_analyze_test_coverage PASSED           [ 69%]
```

And in the demo:

```
✨ Tested Files Detected:
    ✅ square.py
    ✅ triangle.py
    ✅ shapes.py

💡 Explanation:
  • 'test_square_area' → extracted 'square' → matched square.py
  • 'test_triangle_perimeter' → extracted 'triangle' → matched triangle.py
  • 'test_shape_color' → extracted 'shape' → matched shapes.py
```

## What This Solves (GitHub Issue #4)

**Before:** The code only used filename patterns to find test files, missing files like `square.py` and `triangle.py` when the test file was named `shapes_test.py`.

**After:** The code analyzes test method names to determine which files are actually being tested, correctly identifying:
- `test_square_area()` → tests `square.py`
- `test_triangle_perimeter()` → tests `triangle.py`
- `test_shape_color()` → tests `shapes.py`

All three source files are now correctly identified as having test coverage! 🎉

## Troubleshooting

### Tests Pass But MongoDB Fails

If unit tests pass but `main.py` fails with MongoDB errors:
- The Issue #4 fix is working correctly
- The MongoDB error is a separate infrastructure issue
- Check your internet connection and `.env` credentials

### False Positives

If you see files incorrectly marked as tested:
- Check the test method names
- Very generic names like `test_data()` might match multiple files
- Adjust the minimum component length in `extract_tested_files_from_methods()`

### False Negatives

If tested files are not detected:
- Verify test method names contain the source filename
- Add more test pattern prefixes/suffixes if needed
- Check that file extensions match `VALID_CODE_EXTENSIONS`

## Manual Verification Checklist

- [ ] Run `pytest tests/repo_miner_test.py -v` - all tests pass
- [ ] Run `python3 demo_test_detection.py` - see correct output
- [ ] Scenario 1 identifies all 3 source files (square, triangle, shapes)
- [ ] Scenario 2 excludes unrelated StringUtil.java
- [ ] Scenario 3 handles snake_case correctly
- [ ] No false positives from very short names
