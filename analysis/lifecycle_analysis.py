"""
Lifecycle Analysis for TDD Adoption.
Analyzes how TDD patterns change across different stages of a project's maturity.
"""
from analysis.static_analysis import Static_Analysis, JAVA, PYTHON, CPP
from database.db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION
from pymongo.errors import PyMongoError
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import os

# Constants for lifecycle analysis
NUM_STAGES = 4  # Divide lifecycle into Quartiles (25% chunks)
LIFECYCLE_OUTPUT_FILE = "analysis-output/{}_lifecycle_analysis.txt"
MAX_THREADS = 60

class LifecycleAnalysis(Static_Analysis):
    """Extension of Static_Analysis to track TDD evolution over time."""

    def __init__(self, commits_collection, repos_collection, language: str):
        super().__init__(commits_collection, repos_collection, language, write_to_db=False)
        # Track sums and counts to calculate averages per stage
        self.stage_adoption_sums = {i + 1: 0.0 for i in range(NUM_STAGES)}
        self.stage_project_counts = {i + 1: 0 for i in range(NUM_STAGES)}
        self.lifecycle_log = ""

    def _get_commit_metadata(self, project_name):
        """
        Pass 1: Fetch ONLY _id and date. 
        This prevents timeouts by avoiding downloading heavy diffs/messages.
        """
        try:
            cursor = self.commits.find(
                {"project": project_name}, 
                {"_id": 1, "committer_date": 1}
            )
            meta = list(cursor)
            # Sort by date locally
            meta.sort(key=lambda x: str(x.get("committer_date", "")))
            return meta
        except PyMongoError as e:
            print(f"(!) DB Error fetching metadata for {project_name}: {e}")
            return []

    def _fetch_commits_by_ids(self, commit_ids):
        """
        Pass 2: Fetch full data for a specific list of IDs.
        """
        if not commit_ids:
            return []
        
        try:
            cursor = self.commits.find({"_id": {"$in": commit_ids}})
            commits_map = {doc["_id"]: doc for doc in cursor}
            
            ordered_commits = []
            for cid in commit_ids:
                if cid in commits_map:
                    ordered_commits.append(commits_map[cid])
            return ordered_commits
        except PyMongoError:
            return []

    def process_single_project(self, name):
        """
        Worker function to process a single project in a thread.
        Returns a tuple: (formatted_log_row, list_of_stage_stats) or None.
        """
        # 1. Light fetch (IDs only)
        commit_meta = self._get_commit_metadata(name)
        total_count = len(commit_meta)

        # Skip projects too small to divide into stages
        if total_count < NUM_STAGES:
            return None

        # Divide the project history into 4 chunks based on metadata
        stage_size = math.ceil(total_count / NUM_STAGES)
        project_row = f"{name[:40]:<40}"
        
        # Store stats temporarily for this project [(rate, 1), (rate, 1)...]
        project_stats = []

        for i in range(NUM_STAGES):
            start = i * stage_size
            end = min((i + 1) * stage_size, total_count)
            
            # Identify IDs for this stage
            stage_meta = commit_meta[start:end]
            stage_ids = [m["_id"] for m in stage_meta]

            if not stage_ids:
                project_row += " |  N/A    "
                project_stats.append((0.0, 0)) # No data for this stage
                continue

            # 2. Heavy fetch (Full data only for this stage)
            stage_commits = self._fetch_commits_by_ids(stage_ids)

            # Detect TDD patterns
            tdd_patterns = self.detect_tdd_in_commits(stage_commits)
            if len(stage_commits) > 0:
                stage_rate = (len(tdd_patterns) / len(stage_commits)) * 100
            else:
                stage_rate = 0.0

            project_stats.append((stage_rate, 1)) # 1 indicates valid project count
            project_row += f" | {stage_rate:7.2f}%"

        return (project_row, project_stats)

    def run_lifecycle_study(self, sample_limit=60):
        """Processes projects using multi-threading."""
        all_project_names = self._get_project_names()
        project_names = all_project_names[:sample_limit]
        
        self.lifecycle_log += f"Starting Lifecycle Analysis for {self._language}\n"
        self.lifecycle_log += f"Defining maturity by commit quartiles (Stage 1-4)\n"
        self.lifecycle_log += f"Sample size: {len(project_names)} projects\n"
        self.lifecycle_log += "=" * 90 + "\n"
        self.lifecycle_log += f"{'Project Name':<40} | Stage 1  | Stage 2  | Stage 3  | Stage 4\n"
        self.lifecycle_log += "-" * 90 + "\n"

        # Multi-threading execution
        # max_workers=5 is conservative to avoid overwhelming the Atlas connection pool
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            # Submit all tasks
            future_to_name = {executor.submit(self.process_single_project, name): name for name in project_names}
            
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result = future.result()
                    if result:
                        row_str, stats = result
                        self.lifecycle_log += row_str + "\n"
                        
                        # Aggregate stats into the shared class dictionary
                        # This part runs sequentially in the main thread, so it is thread-safe
                        for i, (rate, count) in enumerate(stats):
                            if count > 0:
                                self.stage_adoption_sums[i + 1] += rate
                                self.stage_project_counts[i + 1] += 1
                                
                except Exception as exc:
                    print(f"(!) Thread exception for '{name}': {exc}")

        self._generate_lifecycle_summary()

    def _generate_lifecycle_summary(self):
        """Computes final averages and concludes if TDD diminishes."""
        self.lifecycle_log += "\n" + "=" * 30 + " FINAL LIFECYCLE TREND " + "=" * 30 + "\n"
        self.lifecycle_log += f"{'Stage (Maturity)':<35} | {'Average TDD Adoption':<25}\n"
        self.lifecycle_log += "-" * 80 + "\n"

        stages = [
            "Stage 1 (Inception 0-25%)", 
            "Stage 2 (Growth 25-50%)", 
            "Stage 3 (Maturity 50-75%)", 
            "Stage 4 (Maintenance 75-100%)"
        ]
        
        results = []
        for i, stage_name in enumerate(stages):
            stage_num = i + 1
            count = self.stage_project_counts[stage_num]
            avg = (self.stage_adoption_sums[stage_num] / count) if count > 0 else 0
            results.append(avg)
            self.lifecycle_log += f"{stage_name:<35} | {avg:.2f}%\n"

        self.lifecycle_log += "-" * 80 + "\n"
        
        # Trend Conclusion Logic comparing S1 to S4
        if len(results) >= 4:
            s1, s4 = results[0], results[3]
            if s1 > 0:
                if s4 < s1 * 0.8:
                    self.lifecycle_log += "CONCLUSION: TDD adoption DIMINISHES significantly as the codebase matures.\n"
                elif s4 > s1 * 1.2:
                    self.lifecycle_log += "CONCLUSION: TDD adoption INCREASES as the codebase matures.\n"
                else:
                    self.lifecycle_log += "CONCLUSION: TDD adoption remains CONSISTENT throughout the lifecycle.\n"
            else:
                self.lifecycle_log += "CONCLUSION: Insufficient TDD data in Stage 1 to determine a trend.\n"

    def write_lifecycle_log(self):
        """Saves the log to a language-specific file."""
        path = LIFECYCLE_OUTPUT_FILE.format(self._language)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(self.lifecycle_log)
        print(f"\nAnalysis complete. Results saved to: {path}")

def run(choice: str):
    """Main function to run lifecycle analysis based on user choice."""
    # Map inputs to a list of languages to process
    language_map = {
        "1": [JAVA], 
        "2": [PYTHON], 
        "3": [CPP],
        "4": [JAVA, PYTHON, CPP]
    }
    
    if choice not in language_map:
        print("Invalid selection. Please run the script again and choose 1-4.")
        return

    target_languages = language_map[choice]

    # Database setup
    commits_col = get_collection(COMMIT_COLLECTION)
    repos_col = get_collection(REPO_COLLECTION)
    
    for lang in target_languages:
        print(f"\nProcessing {lang} with {MAX_THREADS} threads...")
        analyzer = LifecycleAnalysis(commits_col, repos_col, lang)
        analyzer.run_lifecycle_study(sample_limit=60)
        
        # Print summary to console and write to file
        print(analyzer.lifecycle_log)
        analyzer.write_lifecycle_log()

if __name__ == "__main__":
    # Options menu for manual selection
    print("\n--- TDD Lifecycle Analysis Tool (Multi-threaded) ---")
    print("1. Java")
    print("2. Python")
    print("3. C++")
    print("4. All Languages")
    
    choice = input("\nSelect a language to analyse (1-4): ").strip()

    run(choice)