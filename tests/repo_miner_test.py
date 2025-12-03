import datetime
import repo_miner
from repo_miner import Repo_miner


class FakeModifiedFile:
    def __init__(self, filename, diff):
        self.filename = filename
        self.diff = diff

class FakeCommit:
    def __init__(self, hash_, committer_date, modified_files, dmm_unit_size=0):
        self.hash = hash_
        self.committer_date = committer_date
        self.modified_files = modified_files
        self.dmm_unit_size = dmm_unit_size

class FakeRepo:
    def __init__(self, repo_url, single=None):
        self.repo_url = repo_url
        self.single = single
        # will be set by tests by assigning .commits
        self.commits = []

    def traverse_commits(self):
        return list(self.commits)

def test_mine_repo_returns_expected_structure(monkeypatch):
    # Prepare fake commits
    c1 = FakeCommit(
        hash_="abc123",
        committer_date=datetime.datetime(2021, 1, 1, 12, 0, 0),
        modified_files=[FakeModifiedFile("foo.txt", "diff-1")],
        dmm_unit_size=7,
    )
    c2 = FakeCommit(
        hash_="def456",
        committer_date=datetime.datetime(2021, 1, 2, 13, 30, 0),
        modified_files=[FakeModifiedFile("bar.py", "diff-2"), FakeModifiedFile("baz.md", "diff-3")],
        dmm_unit_size=3,
    )

    fake_repo = FakeRepo("https://example.com/repo.git", single='1bdad6c')
    fake_repo.commits = [c1, c2]

    # Patch the Repository used inside the repo_miner module
    monkeypatch.setattr(repo_miner, "Repository", lambda repo_url, single=None: fake_repo)

    result = Repo_miner.mine_repo("https://example.com/repo.git")

    assert isinstance(result, list)
    assert len(result) == 2

    first = result[0]
    assert first["hash"] == "abc123"
    assert first["date"] == "2021-01-01 12:00:00"
    assert first["files_changed"] == {"foo.txt": "diff-1"}
    assert first["size"] == 7

    second = result[1]
    assert second["hash"] == "def456"
    assert second["date"] == "2021-01-02 13:30:00"
    # files_changed should map filenames to diffs
    assert second["files_changed"] == {"bar.py": "diff-2", "baz.md": "diff-3"}
    assert second["size"] == 3

def test_mine_repo_handles_no_modified_files(monkeypatch):
    c = FakeCommit(
        hash_="nochange",
        committer_date=datetime.datetime(2022, 6, 1, 8, 0, 0),
        modified_files=[],
        dmm_unit_size=0,
    )
    fake_repo = FakeRepo("local/path", single='1bdad6c')
    fake_repo.commits = [c]

    monkeypatch.setattr(repo_miner, "Repository", lambda repo_url, single=None: fake_repo)

    result = Repo_miner.mine_repo("local/path")

    assert len(result) == 1
    entry = result[0]
    assert entry["hash"] == "nochange"
    assert entry["files_changed"] == {}
    assert entry["date"] == "2022-06-01 08:00:00"