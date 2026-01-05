import os
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

import analysis.source_file_calculator as sfc


def test_parse_github_url_valid():
    owner, repo = sfc.parse_github_url("https://github.com/owner/repo.git")
    assert owner == "owner"
    assert repo == "repo"

    owner, repo = sfc.parse_github_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"


def test_parse_github_url_invalid():
    with pytest.raises(ValueError):
        sfc.parse_github_url("https://github.com/owner")  # missing repo part


def test_count_files_github_success_counts(monkeypatch):
    # Prepare fake API response JSON
    fake_tree = [
        {"path": "src/main/java/App.java", "type": "blob"},
        {"path": "tests/test_app.py", "type": "blob"},
        {"path": "README.md", "type": "blob"},
        {"path": "lib/module.cpp", "type": "blob"},
        {"path": "scripts/build.sh", "type": "blob"},
        {"path": "docs/manual.txt", "type": "blob"},
    ]
    fake_json = {"tree": fake_tree}

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = fake_json

    calls = {}

    def fake_get(url, headers=None, timeout=None):
        # capture the call for assertion
        calls['url'] = url
        calls['headers'] = headers
        calls['timeout'] = timeout
        return fake_response

    monkeypatch.setattr(sfc, "GITHUB_TOKEN", None)
    monkeypatch.setattr(sfc.requests, "get", fake_get)

    prod, tests, total = sfc.count_files_github("https://github.com/owner/repo")
    assert prod == 2  # App.java and module.cpp
    assert tests == 1  # tests/test_app.py
    assert total == 3
    assert "git/trees/HEAD?recursive=1" in calls['url']
    assert calls['timeout'] == 30


def test_count_files_github_uses_token_header(monkeypatch):
    # Ensure Authorization header included when GITHUB_TOKEN present
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"tree": []}

    monkeypatch.setenv("GITHUB_TOKEN", "mytoken")
    # update module-level variable if already loaded
    monkeypatch.setattr(sfc, "GITHUB_TOKEN", "mytoken")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured['headers'] = headers
        return fake_response

    monkeypatch.setattr(sfc.requests, "get", fake_get)

    sfc.count_files_github("https://github.com/owner/repo")
    assert captured['headers'] is not None
    assert captured['headers'].get("Authorization") == "Bearer mytoken"


def test_count_files_github_non_200_raises(monkeypatch):
    fake_response = MagicMock()
    fake_response.status_code = 404
    fake_response.text = "not found"

    monkeypatch.setattr(sfc.requests, "get", lambda *a, **k: fake_response)

    with pytest.raises(RuntimeError) as exc:
        sfc.count_files_github("https://github.com/owner/repo")
    assert "GitHub API error 404" in str(exc.value)


def test_get_all_mined_project_names(monkeypatch):
    # Mock get_collection to return an object with distinct method
    fake_col = SimpleNamespace(distinct=lambda key: ["projA", "projB", "projA"])
    monkeypatch.setattr(sfc, "get_collection", lambda name: fake_col)

    names = sfc.get_all_mined_project_names()
    assert isinstance(names, set)
    assert names == {"projA", "projB"}


def test_num_source_files_calls_count_and_update(monkeypatch):
    # Patch get_project to return repo_url, and count_files_github to a known tuple
    monkeypatch.setattr(sfc, "get_project", lambda name: {"repo_url": "https://github.com/owner/repo.git"})
    monkeypatch.setattr(sfc, "count_files_github", lambda url: (5, 2, 7))

    result = sfc.num_source_files("some-project")
    assert result == (5, 2, 7)


def test_integration_main_update_project(monkeypatch):
    """
    Simulate running __main__ style flow for a single project in DB.
    Patch get_all_mined_project_names, get_project, count_files_github and update_project.
    """
    monkeypatch.setattr(sfc, "get_all_mined_project_names", lambda: {"projX"})
    monkeypatch.setattr(sfc, "get_project", lambda name: {"repo_url": "https://github.com/owner/repo.git"})
    monkeypatch.setattr(sfc, "count_files_github", lambda url: (10, 3, 13))

    updated = {}

    def fake_update_project(name, project_obj):
        updated['name'] = name
        updated['project'] = project_obj

    monkeypatch.setattr(sfc, "update_project", fake_update_project)

    # Run the loop body similarly to __main__
    for project in sfc.get_all_mined_project_names():
        n = sfc.num_source_files(project)
        new_project = sfc.get_project(project)

        if new_project is None:
                print(f"Skipping {project}: Project details not found in DB.")
                continue

        new_project['num_production_files'] = n[0]
        new_project['num_test_files'] = n[1]
        new_project['num_source_files'] = n[2]
        sfc.update_project(project, new_project)

    assert updated['name'] == "projX"
    assert updated['project']['num_production_files'] == 10
    assert updated['project']['num_test_files'] == 3
    assert updated['project']['num_source_files'] == 13