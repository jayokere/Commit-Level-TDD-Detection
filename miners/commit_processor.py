"""
Core commit processing utilities for traversing repositories and extracting metrics.
"""

from .file_analyser import FileAnalyser
from .test_analyser import TestAnalyser
from db import get_existing_commit_hashes, save_commit_batch


class CommitProcessor:
    """Processes commits from a repository and extracts metrics."""
    
    def __init__(self, batch_size=2000):
        """
        Initialize the commit processor.
        
        Args:
            batch_size (int): Number of commits to buffer before writing to DB.
        """
        self.batch_size = batch_size
    
    def process_commits(self, repo_miner, project_name, repo_url):
        """
        Traverse commits in a repository and extract metrics.
        
        Args:
            repo_miner (Repository): A PyDriller Repository object.
            project_name (str): Name of the project being mined.
            repo_url (str): URL of the repository.
            
        Yields:
            tuple: (commit_info_dict, new_commits_count, existing_count)
        """
        # Retrieve all commit hashes already stored for this project
        existing_hashes = get_existing_commit_hashes(project_name)
        initial_count = len(existing_hashes)
        
        commits_buffer = []
        new_commits_mined = 0
        
        # Traverse the git history of the repository
        for commit in repo_miner.traverse_commits():
            # Check: If hash exists in the DB, skip processing entirely
            if commit.hash in existing_hashes:
                continue
            
            # Filter: Only keep relevant files (Source/Tests) based on criteria
            relevant_files_objs = [f for f in commit.modified_files if FileAnalyser.is_valid_file(f)]
            
            if not relevant_files_objs:
                continue
            
            # Extract file metrics
            processed_files = [FileAnalyser.extract_file_metrics(f) for f in relevant_files_objs]
            
            # Analyze test coverage
            file_categories = TestAnalyser.map_test_relations(relevant_files_objs)
            
            # Construct the document object for MongoDB
            commit_info = {
                'project': project_name,
                'repo_url': repo_url,
                'hash': commit.hash,
                'committer_date': commit.committer_date,
                'lines_added': commit.insertions,
                'lines_removed': commit.deletions,
                'modified_files': processed_files,
                'file_categories': file_categories
            }
            
            commits_buffer.append(commit_info)
            new_commits_mined += 1
            
            # Batch write to DB to avoid hitting database connection limits
            if len(commits_buffer) >= self.batch_size:
                save_commit_batch(commits_buffer)
                commits_buffer = []
        
        # Save any remaining commits in the buffer
        if commits_buffer:
            save_commit_batch(commits_buffer)
        
        return new_commits_mined, initial_count
