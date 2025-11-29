import unittest
from unittest.mock import patch, MagicMock
from apache_web_miner import Apache_web_miner  # Import your class

class TestApacheWebMiner(unittest.TestCase):

    def setUp(self):
        """
        This runs before EVERY test function. 
        It creates a fresh miner instance so tests don't interfere with each other.
        """
        self.test_url = "http://fake-url.com/data.json"
        self.miner = Apache_web_miner(self.test_url)

    # --- Test 1: Does it initialize correctly? ---
    def test_initialization(self):
        self.assertEqual(self.miner.url, self.test_url)
        self.assertEqual(self.miner.data, {})

    # --- Test 2: Logic Check (Does it filter links correctly?) ---
    def test_get_github_links_logic(self):
        """
        Here we manually inject fake data into the miner 
        to test the filtering logic without needing the internet.
        """
        # Scenario: 
        # 1. 'Valid Project' has a github link AND a non-github link.
        # 2. 'No Github Project' has a repository list, but no github links.
        # 3. 'Empty Project' has no repository list at all.
        fake_data = {
            "proj_1": {
                "name": "Valid Project",
                "repository": [
                    "https://github.com/apache/valid", 
                    "https://gitbox.apache.org/valid"
                ]
            },
            "proj_2": {
                "name": "No Github Project",
                "repository": ["https://svn.apache.org/old"]
            },
            "proj_3": {
                "name": "Empty Project"
            }
        }

        # Inject the fake data
        self.miner.data = fake_data
        
        # Run the method
        results = self.miner.get_github_links()

        # Assertions (The "Test")
        # 1. Should contain "Valid Project"
        self.assertIn("Valid Project", results)
        
        # 2. Should NOT contain the others
        self.assertNotIn("No Github Project", results)
        self.assertNotIn("Empty Project", results)

        # 3. The list for "Valid Project" should ONLY have the github link
        expected_list = ["https://github.com/apache/valid"]
        self.assertEqual(results["Valid Project"], expected_list)

    # --- Test 3: Network Check (Mocking the API call) ---
    @patch('requests.get')
    def test_fetch_data_success(self, mock_get):
        """
        We mock requests.get so it doesn't actually hit the internet.
        """
        # Create a fake response object
        mock_response = MagicMock()
        expected_json = {"id": "test_project", "name": "Test"}
        
        # Tell the mock: "When .json() is called, return this dictionary"
        mock_response.json.return_value = expected_json
        mock_response.status_code = 200
        
        # Tell requests.get: "Return our fake response object"
        mock_get.return_value = mock_response

        # Run the actual function
        self.miner.fetch_data()

        # Verify the data was stored correctly
        self.assertEqual(self.miner.data, expected_json)
        
        # Verify requests.get was actually called with the right URL
        mock_get.assert_called_with(self.test_url)

    # --- Test 4: Network Failure Handling ---
    @patch('requests.get')
    def test_fetch_data_failure(self, mock_get):
        """
        Test what happens if the internet is down.
        """
        # Make requests.get raise an error
        mock_get.side_effect = Exception("Internet Down")

        # Run the function (it should catch the error and print it, not crash)
        self.miner.fetch_data()

        # Data should still be empty
        self.assertEqual(self.miner.data, {})

if __name__ == '__main__':
    unittest.main()