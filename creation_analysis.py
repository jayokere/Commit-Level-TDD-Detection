from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from static_analysis import Static_Analysis, JAVA, PYTHON, CPP  # uses your existing heuristics
from db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION


@dataclass(frozen=True)
class ProjectCounts:
    project: str
    paired: int
    before: int
    same: int
    after: int
    note: str = ""  # e.g., "no_commits", "no_tests", "no_sources", "no_pairs"


@dataclass(frozen=True)
class Totals:
    before: int = 0
    same: int = 0
    after: int = 0
    paired_total: int = 0


class creation_analysis(Static_Analysis):
    """
    Language-level aggregation only, TXT output only.

    Counts are based on FIRST-SEEN timestamps per filename:
    - each test file contributes at most 1 paired comparison
    - each test file is paired to at most 1 best-matching source file (via _is_related_file)
    """

    def __init__(self, commits_collection, repos_collection, language: str):
        super().__init__(commits_collection, repos_collection, language, write_to_db=False)

    def run(self) -> Totals:
        projects = self._get_project_names()

        per_project: List[ProjectCounts] = []
        totals = Totals()

        # Verification counters (helps you sanity-check)
        zero_commit_projects = 0
        no_test_projects = 0
        no_source_projects = 0
        no_pair_projects = 0

        for idx, project in enumerate(projects, start=1):
            commits = self.get_commits_for_project(project)

            if not commits:
                zero_commit_projects += 1
                pc = ProjectCounts(project=project, paired=0, before=0, same=0, after=0, note="no_commits")
                per_project.append(pc)
                self._print_progress(idx, len(projects), pc)
                continue

            b, s, a, p, note = self._analyze_project_counts(commits)

            if note == "no_tests":
                no_test_projects += 1
            elif note == "no_sources":
                no_source_projects += 1
            elif note == "no_pairs":
                no_pair_projects += 1

            # accumulate
            totals = Totals(
                before=totals.before + b,
                same=totals.same + s,
                after=totals.after + a,
                paired_total=totals.paired_total + p,
            )

            pc = ProjectCounts(project=project, paired=p, before=b, same=s, after=a, note=note)
            per_project.append(pc)
            self._print_progress(idx, len(projects), pc)

        # write one TXT per language with audit info
        self._write_auditable_txt(
            totals=totals,
            per_project=per_project,
            meta={
                "projects_total": len(projects),
                "projects_no_commits": zero_commit_projects,
                "projects_no_tests": no_test_projects,
                "projects_no_sources": no_source_projects,
                "projects_no_pairs": no_pair_projects,
            },
        )

        print("Timing Analysis Complete! Check analysis-output/.")
        return totals

    def _print_progress(self, idx: int, total: int, pc: ProjectCounts) -> None:
        # Console feedback for verification while scanning
        msg = (
            f"\r[{idx}/{total}] {pc.project} -> "
            f"paired={pc.paired} before={pc.before} same={pc.same} after={pc.after}"
        )
        if pc.note:
            msg += f" ({pc.note})"
        print(msg, end="", flush=True)
        if idx == total:
            print()  # newline

    def _analyze_project_counts(self, commits: List[Dict[str, Any]]) -> Tuple[int, int, int, int, str]:
        first_seen_test = self._first_seen_map(commits, file_kind="test")
        first_seen_source = self._first_seen_map(commits, file_kind="source")

        if not first_seen_test:
            return 0, 0, 0, 0, "no_tests"
        if not first_seen_source:
            return 0, 0, 0, 0, "no_sources"

        tests = sorted(first_seen_test.keys())
        sources = sorted(first_seen_source.keys())

        before = same = after = paired_total = 0

        for t in tests:
            s = self._best_source_match(t, sources)
            if not s:
                continue

            t_ts = first_seen_test[t]
            s_ts = first_seen_source[s]

            if t_ts < s_ts:
                before += 1
            elif t_ts > s_ts:
                after += 1
            else:
                same += 1

            paired_total += 1

        if paired_total == 0:
            return 0, 0, 0, 0, "no_pairs"

        return before, same, after, paired_total, ""

    def _first_seen_map(self, commits: List[Dict[str, Any]], file_kind: str) -> Dict[str, datetime]:
        out: Dict[str, datetime] = {}

        for c in commits:
            ts = self._parse_commit_time(c.get("committer_date"))
            if ts is None:
                continue

            if file_kind == "test":
                filenames = self._extract_test_filenames(c)
            elif file_kind == "source":
                filenames = self._extract_source_filenames(c)
            else:
                raise ValueError(f"Invalid file_kind: {file_kind}")

            for fn in filenames:
                if not fn:
                    continue
                if fn not in out or ts < out[fn]:
                    out[fn] = ts

        return out

    def _best_source_match(self, test_file: str, source_files: List[str]) -> Optional[str]:
        matches = [s for s in source_files if self._is_related_file(test_file, s)]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]

        def key_fn(s: str) -> Tuple[int, int, str]:
            tb = os.path.splitext(os.path.basename(test_file))[0]
            sb = os.path.splitext(os.path.basename(s))[0]
            return (abs(len(tb) - len(sb)), len(sb), s)

        matches.sort(key=key_fn)
        return matches[0]

    @staticmethod
    def _parse_commit_time(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            v = value.strip()
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v, fmt)
                except Exception:
                    continue
        return None

    def _write_auditable_txt(self, totals: Totals, per_project: List[ProjectCounts], meta: Dict[str, int]) -> None:
        out_dir = "analysis-output"
        os.makedirs(out_dir, exist_ok=True)

        path = os.path.join(out_dir, f"{self._language}_test_source_timing_audit.txt")

        total = totals.paired_total
        before = totals.before
        same = totals.same
        after = totals.after

        # Sort to make anomalies pop (highest paired first; then name)
        per_project_sorted = sorted(per_project, key=lambda p: (-p.paired, p.project))

        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Language: {self._language}\n")
            f.write("=== Overall counts (paired test->source) ===\n")
            f.write(f"paired_total: {total}\n")
            f.write(f"before: {before}\n")
            f.write(f"same:   {same}\n")
            f.write(f"after:  {after}\n")
            if total > 0:
                f.write("\n=== Overall percentages ===\n")
                f.write(f"before_pct: {before / total * 100:.4f}%\n")
                f.write(f"same_pct:   {same / total * 100:.4f}%\n")
                f.write(f"after_pct:  {after / total * 100:.4f}%\n")

            f.write("\n=== Project coverage / sanity ===\n")
            for k in ["projects_total", "projects_no_commits", "projects_no_tests", "projects_no_sources", "projects_no_pairs"]:
                f.write(f"{k}: {meta.get(k, 0)}\n")

            f.write("\n=== Per-project breakdown ===\n")
            f.write("project\tpaired\tbefore\tsame\tafter\tnote\n")
            for p in per_project_sorted:
                f.write(f"{p.project}\t{p.paired}\t{p.before}\t{p.same}\t{p.after}\t{p.note}\n")

            f.write("\n=== Quick verification identities ===\n")
            f.write("Invariant 1: before + same + after == paired_total\n")
            f.write(f"Computed: {before} + {same} + {after} = {before + same + after}\n")
            f.write(f"paired_total: {total}\n")

        print(f"Wrote audit TXT: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count whether test files appear before/same/after related source files (TXT audit only)."
    )
    parser.add_argument(
        "-l",
        "--language",
        type=str,
        choices=[JAVA, PYTHON, CPP],
        required=True,
        help='Programming language to analyze ("Java", "Python", or "C++")',
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    commits = get_collection(COMMIT_COLLECTION)
    repos = get_collection(REPO_COLLECTION)

    analysis = creation_analysis(commits_collection=commits, repos_collection=repos, language=args.language)
    analysis.set_is_verbose(args.verbose)
    analysis.run()


if __name__ == "__main__":
    main()
