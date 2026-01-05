import pytest
from unittest.mock import MagicMock
from analysis.lifecycle_analysis import LifecycleAnalysis

@pytest.fixture
def lifecycle():
    return LifecycleAnalysis(MagicMock(), MagicMock(), "Java")

class TestLifecycleAnalysis:

    def test_run_lifecycle_study_stage_division(self, lifecycle):
        # Mock 4 commits to have exactly 1 per stage (4 stages total)
        # Commit 1: TDD
        c1 = {"_id": "1", "hash": "1", "committer_date": "2023-01-01", "test_coverage": {"test_files": ["T1"], "source_files": ["S1"]}}
        # Commit 2: No TDD
        c2 = {"_id": "2", "hash": "2", "committer_date": "2023-01-02", "test_coverage": {"test_files": [], "source_files": ["S2"]}}
        # Commit 3: TDD
        c3 = {"_id": "3", "hash": "3", "committer_date": "2023-01-03", "test_coverage": {"test_files": ["T3"], "source_files": ["S3"]}}
        # Commit 4: No TDD
        c4 = {"_id": "4", "hash": "4", "committer_date": "2023-01-04", "test_coverage": {"test_files": [], "source_files": ["S4"]}}

        all_commits = [c1, c2, c3, c4]
        
        # Mock the internal fetch methods to return our test data
        lifecycle._get_commit_metadata = MagicMock(return_value=[
            {"_id": "1", "committer_date": "2023-01-01"},
            {"_id": "2", "committer_date": "2023-01-02"},
            {"_id": "3", "committer_date": "2023-01-03"},
            {"_id": "4", "committer_date": "2023-01-04"},
        ])
        
        # Map commits by ID for fetch
        commits_by_id = {c["_id"]: c for c in all_commits}
        def mock_fetch_by_ids(ids):
            return [commits_by_id[i] for i in ids if i in commits_by_id]
        lifecycle._fetch_commits_by_ids = MagicMock(side_effect=mock_fetch_by_ids)
        
        # Mock detect_tdd_in_commits to return patterns based on input
        # Returns tuple (patterns, log_string) to match new signature
        def mock_detect(commits):
            found = []
            for c in commits:
                tc = c.get('test_coverage', {})
                if tc.get('test_files') and tc.get('source_files'):
                    found.append({"test_commit": c["hash"]})
            return (found, "")
        
        lifecycle.detect_tdd_in_commits = mock_detect
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