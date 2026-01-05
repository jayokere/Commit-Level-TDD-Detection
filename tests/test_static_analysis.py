import pytest
from unittest.mock import MagicMock, patch
from analysis.static_analysis import Static_Analysis

@pytest.fixture
def analyzer():
    commits_col = MagicMock()
    repos_col = MagicMock()
    # Create instance with write_to_db=False to avoid DB mocks in logic
    return Static_Analysis(commits_col, repos_col, "Java", write_to_db=False)

def create_mock_commit(hash_val, committer_date, test_files=None, source_files=None):
    """Helper to build the dictionary structure expected by Static_Analysis."""
    # Build list of dicts for files
    tf_list = [{"filename": f, "changed_methods": []} for f in (test_files or [])]
    sf_list = [{"filename": f, "changed_methods": []} for f in (source_files or [])]
    
    return {
        "hash": hash_val,
        "committer_date": committer_date,
        "test_coverage": {
            "test_files": tf_list,
            "source_files": sf_list,
            # For this test, we assume 'tested_files' might be populated but 
            # detection relies heavily on _is_related_file logic internally
            "tested_files": [f["filename"] for f in sf_list] 
        }
    }

class TestStaticAnalysis:

    def test_detect_same_commit_tdd(self, analyzer):
        """Test detection when Test and Source are in the same commit."""
        c1 = create_mock_commit(
            "h1", "2023-01-01",
            test_files=["CalculatorTest.java"],
            source_files=["Calculator.java"]
        )
        
        patterns = analyzer.detect_tdd_in_commits([c1])
        
        assert len(patterns) == 1
        assert patterns[0]['mode'] == 'same_commit'
        assert patterns[0]['tdd_percentage'] == 100.0

    def test_detect_diff_commit_tdd(self, analyzer):
        """Test detection when Test is in Commit 1, Source is in Commit 2."""
        # C1: Test Only
        c1 = create_mock_commit(
            "h1", "2023-01-01",
            test_files=["CalculatorTest.java"],
            source_files=[]
        )
        # C2: Source Only (Related)
        c2 = create_mock_commit(
            "h2", "2023-01-02",
            test_files=[],
            source_files=["Calculator.java"]
        )
        
        patterns = analyzer.detect_tdd_in_commits([c1, c2])
        
        assert len(patterns) == 1
        p = patterns[0]
        assert p['mode'] == 'diff_commit'
        assert p['test_commit'] == "h1"
        assert p['source_commit'] == "h2"
        assert p['tdd_percentage'] == 100.0

    def test_no_tdd_unrelated_files(self, analyzer):
        """Test that unrelated files are not flagged as TDD."""
        c1 = create_mock_commit("h1", "date", test_files=["TestA.java"], source_files=[])
        c2 = create_mock_commit("h2", "date", test_files=[], source_files=["ClassB.java"])
        
        patterns = analyzer.detect_tdd_in_commits([c1, c2])
        assert len(patterns) == 0

    def test_is_related_file_logic(self, analyzer):
        # Direct match
        assert analyzer._is_related_file("CalculatorTest.java", "Calculator.java") is True
        # Prefix
        assert analyzer._is_related_file("test_utils.py", "utils.py") is True
        # Suffix
        assert analyzer._is_related_file("UtilsSpec.ts", "Utils.ts") is True
        # Unrelated
        assert analyzer._is_related_file("UserTest.java", "Order.java") is False