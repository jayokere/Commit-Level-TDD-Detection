import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import requests

# -------------------------------------------------------------------------
# PATH SETUP
# -------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# -------------------------------------------------------------------------
# MOCKING DEPENDENCIES
# -------------------------------------------------------------------------
# 1. Create the mocks globally
mock_db = MagicMock()
mock_intro = MagicMock()
mock_utils = MagicMock()

# 2. Configure utilities
def pass_through_decorator(func):
    return func
mock_utils.measure_time.side_effect = pass_through_decorator
mock_utils.ping_target.return_value = True 

# 3. Inject mocks into sys.modules
sys.modules['database.db'] = mock_db
sys.modules['utilities.miner_intro'] = mock_intro
sys.modules['utilities.utils'] = mock_utils

# Now safe to import the actual miner
from mining.apache_miner import ApacheGitHubMiner, RateLimitExceededError

class TestApacheGitHubMiner(unittest.TestCase):

    def setUp(self):
        """Set up a fresh miner instance before every test."""
        # Reset the DB mock calls to ensure a clean slate for each test
        mock_db.reset_mock()
        
        with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            self.miner = ApacheGitHubMiner(num_threads=1)
            self.miner.session.mount = MagicMock()

    def test_init_sets_headers(self):
        self.assertIn("Authorization", self.miner.session.headers)
        self.assertEqual(self.miner.session.headers["Authorization"], "token fake-token")

    # -------------------------------------------------------------------------
    # Rate Limit Logic
    # -------------------------------------------------------------------------
    def test_check_rate_limit_healthy(self):
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        response.headers = {'X-RateLimit-Remaining': '5000'}
        self.miner._check_rate_limit(response)
        self.assertFalse(self.miner._stop_event.is_set())

    def test_check_rate_limit_403_triggers_stop(self):
        response = MagicMock(spec=requests.Response)
        response.status_code = 403
        response.headers = {'X-RateLimit-Reset': '1700000000'}
        with self.assertRaises(RateLimitExceededError):
            self.miner._check_rate_limit(response)
        self.assertTrue(self.miner._stop_event.is_set())

    def test_check_rate_limit_zero_remaining(self):
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        response.headers = {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1700000000'}
        with self.assertRaises(RateLimitExceededError):
            self.miner._check_rate_limit(response)
        self.assertTrue(self.miner._stop_event.is_set())

    def test_check_rate_limit_respects_stop_event(self):
        self.miner._stop_event.set()
        response = MagicMock(spec=requests.Response)
        with self.assertRaisesRegex(RateLimitExceededError, "Global stop signal"):
            self.miner._check_rate_limit(response)

    # -------------------------------------------------------------------------
    # Repo Count
    # -------------------------------------------------------------------------
    @patch('apache_miner.requests.Session.get')
    def test_get_total_org_repos_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"public_repos": 150}
        mock_get.return_value = mock_response
        self.assertEqual(self.miner.get_total_org_repos(), 150)

    @patch('apache_miner.requests.Session.get')
    def test_get_total_org_repos_failure(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404 
        mock_get.return_value = mock_response
        self.assertEqual(self.miner.get_total_org_repos(), 0)

    # -------------------------------------------------------------------------
    # Fetch Page
    # -------------------------------------------------------------------------
    @patch('apache_miner.requests.Session.get')
    def test_fetch_page_filtering(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "ProjectA", "html_url": "url1", "url": "api1", "language": "Java"},
            {"name": "ProjectB", "html_url": "url2", "url": "api2", "language": "Go"},
            {"name": "ProjectC", "html_url": "url3", "url": "api3", "language": "Python"},
        ]
        mock_get.return_value = mock_response
        results = self.miner._fetch_page(1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['language'], "Java")
        self.assertEqual(results[1]['language'], "Python")

    def test_fetch_page_stops_if_event_set(self):
        self.miner._stop_event.set()
        self.assertEqual(self.miner._fetch_page(1), [])

    # -------------------------------------------------------------------------
    # Commit Counting
    # -------------------------------------------------------------------------
    @patch('apache_miner.requests.Session.get')
    def test_get_commit_count_pagination_trick(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Correctly formatted URL param for the regex to find
        mock_response.headers = {'Link': '<https://api.github.com/commits?per_page=1&page=500>; rel="last"'}
        mock_get.return_value = mock_response
        self.assertEqual(self.miner.get_commit_count("http://fake.api"), 500)

    @patch('apache_miner.requests.Session.get')
    def test_get_commit_count_small_repo(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = [1, 2, 3, 4, 5] 
        mock_get.return_value = mock_response
        self.assertEqual(self.miner.get_commit_count("http://fake.api"), 5)

    def test_get_commit_count_returns_zero_on_stop(self):
        self.miner._stop_event.set()
        self.assertEqual(self.miner.get_commit_count("http://fake.api"), 0)

    # -------------------------------------------------------------------------
    # Orchestration
    # -------------------------------------------------------------------------
    @patch('apache_miner.ping_target')
    def test_fetch_candidate_repos_aborts_on_ping_fail(self, mock_ping):
        mock_ping.return_value = False 
        self.assertEqual(self.miner.fetch_candidate_repos(), [])

    @patch('apache_miner.ping_target')
    @patch('apache_miner.ApacheGitHubMiner.get_total_org_repos')
    def test_fetch_candidate_repos_aborts_on_zero_repos(self, mock_get_total, mock_ping):
        mock_ping.return_value = True
        mock_get_total.return_value = 0 
        self.assertEqual(self.miner.fetch_candidate_repos(), [])

    @patch('apache_miner.ApacheGitHubMiner.get_commit_count')
    @patch('apache_miner.ApacheGitHubMiner.fetch_candidate_repos')
    @patch('apache_miner.ThreadPool') 
    def test_run_success_flow(self, mock_threadpool, mock_fetch, mock_get_commits):
        """
        Test the main run loop.
        """
        # 1. Setup Data
        mock_fetch.return_value = [
            {"name": "Repo1", "url": "u1", "api_url": "a1", "language": "Java"}
        ]
        
        # 2. Mock ThreadPool
        # Since ThreadPool is used as a Context Manager (with ... as pool:),
        # we must mock the return value of __enter__.
        mock_pool_instance = mock_threadpool.return_value
        mock_pool_instance.__enter__.return_value = mock_pool_instance
        
        processed_result = {
            "name": "Repo1", "url": "u1", "language": "Java", "commits": 100
        }
        # Now that we patched the correct object, this return value will actually be used
        mock_pool_instance.imap_unordered.return_value = [processed_result]
        
        # 3. Run
        self.miner.run()
        
        # 4. Assert
        # Check that we fetched repos
        mock_fetch.assert_called_once()
        
        # Check that we SAVED to the DB.
        # Ensure 'mock_db' is available in your test class scope or imported
        mock_db.save_repo_batch.assert_called_once_with([processed_result], "apache-repos")
        
if __name__ == '__main__':
    unittest.main()