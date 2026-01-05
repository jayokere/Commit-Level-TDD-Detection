"""
Check for TDD in separate commits. Check the current commit for the presence of a test file.
If true, check the next commit for a related source file. If true, mark the second commit as tdd_in_diff_commit: True
"""

import os
import sys

# Ensure parent directory is in sys.path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from database.db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION
from bson.json_util import dumps
from typing import List, Dict, Any, Optional, Set, Tuple
import re
from datetime import datetime
# --- MULTITHREADING IMPORTS ---
from concurrent.futures import ThreadPoolExecutor, as_completed
from utilities.config import LANGUAGE_MAP
import threading
from pathlib import Path

# Compute project root (parent of analysis/ directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_ANALYSIS_OUTPUT_FILE = str(PROJECT_ROOT / "analysis-output" / "{}_static_analysis.txt")
SAMPLE_COUNT = 60
HIGH_TDD_THRESHOLD = 35

commits = get_collection(COMMIT_COLLECTION)
repos = get_collection(REPO_COLLECTION)


class Static_Analysis:
    """Class for analyzing commits and detecting TDD patterns."""

    def __init__(
        self,
        commits_collection,
        repos_collection,
        language: str,
        write_to_db: bool = False,
    ):
        self.commits = commits_collection
        self.repos = repos_collection
        self._language = language
        self._isVerbose = False
        self.output_log = ""
        self.final_log = ""
        self._projects_with_tdd_detected_count = 0 
        self._high_tdd_projects_count = 0 
        self._tdd_adoption_rate_list = []
        self._write_to_db = write_to_db
        self._total_tdd_commits_count = 0  
        self._total_commits_analysed_count = 0  
        # --- LOCK FOR THREAD-SAFE CONSOLE PRINTING ---
        self._console_lock = threading.Lock()

    def analyze(self):
        """Analyze commits for TDD patterns using Multithreading."""
        project_names = self._get_project_names()
        project_count = len(project_names)
        
        # Using 10 workers as this is largely I/O bound (DB reads)
        max_workers = 60 
        print(f"🚀 Starting parallel analysis for {project_count} projects using {max_workers} threads...")

        completed_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all projects to the pool
            future_to_project = {
                executor.submit(self._analyze_single_project, name, i): name 
                for i, name in enumerate(project_names)
            }

            for future in as_completed(future_to_project):
                name = future_to_project[future]
                try:
                    # Retrieve result from the thread
                    result = future.result()
                    
                    # Unpack the results safely
                    (project_log, 
                     project_tdd_count, 
                     project_total_commits, 
                     project_percentage, 
                     tdd_detected_bool, 
                     high_tdd_bool) = result

                    # --- MAIN THREAD AGGREGATION (Safe) ---
                    # Append the project's log buffer to the main output log
                    self.output_log += project_log
                    
                    # Update totals
                    self._total_tdd_commits_count += project_tdd_count
                    self._total_commits_analysed_count += project_total_commits
                    self._tdd_adoption_rate_list.append(project_percentage)

                    if tdd_detected_bool:
                        self._projects_with_tdd_detected_count += 1
                    if high_tdd_bool:
                        self._high_tdd_projects_count += 1

                except Exception as exc:
                    print(f"❌ Exception analyzing {name}: {exc}")
                
                # Update progress bar
                completed_count += 1
                self._print_progress(completed_count, project_count)

    def _analyze_single_project(self, name: str, index: int) -> Tuple[str, int, int, float, bool, bool]:
        """
        Helper method to run analysis for a single project.
        Designed to be thread-safe by avoiding direct writes to self.output_log.
        
        Returns:
            (log_string, tdd_count, total_commits, percentage, detected_bool, high_tdd_bool)
        """
        local_log = ""  # Local buffer for this thread
        
        commits = self.get_commits_for_project(name)
        total_commits = self._get_total_commits_for_project(name)
        
        if not commits:
            local_log += f"\n{index}.) {self._language} project \"{name}\" was not sampled\n"
            local_log += f"It has {total_commits} commits\n"
            return (local_log, 0, total_commits, 0.0, False, False)

        # Detect patterns (this method now returns the log string too)
        tdd_patterns, detection_log = self.detect_tdd_in_commits(commits)
        
        # Count unique commits that exhibit TDD (not pattern count)
        tdd_commit_hashes = set()
        for pattern in tdd_patterns:
            if pattern.get("test_commit"):
                tdd_commit_hashes.add(pattern["test_commit"])
        num_tdd_commits = len(tdd_commit_hashes)
        
        # Build the log string locally
        local_log += f"\n{index}.) Checking TDD patterns for project \"{name}\"\n"
        local_log += f"Total commits in project \"{name}\": {total_commits}\n"
        local_log += f"Detected TDD patterns ({len(tdd_patterns)} total, {num_tdd_commits} unique commits):\n"
        
        percentage = (num_tdd_commits / total_commits * 100) if total_commits > 0 else 0
        local_log += f"TDD pattern percentage: {percentage:.2f}% ({num_tdd_commits}/{total_commits})\n"
        
        # Append the detailed detection logs
        local_log += detection_log

        detected = False
        if tdd_patterns:
            detected = True
            local_log += f"TDD detected in project \"{name}\".\n"

        high_tdd = False
        if percentage > HIGH_TDD_THRESHOLD:
            high_tdd = True
            local_log += f"High TDD adoption (>20%) detected in project \"{name}\".\n"

        # If verbose, dump pattern details to local log
        for pattern in tdd_patterns:
            local_log += f"{dumps(pattern, indent=2)}\n"

        return (local_log, num_tdd_commits, total_commits, percentage, detected, high_tdd)

    def _print_progress(self, completed, total):
        """Thread-safe progress print."""
        percent = (completed / total) * 100
        with self._console_lock:
            print(f"\rAnalysis progress: {percent:.2f}% ({completed}/{total})", end="", flush=True)

    def _get_project_names(self) -> List[str]:
        repos_cursor = self.repos.find({"language": self._language}, {"name": 1, "_id": 0})
        project_names = sorted([repo.get("name") for repo in repos_cursor if repo.get("name")])
        return project_names

    def detect_tdd_in_commits(self, commits_list) -> Tuple[List[Dict], str]:
        """
        Detect TDD patterns.
        Returns: (list_of_patterns, log_string_for_updates)
        """
        tdd_patterns = []
        updated_hashes = set()
        log_buffer = "" # Accumulate logs here
        
        # Track which commits have been counted as TDD to prevent double-counting
        tdd_commit_hashes = set()

        for i in range(len(commits_list)):
            current = commits_list[i]
            current_hash = current.get("hash")
            
            # Skip if this commit was already counted as TDD
            if current_hash in tdd_commit_hashes:
                continue
            
            # 1) SAME-COMMIT TDD DETECTION
            if self._has_test_and_source_file(current):
                test_files = self._extract_test_filenames(current)
                source_files = self._extract_source_filenames(current)
                num_test = len(test_files)
                num_source = len(source_files)
                percent = 0.0 if num_source == 0 else min(100.0, (num_test / num_source) * 100.0)

                if self._write_to_db:
                    ch = current.get("hash")
                    # Capture log from DB update
                    msg = self._set_tdd_percentage(ch, percent)
                    if msg: log_buffer += msg + "\n"
                    if ch: updated_hashes.add(ch)

                tdd_patterns.append({
                    "test_commit": current.get("hash"),
                    "test_files": test_files,
                    "source_files": source_files,
                    "tdd_percentage": percent,
                    "mode": "same_commit"
                })
                
                # Mark this commit as counted
                if current_hash:
                    tdd_commit_hashes.add(current_hash)
                continue

            # 2) DIFF-COMMIT TDD DETECTION
            if i < len(commits_list) - 1:
                next_commit = commits_list[i + 1]
                next_hash = next_commit.get("hash")

                if (self._has_test_files_only(current) and 
                    self._has_related_source_files(current, next_commit)):
                    
                    test_files = self._extract_test_filenames(current)
                    source_files = self._extract_source_filenames(next_commit)
                    percent = 100.0

                    if self._write_to_db:
                        ch = current.get("hash")
                        nh = next_commit.get("hash")

                        msg1 = self._set_tdd_percentage(ch, percent)
                        msg2 = self._set_tdd_percentage(nh, percent)
                        
                        if msg1: log_buffer += msg1 + "\n"
                        if msg2: log_buffer += msg2 + "\n"

                        if ch: updated_hashes.add(ch)
                        if nh: updated_hashes.add(nh)

                    tdd_patterns.append({
                        "test_commit": current.get("hash"),
                        "source_commit": next_commit.get("hash"),
                        "test_files": test_files,
                        "source_files": source_files,
                        "tdd_percentage": percent,
                        "mode": "diff_commit"
                    })
                    
                    # Mark ONLY the current (test) commit as counted for TDD
                    # The next commit's source files are part of this pattern, but 
                    # if it also has tests, it should still be eligible for its own pattern
                    if current_hash:
                        tdd_commit_hashes.add(current_hash)

        # Mark non-detected commits (if write enabled)
        if self._write_to_db:
            for c in commits_list:
                h = c.get("hash")
                if not h or h in updated_hashes:
                    continue
                try:
                    res = self.commits.update_one(
                        {"hash": h, "tdd_detected": {"$ne": True}}, # Only update if not already True
                        {"$set": {"tdd_percentage": 0.0, "tdd_detected": False}}
                    )
                    if res.modified_count > 0:
                        log_buffer += f"DB mark non-detected for commit {h}\n"
                except Exception as e:
                    log_buffer += f"Error marking commit {h} as non-detected: {e}\n"

        return tdd_patterns, log_buffer

    def _set_tdd_percentage(self, commit_hash: str, percent: float) -> str:
        """
        Helper to update DB. Returns the log string instead of appending to self.output_log.
        """
        if not commit_hash: return ""
        try:
            pct = round(float(percent), 2)
            result = self.commits.update_one(
                {"hash": commit_hash},
                {"$set": {"tdd_percentage": pct, "tdd_detected": True}}
            )
            return f"DB update for {commit_hash}: set tdd_percentage={pct}"
        except Exception as e:
            return f"Error updating commit {commit_hash}: {e}"

    # --- Unchanged Helper Methods (Pure Functions) ---
    def _has_test_files_only(self, commit: Dict) -> bool:
        test_coverage = commit.get("test_coverage", {})
        return len(test_coverage.get("source_files", [])) == 0 and len(test_coverage.get("tested_files", [])) == 0

    def _has_related_source_files(self, test_commit: Dict, source_commit: Dict) -> bool:
        test_entries = self._extract_test_file_entries(test_commit)
        source_entries = self._extract_source_file_entries(source_commit)
        for test_filename, test_methods in test_entries:
            for source_filename, source_methods in source_entries:
                if self._methods_indicate_relation(test_filename, test_methods, source_filename, source_methods):
                    return True
                if self._is_related_file(test_filename, source_filename):
                    return True
        return False

    def _has_test_and_source_file(self, commit: Dict) -> bool:
        test_entries = self._extract_test_file_entries(commit)
        source_entries = self._extract_source_file_entries(commit)
        if not test_entries or not source_entries: return False
        for test_filename, test_methods in test_entries:
            for source_filename, source_methods in source_entries:
                if self._methods_indicate_relation(test_filename, test_methods, source_filename, source_methods):
                    return True
                if self._is_related_file(test_filename, source_filename):
                    return True
        return False

    def _extract_test_filenames(self, test_commit: Dict) -> List[str]:
        return [f.get("filename", "") for f in test_commit.get("test_coverage", {}).get("test_files", []) if f.get("filename")]

    def _extract_source_filenames(self, source_commit: Dict) -> List[str]:
        return [f.get("filename", "") for f in source_commit.get("test_coverage", {}).get("source_files", []) if f.get("filename")]
    
    def _extract_test_file_entries(self, commit: Dict) -> List[Tuple[str, List[str]]]:
        tc = commit.get("test_coverage", {}) or {}
        out = []
        for tf in tc.get("test_files", []) or []:
            if isinstance(tf, dict) and tf.get("filename"):
                out.append((tf["filename"], [m for m in tf.get("changed_methods", []) if m]))
        return out

    def _extract_source_file_entries(self, commit: Dict) -> List[Tuple[str, List[str]]]:
        tc = commit.get("test_coverage", {}) or {}
        out = []
        for sf in tc.get("source_files", []) or []:
            if isinstance(sf, dict) and sf.get("filename"):
                out.append((sf["filename"], [m for m in sf.get("changed_methods", []) if m]))
        return out

    def _is_related_file(self, test_file: str, source_file: str) -> bool:
        test_base = os.path.splitext(os.path.basename(test_file))[0].lower()
        source_base = os.path.splitext(os.path.basename(source_file))[0].lower()
        
        prefixes = ['test_', 'test', 'tests_', 'tests', 'should_', 'should', 'when_', 'when']
        suffixes = ['_test', 'test', '_tests', 'tests', '_spec', 'spec', 'testcase']

        cleaned_test = test_base
        for prefix in prefixes:
            if cleaned_test.startswith(prefix):
                cleaned_test = cleaned_test[len(prefix):]
                break
        for suffix in suffixes:
            if cleaned_test.endswith(suffix):
                cleaned_test = cleaned_test[:-len(suffix)]
                break
        cleaned_test = cleaned_test.strip('_')

        if cleaned_test == source_base or source_base == cleaned_test: return True
        
        test_parts = set(cleaned_test.split('_'))
        camel_parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', test_base)
        test_parts.update([p.lower() for p in camel_parts if len(p) > 2])

        for part in test_parts:
            if part and len(part) > 2 and (part in source_base or source_base in part):
                return True
        if test_base.endswith('it') and test_base[:-2] in source_base: return True
        return False
    
    def _methods_indicate_relation(self, test_f, test_m, source_f, source_m) -> bool:
        if not test_m or not source_m: return False
        t_tok = self._method_tokens(test_m)
        s_tok = self._method_tokens(source_m)
        if not t_tok or not s_tok: return False
        
        # Primary signal: meaningful token intersection
        if t_tok.intersection(s_tok): return True
        
        # Secondary: test tokens reference source basename tokens
        s_base = self._basename_tokens(source_f)
        if s_base and t_tok.intersection(s_base): return True
        
        # Tertiary: normalized test method equals a source method
        normalized_test = [self._normalize_test_method_name(m) for m in test_m]
        normalized_source = set(self._normalize_method_name(m) for m in source_m)
        for tm in normalized_test:
            if tm and tm in normalized_source:
                return True
        
        return False

    @staticmethod
    def _normalize_method_name(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _normalize_test_method_name(name: str) -> str:
        n = name.strip().lower()
        for p in ("test_", "test", "should_", "should", "when_", "when", "given_", "given"):
            if n.startswith(p):
                n = n[len(p):]
                break
        return n.strip("_")

    def _method_tokens(self, methods: List[str]) -> Set[str]:
        tokens = set()
        for m in methods:
            for t in self._split_identifier(m):
                t = t.lower()
                if not self._is_generic_token(t) and len(t) >= 3: tokens.add(t)
        return tokens

    def _basename_tokens(self, filename: str) -> Set[str]:
        base = os.path.splitext(os.path.basename(filename))[0]
        tokens = set()
        for t in self._split_identifier(base):
            t = t.lower()
            if not self._is_generic_token(t) and len(t) >= 3: tokens.add(t)
        return tokens

    @staticmethod
    def _split_identifier(s: str) -> List[str]:
        if not s: return []
        s = s.replace("-", "_")
        parts = re.split(r"[_\W]+", s)
        out = []
        for p in parts:
            if not p: continue
            camel = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|$)|\d+", p)
            out.extend(camel) if camel else out.append(p)
        return out

    @staticmethod
    def _is_generic_token(t: str) -> bool:
        return t in {"test", "tests", "should", "when", "given", "then", "setup", "teardown", "before", "after", "init", "case", "cases", "spec", "it", "run", "runs", "assert", "verify", "check"}

    def get_commits_for_project(self, project_name) -> List[Dict[str, Any]]:
        return list(self.commits.find({"project": project_name}).sort("committer_date", 1))

    def _get_total_commits_for_project(self, project_name: str) -> int:
        repo = self.repos.find_one({"name": project_name})
        return repo.get("commits", 0) if repo else 0

    def set_is_verbose(self, verbose: bool):
        self._isVerbose = verbose

    def log_totals(self):
        """Print the total number of repos and commits stored in the database."""
        analysis_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo_count = self.repos.count_documents({})
        commit_count = self.commits.count_documents({})
        java_repo_count = self.repos.count_documents({"language": "Java"})
        python_repo_count = self.repos.count_documents({"language": "Python"})
        cpp_repo_count = self.repos.count_documents({"language": "C++"})
        self.output_log += f"Analysis Date and Time: {analysis_datetime}\n"
        self.output_log += f"Total repositories: {repo_count}\n"
        self.output_log += f"Total commits: {commit_count}\n"
        self.output_log += f"Total Java repositories: {java_repo_count}\n"
        self.output_log += f"Total Python repositories: {python_repo_count}\n"
        self.output_log += f"Total C++ repositories: {cpp_repo_count}\n"

    def log_final_analysis_results(self):
        """Log comprehensive TDD metrics including average and global rates."""
        num_projects_processed = len(self._tdd_adoption_rate_list)
        
        # Calculation: Average of project percentages
        avg_adoption_rate = (sum(self._tdd_adoption_rate_list) / num_projects_processed) if num_projects_processed > 0 else 0

        # Calculation: Overall Language Adoption
        overall_language_rate = (self._total_tdd_commits_count / self._total_commits_analysed_count * 100) if self._total_commits_analysed_count > 0 else 0

        # Percentage of projects with > 0% TDD
        any_tdd_rate = (self._projects_with_tdd_detected_count / num_projects_processed * 100) if num_projects_processed > 0 else 0
        
        # Percentage of projects with > threshold TDD
        high_tdd_rate = (self._high_tdd_projects_count / num_projects_processed * 100) if num_projects_processed > 0 else 0

        self.final_log += f"\n" + "="*30 + " FINAL RESULTS " + "="*30 + "\n"
        self.final_log += f"Language: {self._language}\n"
        self.final_log += f"Projects Processed: {num_projects_processed} (Sample Cap: {SAMPLE_COUNT})\n"
        self.final_log += "-"*75 + "\n"
        self.final_log += f"Total Commits across all projects: {self._total_commits_analysed_count}\n"
        self.final_log += f"Total TDD Commits identified: {self._total_tdd_commits_count}\n"
        self.final_log += "-"*75 + "\n"
        self.final_log += f"Projects with ANY TDD detected (>0%): {self._projects_with_tdd_detected_count} ({any_tdd_rate:.2f}%)\n"
        self.final_log += f"Projects with TDD adoption > ({HIGH_TDD_THRESHOLD}%): {self._high_tdd_projects_count} ({high_tdd_rate:.2f}%)\n"
        self.final_log += "-"*75 + "\n"
        self.final_log += f"Average TDD Adoption Rate (Mean of project %): {avg_adoption_rate:.2f}%\n"
        self.final_log += f"Overall Language Adoption Rate (Total TDD / Total Commits): {overall_language_rate:.2f}%\n"
        self.final_log += "="*75 + "\n"

        self.output_log += self.final_log

    def print_output_log(self):
        print("\n" + "=" * 80)
        print(self.final_log)
        print("=" * 80)

    def write_output_log(self, filepath: str = STATIC_ANALYSIS_OUTPUT_FILE):
        filepath = filepath.format(self._language)
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w") as f: f.write(self.output_log)
        except IOError as e: print(f"Error writing to file {filepath}: {e}")

# ----------------------------
# CLI
# ----------------------------

def run(choice: str) -> None:
    """Main function to run static analysis based on user choice."""
    
    if choice not in LANGUAGE_MAP:
        print("Invalid selection. Please run the script again and choose 1-4.")
        return

    target_languages = LANGUAGE_MAP[choice]

    for lang in target_languages:
        print(f"\nProcessing {lang} Static Analysis...")
        # Defaults: write_to_db=False, verbose=False for manual runs
        analysis = Static_Analysis(commits, repos, lang, write_to_db=False)
        
        analysis.log_totals()
        analysis.analyze()
        analysis.log_final_analysis_results()
        analysis.print_output_log()
        analysis.write_output_log()
        print(f"Analysis for {lang} Complete! Check analysis-output folder.")

if __name__ == "__main__":
    # Options menu for manual selection
    print("\n--- TDD Static Analysis Tool (Multi-threaded) ---")
    print("1. Java")
    print("2. Python")
    print("3. C++")
    print("4. All Languages")
    
    choice = input("\nSelect a language to analyse (1-4): ").strip()
    run(choice)