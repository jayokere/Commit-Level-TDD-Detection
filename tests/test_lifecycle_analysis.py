import pytest
from unittest.mock import MagicMock
from lifecycle_analysis import LifecycleAnalysis

@pytest.fixture
def lifecycle():
    return LifecycleAnalysis(MagicMock(), MagicMock(), "Java")

class TestLifecycleAnalysis:

    def test_run_lifecycle_study_stage_division(self, lifecycle):
        # Mock 4 commits to have exactly 1 per stage (4 stages total)
        # Commit 1: TDD
        c1 = {"hash": "1", "test_coverage": {"test_files": ["T1"], "source_files": ["S1"]}} 
        # Commit 2: No TDD
        c2 = {"hash": "2", "test_coverage": {"test_files": [], "source_files": ["S2"]}}
        # Commit 3: TDD
        c3 = {"hash": "3", "test_coverage": {"test_files": ["T3"], "source_files": ["S3"]}}
        # Commit 4: No TDD
        c4 = {"hash": "4", "test_coverage": {"test_files": [], "source_files": ["S4"]}}

        # We need to mock detect_tdd_in_commits to return patterns based on input
        # Simple strategy: if test_files & source_files not empty -> TDD
        def mock_detect(commits):
            found = []
            for c in commits:
                tc = c['test_coverage']
                if tc['test_files'] and tc['source_files']:
                    found.append(c)
            return found
        
        lifecycle.detect_tdd_in_commits = mock_detect
        lifecycle.get_commits_for_project = MagicMock(return_value=[c1, c2, c3, c4])
        lifecycle._get_project_names = MagicMock(return_value=["ProjectA"])
        
        # Run
        lifecycle.run_lifecycle_study(sample_limit=1)
        
        # Check stats
        # Stage 1 (c1): 1 commit, 1 TDD -> 100%
        # Stage 2 (c2): 1 commit, 0 TDD -> 0%
        # Stage 3 (c3): 1 commit, 1 TDD -> 100%
        # Stage 4 (c4): 1 commit, 0 TDD -> 0%
        
        assert lifecycle.stage_adoption_sums[1] == 100.0
        assert lifecycle.stage_adoption_sums[2] == 0.0
        assert lifecycle.stage_adoption_sums[3] == 100.0
        assert lifecycle.stage_adoption_sums[4] == 0.0