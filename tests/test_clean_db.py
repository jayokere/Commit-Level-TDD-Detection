import pytest
from unittest.mock import MagicMock, patch, call
from database import clean_db

class TestCleanDB:

    @patch("database.clean_db.get_collection")
    def test_clean_duplicates_logic(self, mock_get_col):
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        
        # Mock the aggregation result: 1 group with 3 duplicates
        mock_col.aggregate.return_value = [
            {
                "_id": {"project": "p1", "hash": "h1"},
                "count": 3,
                "ids": ["id_keep", "id_remove_1", "id_remove_2"]
            }
        ]
        
        clean_db.clean_duplicates()
        
        # Should call bulk_write
        assert mock_col.bulk_write.called
        
        # We expect 2 deletions (the 2nd and 3rd ID)
        # Note: clean_db constructs DeleteOne objects
        ops = mock_col.bulk_write.call_args[0][0]
        assert len(ops) == 2
        
        # Verify IDs targeted
        assert ops[0]._filter['_id'] == "id_remove_1"
        assert ops[1]._filter['_id'] == "id_remove_2"