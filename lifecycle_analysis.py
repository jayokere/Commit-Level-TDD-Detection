"""
Lifecycle Analysis for TDD Adoption.
Analyzes how TDD patterns change across different stages of a project's maturity.
"""
from static_analysis import Static_Analysis, JAVA, PYTHON, CPP
from db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION
from pymongo.errors import PyMongoError
import math
import os

# Constants for lifecycle analysis
NUM_STAGES = 4  # Divide lifecycle into Quartiles (25% chunks)
LIFECYCLE_OUTPUT_FILE = "analysis-output/{}_lifecycle_analysis.txt"

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
        This prevents timeouts by avoiding downloading heavy diffs/messages for the whole history at once.
        """
        # Projection: 1 = include, 0 = exclude
        cursor = self.commits.find(
            {"project": project_name}, 
            {"_id": 1, "committer_date": 1}
        )
        
        # Load lightweight metadata into memory
        meta = list(cursor)
        
        # Sort by date locally
        meta.sort(key=lambda x: str(x.get("committer_date", "")))
        return meta

    def _fetch_commits_by_ids(self, commit_ids):
        """
        Pass 2: Fetch full data for a specific list of IDs (one stage at a time).
        """
        if not commit_ids:
            return []
            
        # Fetch the full documents for these IDs
        # We assume the list of IDs is relatively small (one stage of one project)
        cursor = self.commits.find({"_id": {"$in": commit_ids}})
        
        # Map IDs to documents to restore sorted order (since $in returns arbitrary order)
        commits_map = {doc["_id"]: doc for doc in cursor}
        
        ordered_commits = []
        for cid in commit_ids:
            if cid in commits_map:
                ordered_commits.append(commits_map[cid])
                
        return ordered_commits

    def run_lifecycle_study(self, sample_limit=60):
        """Processes projects and calculates TDD adoption per lifecycle stage."""
        all_project_names = self._get_project_names()
        project_names = all_project_names[:sample_limit]
        
        self.lifecycle_log += f"Starting Lifecycle Analysis for {self._language}\n"
        self.lifecycle_log += f"Defining maturity by commit quartiles (Stage 1-4)\n"
        self.lifecycle_log += f"Sample size: {len(project_names)} projects\n"
        self.lifecycle_log += "=" * 90 + "\n"
        self.lifecycle_log += f"{'Project Name':<40} | Stage 1  | Stage 2  | Stage 3  | Stage 4\n"
        self.lifecycle_log += "-" * 90 + "\n"

        for name in project_names:
            try:
                # 1. Light fetch (IDs only) - Fast & Low Memory
                commit_meta = self._get_commit_metadata(name)
                total_count = len(commit_meta)

                # Skip projects too small to divide into stages
                if total_count < NUM_STAGES:
                    continue

                # Divide the project history into 4 chunks based on metadata
                stage_size = math.ceil(total_count / NUM_STAGES)
                project_row = f"{name[:40]:<40}"
                
                for i in range(NUM_STAGES):
                    start = i * stage_size
                    end = min((i + 1) * stage_size, total_count)
                    
                    # Identify IDs for this stage
                    stage_meta = commit_meta[start:end]
                    stage_ids = [m["_id"] for m in stage_meta]

                    if not stage_ids:
                        project_row += " |  N/A    "
                        continue

                    # 2. Heavy fetch (Full data only for this stage) - Safe
                    stage_commits = self._fetch_commits_by_ids(stage_ids)

                    # Detect TDD patterns
                    tdd_patterns = self.detect_tdd_in_commits(stage_commits)
                    stage_rate = (len(tdd_patterns) / len(stage_commits)) * 100
                    
                    self.stage_adoption_sums[i + 1] += stage_rate
                    self.stage_project_counts[i + 1] += 1
                    project_row += f" | {stage_rate:7.2f}%"

                self.lifecycle_log += project_row + "\n"
                
            except PyMongoError as e:
                print(f"(!) Timeout or DB error processing '{name}': {e}. Skipping.")
                continue

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

def main():
    # Options menu for manual selection
    print("\n--- TDD Lifecycle Analysis Tool ---")
    print("1. Java")
    print("2. Python")
    print("3. C++")
    print("4. All Languages")
    
    choice = input("\nSelect a language to analyse (1-4): ").strip()
    
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
        print(f"\nProcessing {lang}...")
        analyzer = LifecycleAnalysis(commits_col, repos_col, lang)
        analyzer.run_lifecycle_study(sample_limit=60)
        
        # Print summary to console and write to file
        print(analyzer.lifecycle_log)
        analyzer.write_lifecycle_log()

if __name__ == "__main__":
    main()