"""
creation_analysis.py

Language-level timing analysis: counts how many TEST FILES were first created
BEFORE / SAME TIME / AFTER their associated SOURCE FILE.

Association strategy for each test file:
  A) Name-based: Static_Analysis._is_related_file(test_file, source_file)
  B) Method-based: compare test_coverage.test_files[].changed_methods against
                   test_coverage.source_files[].changed_methods, using token overlap
                   and a few safe heuristics.

Output:
- analysis-output/<Language>_test_source_timing_audit.txt

Run:
  python creation_analysis.py -l Java
  python creation_analysis.py -l Python
  python creation_analysis.py -l C++
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION
from static_analysis import Static_Analysis, JAVA, PYTHON, CPP


# ----------------------------
# Data containers
# ----------------------------

@dataclass(frozen=True)
class ProjectCounts:
    project: str
    paired: int
    before: int
    same: int
    after: int
    paired_by_methods: int
    paired_by_name: int
    note: str = ""  # "no_commits" | "no_tests" | "no_sources" | "no_pairs"


@dataclass(frozen=True)
class Totals:
    before: int = 0
    same: int = 0
    after: int = 0
    paired_total: int = 0
    paired_by_methods: int = 0
    paired_by_name: int = 0


# ----------------------------
# Analysis
# ----------------------------

class creation_analysis(Static_Analysis):
    """
    Counts whether test files were introduced before/same/after their associated source files.

    Associations are determined per test file using:
      - Name heuristic (_is_related_file)
      - Method heuristic (changed_methods overlap between test and source)
    """

    def __init__(self, commits_collection, repos_collection, language: str):
        super().__init__(commits_collection, repos_collection, language, write_to_db=False)

    def run(self) -> Totals:
        projects = self._get_project_names()

        per_project: List[ProjectCounts] = []
        totals = Totals()

        # Sanity counters
        zero_commit_projects = 0
        no_test_projects = 0
        no_source_projects = 0
        no_pair_projects = 0

        for idx, project in enumerate(projects, start=1):
            commits = self.get_commits_for_project(project)

            if not commits:
                zero_commit_projects += 1
                pc = ProjectCounts(
                    project=project, paired=0, before=0, same=0, after=0,
                    paired_by_methods=0, paired_by_name=0,
                    note="no_commits",
                )
                per_project.append(pc)
                self._print_progress(idx, len(projects), pc)
                continue

            b, s, a, p, by_methods, by_name, note = self._analyze_project_counts(commits)

            if note == "no_tests":
                no_test_projects += 1
            elif note == "no_sources":
                no_source_projects += 1
            elif note == "no_pairs":
                no_pair_projects += 1

            totals = Totals(
                before=totals.before + b,
                same=totals.same + s,
                after=totals.after + a,
                paired_total=totals.paired_total + p,
                paired_by_methods=totals.paired_by_methods + by_methods,
                paired_by_name=totals.paired_by_name + by_name,
            )

            pc = ProjectCounts(
                project=project,
                paired=p, before=b, same=s, after=a,
                paired_by_methods=by_methods,
                paired_by_name=by_name,
                note=note,
            )
            per_project.append(pc)
            self._print_progress(idx, len(projects), pc)

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

    # ----------------------------
    # Core analysis
    # ----------------------------

    def _analyze_project_counts(
        self,
        commits: List[Dict[str, Any]]
    ) -> Tuple[int, int, int, int, int, int, str]:
        """
        Returns:
          before, same, after, paired_total, paired_by_methods, paired_by_name, note
        """
        first_seen_test = self._first_seen_map(commits, file_kind="test")
        first_seen_source = self._first_seen_map(commits, file_kind="source")

        if not first_seen_test:
            return 0, 0, 0, 0, 0, 0, "no_tests"
        if not first_seen_source:
            return 0, 0, 0, 0, 0, 0, "no_sources"

        tests = sorted(first_seen_test.keys())
        sources = sorted(first_seen_source.keys())

        # Build candidates using BOTH name + changed_methods (per-commit)
        candidates_map, provenance_map = self._build_candidates_from_names_and_methods(commits)

        before = same = after = paired_total = 0
        paired_by_methods = 0
        paired_by_name = 0

        for t in tests:
            candidates = candidates_map.get(t, set())
            # keep only candidates that exist in this project (have first-seen timestamps)
            candidates = [s for s in candidates if s in first_seen_source]

            used_methods = False
            used_name = False

            if candidates:
                # Prefer method-derived candidates if any exist for this test
                # (provenance_map tracks whether each candidate was added by methods or name)
                method_candidates = [s for s in candidates if provenance_map.get((t, s)) == "methods"]
                if method_candidates:
                    used_methods = True
                    sfile = self._best_source_match(t, sorted(method_candidates))
                    if not sfile:
                        # fallback to any candidates (name-derived)
                        used_methods = False
                        used_name = True
                        sfile = self._best_source_match(t, sorted(candidates))
                else:
                    used_name = True
                    sfile = self._best_source_match(t, sorted(candidates))
            else:
                # fallback: scan all sources by name heuristic (original behaviour)
                used_name = True
                sfile = self._best_source_match(t, sources)

            if not sfile:
                continue

            t_ts = first_seen_test[t]
            s_ts = first_seen_source[sfile]

            if t_ts < s_ts:
                before += 1
            elif t_ts > s_ts:
                after += 1
            else:
                same += 1

            paired_total += 1
            if used_methods:
                paired_by_methods += 1
            elif used_name:
                paired_by_name += 1

        if paired_total == 0:
            return 0, 0, 0, 0, 0, 0, "no_pairs"

        return before, same, after, paired_total, paired_by_methods, paired_by_name, ""

    def _first_seen_map(self, commits: List[Dict[str, Any]], file_kind: str) -> Dict[str, datetime]:
        """
        Map filename -> earliest committer_date where it appears.
        file_kind: "test" or "source"
        """
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

    # ----------------------------
    # Candidate generation: name + methods
    # ----------------------------

    def _build_candidates_from_names_and_methods(
        self,
        commits: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, str], str]]:
        """
        Returns:
          candidates_map: test_file -> set(source_file candidates)
          provenance_map: (test_file, source_file) -> "methods" | "name"

        We build candidates by looking at each commit's test_coverage and:
          - If a test file and a source file are name-related -> candidate ("name")
          - If their changed_methods look related -> candidate ("methods")
        """
        candidates: Dict[str, Set[str]] = defaultdict(set)
        provenance: Dict[Tuple[str, str], str] = {}

        for c in commits:
            tc = c.get("test_coverage", {}) or {}
            test_files_info = tc.get("test_files", []) or []
            source_files_info = tc.get("source_files", []) or []

            if not test_files_info or not source_files_info:
                continue

            # Build per-test-file method lists
            test_entries: List[Tuple[str, List[str]]] = []
            for tf in test_files_info:
                tfn = (tf or {}).get("filename", "")
                if not tfn:
                    continue
                tmethods = (tf or {}).get("changed_methods", []) or []
                tmethods = [m for m in tmethods if isinstance(m, str) and m]
                test_entries.append((tfn, tmethods))

            # Build per-source-file method lists
            source_entries: List[Tuple[str, List[str]]] = []
            for sf in source_files_info:
                sfn = (sf or {}).get("filename", "")
                if not sfn:
                    continue
                smethods = (sf or {}).get("changed_methods", []) or []
                smethods = [m for m in smethods if isinstance(m, str) and m]
                source_entries.append((sfn, smethods))

            if not test_entries or not source_entries:
                continue

            for (tfn, tmethods) in test_entries:
                for (sfn, smethods) in source_entries:
                    # (A) Method-based relation
                    if self._methods_indicate_relation(tfn, tmethods, sfn, smethods):
                        candidates[tfn].add(sfn)
                        provenance[(tfn, sfn)] = "methods"
                        continue  # method evidence is strongest

                    # (B) Name-based relation
                    if self._is_related_file(tfn, sfn):
                        candidates[tfn].add(sfn)
                        # only set provenance if not already set by methods
                        provenance.setdefault((tfn, sfn), "name")

        return dict(candidates), provenance

    def _methods_indicate_relation(
        self,
        test_filename: str,
        test_methods: List[str],
        source_filename: str,
        source_methods: List[str],
    ) -> bool:
        """
        Heuristic method-level matching using changed_methods lists.

        Returns True if there is meaningful token overlap between test method names and
        source method names, or if test method names strongly reference the source file basename.

        Safe rules (avoid false positives):
          - ignore very short tokens (<3)
          - ignore generic test tokens (test, tests, should, when, given, then, setup, teardown, etc.)
          - require at least one overlapping "significant token"
        """
        if not test_methods or not source_methods:
            return False

        test_tokens = self._method_tokens(test_methods)
        if not test_tokens:
            return False

        source_tokens = self._method_tokens(source_methods)
        if not source_tokens:
            return False

        # Primary signal: token intersection
        if test_tokens.intersection(source_tokens):
            return True

        # Secondary signal: test tokens reference the source basename tokens
        source_base_tokens = self._basename_tokens(source_filename)
        if source_base_tokens and test_tokens.intersection(source_base_tokens):
            return True

        # Also allow direct "test_<sourceMethod>" style where full source method name appears
        # after stripping common prefixes from test method names.
        normalized_test_methods = [self._normalize_test_method_name(m) for m in test_methods]
        source_method_set = set(self._normalize_method_name(m) for m in source_methods)
        for tm in normalized_test_methods:
            if tm in source_method_set:
                return True

        return False

    @staticmethod
    def _normalize_method_name(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _normalize_test_method_name(name: str) -> str:
        n = name.strip().lower()
        # strip common prefixes
        for p in ("test_", "test", "should_", "should", "when_", "when", "given_", "given"):
            if n.startswith(p):
                n = n[len(p):]
                break
        return n.strip("_")

    def _method_tokens(self, method_names: List[str]) -> Set[str]:
        """
        Tokenize method names into a set of significant tokens.
        """
        tokens: Set[str] = set()
        for m in method_names:
            for t in self._split_identifier(m):
                t = t.lower()
                if self._is_generic_token(t):
                    continue
                if len(t) < 3:
                    continue
                tokens.add(t)
        return tokens

    def _basename_tokens(self, filename: str) -> Set[str]:
        """
        Tokenize a file basename (no path, no extension) similarly to method tokenization.
        """
        base = os.path.splitext(os.path.basename(filename))[0]
        tokens = set()
        for t in self._split_identifier(base):
            t = t.lower()
            if self._is_generic_token(t):
                continue
            if len(t) < 3:
                continue
            tokens.add(t)
        return tokens

    @staticmethod
    def _split_identifier(s: str) -> List[str]:
        """
        Split snake_case, kebab-case, and camelCase identifiers into tokens.
        """
        if not s:
            return []
        s = s.replace("-", "_")
        parts = re.split(r"[_\W]+", s)
        out: List[str] = []
        for p in parts:
            if not p:
                continue
            # camelCase split
            camel = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|$)|\d+", p)
            if camel:
                out.extend(camel)
            else:
                out.append(p)
        return out

    @staticmethod
    def _is_generic_token(t: str) -> bool:
        """
        Tokens that are too generic to be evidence of a tested component.
        """
        generic = {
            "test", "tests", "should", "when", "given", "then",
            "setup", "teardown", "before", "after", "init",
            "case", "cases", "spec", "it", "run", "runs",
            "assert", "verify", "check",
        }
        return (t in generic)

    # ----------------------------
    # Match selection + time parsing
    # ----------------------------

    def _best_source_match(self, test_file: str, source_files: List[str]) -> Optional[str]:
        """
        Pick a deterministic "best" matching source among source_files using _is_related_file.
        If multiple matches, break ties by basename-length proximity then lexicographic.
        """
        matches = [s for s in source_files if self._is_related_file(test_file, s)]
        if not matches:
            # If we got here with candidates produced by methods, they might not be name-related.
            # In that case, just pick deterministically.
            if source_files:
                return sorted(source_files)[0]
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

    # ----------------------------
    # Progress + output
    # ----------------------------

    def _print_progress(self, idx: int, total: int, pc: ProjectCounts) -> None:
        msg = (
            f"\r[{idx}/{total}] {pc.project} -> "
            f"paired={pc.paired} before={pc.before} same={pc.same} after={pc.after} "
            f"(by_methods={pc.paired_by_methods}, by_name={pc.paired_by_name})"
        )
        if pc.note:
            msg += f" ({pc.note})"
        print(msg, end="", flush=True)
        if idx == total:
            print()

    def _write_auditable_txt(self, totals: Totals, per_project: List[ProjectCounts], meta: Dict[str, int]) -> None:
        out_dir = "analysis-output"
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{self._language}_test_source_timing_audit.txt")

        total = totals.paired_total
        before = totals.before
        same = totals.same
        after = totals.after

        per_project_sorted = sorted(per_project, key=lambda p: (-p.paired, p.project))

        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Language: {self._language}\n")

            f.write("\n=== Overall counts (paired test->source) ===\n")
            f.write(f"paired_total: {total}\n")
            f.write(f"before: {before}\n")
            f.write(f"same:   {same}\n")
            f.write(f"after:  {after}\n")

            f.write("\n=== Pairing provenance ===\n")
            f.write(f"paired_by_methods: {totals.paired_by_methods}\n")
            f.write(f"paired_by_name: {totals.paired_by_name}\n")
            if total > 0:
                f.write(f"paired_by_methods_pct: {totals.paired_by_methods / total * 100:.4f}%\n")
                f.write(f"paired_by_name_pct: {totals.paired_by_name / total * 100:.4f}%\n")

            if total > 0:
                f.write("\n=== Overall percentages ===\n")
                f.write(f"before_pct: {before / total * 100:.4f}%\n")
                f.write(f"same_pct:   {same / total * 100:.4f}%\n")
                f.write(f"after_pct:  {after / total * 100:.4f}%\n")

            f.write("\n=== Project coverage / sanity ===\n")
            for k in [
                "projects_total",
                "projects_no_commits",
                "projects_no_tests",
                "projects_no_sources",
                "projects_no_pairs",
            ]:
                f.write(f"{k}: {meta.get(k, 0)}\n")

            f.write("\n=== Per-project breakdown ===\n")
            f.write("project\tpaired\tbefore\tsame\tafter\tby_methods\tby_name\tnote\n")
            for p in per_project_sorted:
                f.write(
                    f"{p.project}\t{p.paired}\t{p.before}\t{p.same}\t{p.after}\t"
                    f"{p.paired_by_methods}\t{p.paired_by_name}\t{p.note}\n"
                )

            f.write("\n=== Quick verification identities ===\n")
            f.write("Invariant 1: before + same + after == paired_total\n")
            f.write(f"Computed: {before} + {same} + {after} = {before + same + after}\n")
            f.write(f"paired_total: {total}\n")
            f.write("Invariant 2: paired_by_methods + paired_by_name == paired_total\n")
            f.write(f"Computed: {totals.paired_by_methods} + {totals.paired_by_name} = "
                    f"{totals.paired_by_methods + totals.paired_by_name}\n")
            f.write(f"paired_total: {total}\n")

        print(f"Wrote audit TXT: {path}")


# ----------------------------
# CLI
# ----------------------------

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
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    commits = get_collection(COMMIT_COLLECTION)
    repos = get_collection(REPO_COLLECTION)

    analysis = creation_analysis(commits_collection=commits, repos_collection=repos, language=args.language)
    analysis.set_is_verbose(args.verbose)
    analysis.run()


if __name__ == "__main__":
    main()
