import pytest
from unittest.mock import MagicMock, patch
import enrich_commits

class TestEnrichCommits:

    @pytest.mark.parametrize("path,expected", [
        ("src/test/java/FooTest.java", True),
        ("tests/test_api.py", True),
        ("src/main/java/Foo.java", False),
        ("README.md", False),
        # FIXED: Documentation should NOT be classified as test code.
        # The code correctly returns False because the extension is .doc
        ("docs/test_plan.doc", False), 
        ("docs/test_plan.py", True), # This would be True (python script in docs)
    ])
    def test_is_test_path(self, path, expected):
        assert enrich_commits.is_test_path(path) is expected

    def test_extract_paths_handles_dicts_and_strings(self):
        modified_files = [
            {"filename": "a.py"},
            "b.py",
            {"filename": None}
        ]
        result = enrich_commits.extract_paths(modified_files)
        assert result == ["a.py", "b.py"]

    @patch("enrich_commits.get_collection")
    def test_main_logic(self, mock_get_col):
        """Test the update logic loop."""
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        
        # Mock finding one commit
        mock_col.find.return_value = [{
            "_id": 1,
            "modified_files": [{"filename": "test_a.py"}, {"filename": "a.py"}]
        }]
        
        enrich_commits.main()
        
        assert mock_col.bulk_write.called
        # Get the operation passed to bulk_write
        args = mock_col.bulk_write.call_args[0][0]
        update_op = args[0]
        
        # Check classification
        set_data = update_op._doc['$set']
        assert set_data['commit_kind'] == "MIXED"
        assert set_data['has_test_changes'] is True
        assert set_data['has_prod_changes'] is True