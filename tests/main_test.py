import unittest
from unittest.mock import patch, mock_open, MagicMock
import json

# We import the functions we want to test from main
from main import fetch_project_data, DATA_FILE

class TestMainWorkflow(unittest.TestCase):

    # --- Scenario 1: The File Already Exists (Cache Hit) ---
    @patch('main.os.path.exists')  # Mock checking if file exists
    @patch('builtins.open', new_callable=mock_open, read_data='{"SavedProject": ["url"]}') # Mock opening a file
    @patch('main.Apache_web_miner') # Mock the miner class
    def test_get_data_from_local_file(self, mock_miner_class, mock_file, mock_exists):
        
        # 1. SETUP: Tell the system the file DOES exist
        mock_exists.return_value = True 

        # 2. EXECUTE
        result = fetch_project_data()

        # 3. ASSERTIONS
        # The result should come from the 'read_data' in our mock_open above
        self.assertEqual(result, {"SavedProject": ["url"]})
        
        # Crucial: Ensure we did NOT try to use the miner (internet)
        mock_miner_class.assert_not_called()
        
        # Ensure we actually opened the file in 'read' mode
        mock_file.assert_called_with(DATA_FILE, "r")

    # --- Scenario 2: The File is Missing (Cache Miss) ---
    @patch('main.os.path.exists')
    @patch('builtins.open', new_callable=mock_open) # Mock file opening
    @patch('main.Apache_web_miner')
    @patch('main.json.dump') # Mock saving the JSON
    def test_get_data_from_web(self, mock_json_dump, mock_miner_class, mock_file, mock_exists):
        
        # 1. SETUP: Tell the system the file does NOT exist
        mock_exists.return_value = False
        
        # Setup the fake miner to return some data
        mock_miner_instance = mock_miner_class.return_value
        fake_data = {"NewProject": ["new_url"]}
        mock_miner_instance.get_github_links.return_value = fake_data

        # 2. EXECUTE
        result = fetch_project_data()

        # 3. ASSERTIONS
        # The result should come from the miner
        self.assertEqual(result, fake_data)

        # Verify the miner WAS called
        mock_miner_class.assert_called_once()
        mock_miner_instance.fetch_data.assert_called_once()
        
        # Verify we tried to SAVE the file (opened with 'w')
        mock_file.assert_called_with(DATA_FILE, "w")
        
        # Verify json.dump was called to write the data
        mock_json_dump.assert_called()

if __name__ == '__main__':
    unittest.main()