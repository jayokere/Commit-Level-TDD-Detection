"""
Check for TDD in separate commits. Check the current commit for the presence of a test file.
If true, check the next commit for a related source file. If true, mark the second commit as tdd_in_diff_commit: True
"""
from db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION
from bson.json_util import dumps
from typing import List, Dict, Any, Optional
import os

STATIC_ANALYSIS_OUTPUT_FILE = "analysis-output/{}_static_analysis.txt" 
SAMPLE_COUNT = 60
JAVA = "Java"
PYTHON = "Python"
CPP = "C++"

commits = get_collection(COMMIT_COLLECTION)
repos = get_collection(REPO_COLLECTION)

class Static_Analysis:
    """Class for analyzing commits and detecting TDD patterns."""
    
    def __init__(self, commits_collection, repos_collection, language: str):
        """Initialize with MongoDB collections."""
        self.commits = commits_collection
        self.repos = repos_collection
        self._language = language
        self._isVerbose = False
        self.output_log = ""
        self._projects_with_tdd_detected_count = 0
    
    def analyze(self):
        """Analyze commits for TDD patterns within the same commit or across consecutive commits."""
        project_names = self._get_project_names()
        project_count = len(project_names)
        count = 0

        for i in range(project_count):
            name = project_names[i]
            commits = self.get_commits_for_project(name)
            total_commits = self._get_total_commits_for_project(name)
            if not commits:
                self.output_log += f"\n{i}.) {self._language} project with name \"{name}\" was not sampled\n"
                self.output_log += f"It has {total_commits} commits\n"
                self.log_if_verbose(f"{self._language} project with name \"{name}\" has been skipped for analysis")
                continue

            tdd_patterns = self.detect_tdd_in_commits(commits)

            self.output_log += f"\n{i}-{count}.) Checking TDD patters for project with name \"{name}\"\n"
            self.output_log += f"Total commits in project \"{name}\": {total_commits}\n"
            self.output_log += f"Detected TDD patterns ({len(tdd_patterns)} total):\n"

            percentage = (len(tdd_patterns) / total_commits * 100) if total_commits > 0 else 0
            self.output_log += f"TDD pattern percentage: {percentage:.2f}% ({len(tdd_patterns)}/{total_commits})\n"

            if tdd_patterns:
                self._projects_with_tdd_detected_count += 1
                self.output_log += f"TDD detected in project \"{name}\". Detection count set to {self._projects_with_tdd_detected_count}.\n"

            for pattern in tdd_patterns:
                self.log_if_verbose(f"{dumps(pattern, indent=2)}\n")

            completion_percentage = (i / project_count * 100)
            self.log_if_verbose(f"Analysis progress: {completion_percentage:.2f}% ({i}/{project_count})")

    def _get_project_names(self) -> List[str]:
        """Get a sorted list of project names for the specified project from the repos collection."""
        repos = self.repos.find({ "language": self._language }, {"name": 1, "_id": 0})
        project_names = sorted([repo.get("name") for repo in repos if repo.get("name")])
        return project_names

    def detect_tdd_in_commits(self, commits) -> List[Dict]:
        """Detect TDD patterns where a test file is followed by a source file."""
        tdd_patterns = []
        
        for i in range(len(commits) - 1):
            current = commits[i]
            next_commit = commits[i + 1]
            
            self.log_if_verbose(f"Checking current commit: {current.get('hash')}")
            self.log_if_verbose(f"And potential next commit: {next_commit.get('hash')}")
            
            # Check if current commit has both test and source files
            if self._has_test_and_source_file(current):
                self.log_if_verbose(f"TDD pattern found in single commit: {current.get('hash')}")
                tdd_patterns.append({
                    "test_commit": current["hash"],
                    "test_files": self._extract_test_filenames(current),
                    "source_files": self._extract_source_filenames(current)
                })
            # Check if current commit has test files only
            elif self._has_test_files_only(current) and self._has_related_source_files(current, next_commit):
                self.log_if_verbose(f"TDD pattern found: {current.get('hash')} -> {next_commit.get('hash')}")
                tdd_patterns.append({
                    "test_commit": current["hash"],
                    "source_commit": next_commit["hash"],
                    "test_files": self._extract_test_filenames(current),
                    "source_files": self._extract_source_filenames(next_commit)
                })
            else:
                self.log_if_verbose(f"No TDD pattern found: {current.get('hash')} -> {next_commit.get('hash')}\n")
        
        return tdd_patterns

    def _has_test_files_only(self, commit: Dict) -> bool:
        """Check if a commit has test files only by verifying source_files and tested_files are empty in test_coverage."""
        test_coverage = commit.get("test_coverage", {})
        source_files = test_coverage.get("source_files", [])
        tested_files = test_coverage.get("tested_files", [])
        
        return len(source_files) == 0 and len(tested_files) == 0

    def _has_related_source_files(self, test_commit: Dict, source_commit: Dict) -> bool:
        """Check if the source commit has source files related to the test files in the test commit."""
        test_filenames = self._extract_test_filenames(test_commit)
        source_filenames = self._extract_source_filenames(source_commit)
        
        for test_filename in test_filenames:
            for source_filename in source_filenames:
                if self._is_related_file(test_filename, source_filename):
                    return True
        
        return False

    def _has_test_and_source_file(self, commit: Dict) -> bool:
        """Check if a singular commit has both test files and related source files."""
        test_filenames = self._extract_test_filenames(commit)
        source_filenames = self._extract_source_filenames(commit)
        
        if not test_filenames or not source_filenames:
            return False
        
        for test_filename in test_filenames:
            for source_filename in source_filenames:
                if self._is_related_file(test_filename, source_filename):
                    return True
        
        return False

    def _extract_test_filenames(self, test_commit: Dict) -> List[str]:
        """Extract test filenames from a commit's test_coverage."""
        test_coverage = test_commit.get("test_coverage", {})
        test_files = test_coverage.get("test_files", [])
        
        test_filenames = []
        for test_file in test_files:
            filename = test_file.get("filename", "")
            if filename:
                test_filenames.append(filename)
        
        return test_filenames

    def _extract_source_filenames(self, source_commit: Dict) -> List[str]:
        """Extract source filenames from a commit's test_coverage."""
        source_coverage = source_commit.get("test_coverage", {})
        source_files = source_coverage.get("source_files", [])
        
        source_filenames = []
        for source_file in source_files:
            filename = source_file.get("filename", "")
            if filename:
                source_filenames.append(filename)
        
        return source_filenames

    def _is_related_file(self, test_file: str, source_file: str) -> bool:
        """Check if a test file is related to a source file based on naming conventions."""
        # Remove path and extension for comparison
        test_name = test_file.split('/')[-1].split('.')[0].lower()
        source_name = source_file.split('/')[-1].split('.')[0].lower()
        
        # Check common patterns: TestFoo <-> Foo, FooTest <-> Foo, FooTestCase <-> Foo
        test_patterns = [
            test_name.replace('test', ''),
            test_name.replace('testcase', ''),
            test_name.replace('spec', '')
        ]
        
        source_patterns = [
            source_name,
            'test' + source_name,
            source_name + 'test',
            source_name + 'testcase',
            'spec' + source_name,
            source_name + 'spec'
        ]
        
        # Check if any test pattern matches any source pattern
        for test_p in test_patterns:
            if test_p and test_p in source_patterns:
                return True
        
        return False

    def get_commits_for_project(self, project_name) -> List[Dict[str, Any]]:
        """Fetch commits for the given project name from the mined commits repo 
        and sort by committer_date in ascending order."""
        return list(self.commits.find({"project": project_name}).sort("committer_date", 1))

    def _get_total_commits_for_project(self, project_name: str) -> int:
        """Return the total commits value for a project from the repos collection."""
        repo = self.repos.find_one({"name": project_name})
        if repo:
            return repo.get("commits", 0)
        return 0


    def get_commits_for_repo_url(self, repo_url) -> List[Dict[str, Any]]:
        """Fetch commits for the given repo url and sort by committer_date in ascending order."""
        return list(self.commits.find({"repo_url": repo_url}).sort("committer_date", 1))

    def set_is_verbose(self, verbose: bool):
        """Set the verbose flag for logging."""
        self._isVerbose = verbose
    
    def log_totals(self):
        """Print the total number of repos and commits stored in the database."""
        repo_count = self.repos.count_documents({})
        commit_count = self.commits.count_documents({})
        java_repo_count = self.repos.count_documents({"language": "Java"})
        python_repo_count = self.repos.count_documents({"language": "Python"})
        cpp_repo_count = self.repos.count_documents({"language": "C++"})
        self.output_log += f"Total repositories: {repo_count}\n"
        self.output_log += f"Total commits: {commit_count}\n"
        self.output_log += f"Total Java repositories: {java_repo_count}\n"
        self.output_log += f"Total Python repositories: {python_repo_count}\n"
        self.output_log += f"Total C++ repositories: {cpp_repo_count}\n"
    
    def log_final_analysis_results(self):
        """Log the percentage of projects with TDD detected over the sample count."""
        percentage = (self._projects_with_tdd_detected_count / SAMPLE_COUNT * 100) if SAMPLE_COUNT > 0 else 0
        self.output_log += f"\nFinal Results: {percentage:.2f}% of {self._language} projects ({self._projects_with_tdd_detected_count}/{SAMPLE_COUNT}) have TDD patterns detected\n"
    
    def log_if_verbose(self, msg):
        """Print a message only if verbose mode is enabled."""
        if self._isVerbose:
            print(msg)

    def print_output_log(self):
        """Print the output log."""
        print("\n" + "="*80)
        print(self.output_log)
        print("="*80)

    def write_output_log(self, filepath: str = STATIC_ANALYSIS_OUTPUT_FILE):
        """Write the output log to a file, overwriting if it already exists."""
        filepath = filepath.format(self._language)
        try:
            directory = os.path.dirname(filepath)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            with open(filepath, 'w') as f:
                f.write(self.output_log)
        except IOError as e:
            print(f"Error writing to file {filepath}: {e}")

def main() -> None:
    analysis = Static_Analysis(commits, repos, PYTHON) # Change to specificy langauge; JAVA, PYTHON or CPP
    analysis.set_is_verbose(True) # Set verbose logging True or False
    analysis.log_totals()
    analysis.analyze()
    analysis.log_final_analysis_results()
    analysis.print_output_log()
    analysis.write_output_log()

if __name__ == "__main__":
    main()
