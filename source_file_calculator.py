import os
import requests
from urllib.parse import urlparse

from db import get_collection, get_project, update_project

COMMITS_COLLECTION = "mined-commits"
SOURCE_EXTENSIONS = ('.java', '.py', '.cpp')
DEFAULT_TEST_MARKERS = ("test", "tests", "spec", "specs", "_test", "Test")

# Read GitHub token from environment
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def get_all_mined_project_names():
    """
    Returns a set of all project names that have been mined.
    """
    col = get_collection(COMMITS_COLLECTION)
    cursor = col.distinct("project")
    return set(cursor)


def parse_github_url(repo_url: str):
    """
    Extract owner and repo name from a GitHub URL.
    """
    parsed = urlparse(repo_url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid GitHub URL: {repo_url}")
    return parts[0], parts[1].replace(".git", "")


def count_files_github(repo_url: str) -> tuple[int,int,int]:
    """
    Count source files in a GitHub repo using the Trees API.
    """
    owner, repo = parse_github_url(repo_url)

    api = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"

    headers = {
        "Accept": "application/vnd.github+json"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    r = requests.get(api, headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(
            f"GitHub API error {r.status_code} for {repo_url}: {r.text}"
        )

    data = r.json()
    count_production_files = 0
    count_test_files = 0

    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")
        if not path.endswith(SOURCE_EXTENSIONS):
            continue

        # check if file looks like a test
        is_test = any(marker in path for marker in DEFAULT_TEST_MARKERS)

        if is_test:
            count_test_files += 1
        else:
            count_production_files += 1

    return count_production_files, count_test_files, count_test_files+count_production_files


def num_source_files(project_name):
    """
    Returns the total number of source files for a project using GitHub API.
    """
    repo = get_project(project_name)

    if repo is None:
        raise ValueError(f"Project '{project_name}' not found in the database.")

    return count_files_github(repo['repo_url'])

def run_calculator():
    project_names = get_all_mined_project_names()
    print("Mined Projects:", len(project_names))

    for project in project_names:
        try:
            n = num_source_files(project)
            new_project = get_project(project)

            if new_project is None:
                print(f"Skipping {project}: Project details not found in DB.")
                continue

            new_project['num_production_files'] = n[0]
            new_project['num_test_files'] = n[1]
            new_project['num_source_files'] = n[2]
            update_project(project, new_project)
        except Exception as e:
            print(f"Project: {project}, ERROR: {e}")

    print("Done.")

if __name__ == "__main__":
    run_calculator()