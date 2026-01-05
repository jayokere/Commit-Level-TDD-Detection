import pytest
from unittest.mock import MagicMock
from datetime import datetime
from analysis.creation_analysis import creation_analysis

@pytest.fixture
def creation_analyzer():
    return creation_analysis(MagicMock(), MagicMock(), "Python")

class TestCreationAnalysis:

    def test_first_seen_map(self, creation_analyzer):
        """Verify it correctly finds the earliest date for files."""
        commits = [
            {
                "committer_date": "2023-01-10",
                "test_coverage": {
                    "test_files": [{"filename": "test_a.py"}]
                }
            },
            {
                "committer_date": "2023-01-05", # Earlier date
                "test_coverage": {
                    "test_files": [{"filename": "test_a.py"}]
                }
            }
        ]
        
        result = creation_analyzer._first_seen_map(commits, "test")
        assert result["test_a.py"] == datetime(2023, 1, 5)

    def test_analyze_project_counts_logic(self, creation_analyzer):
        """
        Simulate a project where:
        - test_b.py created BEFORE b.py
        - test_a.py created AFTER a.py
        """
        # Mocking the internal helpers to skip complex parsing logic
        # We inject the "first seen" maps directly into the logic flow 
        # but since _analyze_project_counts calls _first_seen_map internally, 
        # we construct inputs that _first_seen_map will parse correctly.
        
        c1 = {
            "committer_date": "2023-01-01",
            "test_coverage": {
                "test_files": [{"filename": "test_before.py"}], # Test created
                "source_files": [{"filename": "after.py"}]      # Source created
            }
        }
        c2 = {
            "committer_date": "2023-01-05",
            "test_coverage": {
                "source_files": [{"filename": "before.py"}],    # Source created later
                "test_files": [{"filename": "test_after.py"}]   # Test created later
            }
        }
        
        commits = [c1, c2]
        
        # Run analysis
        before, same, after, paired, _, _, note = creation_analyzer._analyze_project_counts(commits)
        
        # test_before.py (Jan 1) vs before.py (Jan 5) -> BEFORE
        # test_after.py (Jan 5) vs after.py (Jan 1) -> AFTER
        
        assert paired == 2
        assert before == 1
        assert after == 1
        assert same == 0

    def test_best_source_match_tie_breaking(self, creation_analyzer):
        """Test the heuristic for picking best source match."""
        test_file = "test_data_manager.py"
        candidates = ["data.py", "data_manager.py"] # Both 'could' be related
        
        # data_manager.py is a stronger match for test_data_manager.py
        # because the name overlap is more complete.
        best = creation_analyzer._best_source_match(test_file, candidates)
        assert best == "data_manager.py"