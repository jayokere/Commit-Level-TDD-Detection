from typing import Dict, Any, List, Tuple, DefaultDict
from collections import defaultdict

from db import get_collection, COMMIT_COLLECTION, REPO_COLLECTION

TDD_FIELD = "TDD-Same"
VALID = {"True", "Semi", "False"}


def load_repo_language_map(repos_col) -> Dict[str, str]:
    """
    Build a mapping from repo URL to language.
    Supports repos storing URL under either 'url' or 'repo_url'.
    """
    m: Dict[str, str] = {}
    cursor = repos_col.find({}, {"url": 1, "repo_url": 1, "language": 1})
    for doc in cursor:
        lang = doc.get("language") or "Unknown"
        u1 = doc.get("url")
        u2 = doc.get("repo_url")
        if isinstance(u1, str) and u1:
            m[u1] = lang
        if isinstance(u2, str) and u2:
            m[u2] = lang
    return m


def aggregate_commits_per_repo(commits_col) -> List[Dict[str, Any]]:
    """
    Aggregate commits into per-repo counts, using only documents that have a valid TDD-Same.
    """
    pipeline = [
        {"$match": {TDD_FIELD: {"$in": list(VALID)}}},
        {"$group": {
            "_id": "$repo_url",
            "total_commits": {"$sum": 1},
            "true_commits": {"$sum": {"$cond": [{"$eq": [f"${TDD_FIELD}", "True"]}, 1, 0]}},
            "semi_commits": {"$sum": {"$cond": [{"$eq": [f"${TDD_FIELD}", "Semi"]}, 1, 0]}},
            "false_commits": {"$sum": {"$cond": [{"$eq": [f"${TDD_FIELD}", "False"]}, 1, 0]}},
        }},
    ]
    return list(commits_col.aggregate(pipeline, allowDiskUse=True))


def pct(n: int, d: int) -> float:
    return (n / d * 100.0) if d > 0 else 0.0


def main() -> None:
    commits = get_collection(COMMIT_COLLECTION)
    repos = get_collection(REPO_COLLECTION)

    # Debug sanity prints (helpful once; keep if you like)
    print("Commits collection:", commits.full_name)
    print("Estimated commits:", commits.estimated_document_count())
    print("Docs with TDD-Same:", commits.count_documents({TDD_FIELD: {"$exists": True}}))

    repo_lang = load_repo_language_map(repos)
    per_repo = aggregate_commits_per_repo(commits)

    # ------------------------------------------------------------------
    # Overall counts (True/Semi/False)
    # ------------------------------------------------------------------
    overall_true = sum(r["true_commits"] for r in per_repo)
    overall_semi = sum(r["semi_commits"] for r in per_repo)
    overall_false = sum(r["false_commits"] for r in per_repo)
    overall_total = sum(r["total_commits"] for r in per_repo)

    print("\n" + "=" * 80)
    print("Overall counts by TDD-Same (True/Semi/False)")
    print("=" * 80)
    print({
        "total_commits": overall_total,
        "true": overall_true,
        "semi": overall_semi,
        "false": overall_false,
    })

    # ------------------------------------------------------------------
    # Overall adoption (All Languages) - commit-weighted
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("Overall adoption rate (All Languages) using TDD-Same")
    print("=" * 80)
    print({
        "true_pct": pct(overall_true, overall_total),
        "semi_pct": pct(overall_semi, overall_total),
        "true_semi_pct": pct(overall_true + overall_semi, overall_total),
    })

    # ------------------------------------------------------------------
    # Language-specific adoption (commit-weighted)
    # ------------------------------------------------------------------
    lang_totals: DefaultDict[str, Dict[str, int]] = defaultdict(lambda: {
        "total": 0, "true": 0, "semi": 0, "false": 0, "projects": 0
    })

    # Also store per-project rates for unweighted per-language averages
    lang_project_rates: DefaultDict[str, List[Tuple[float, float, float]]] = defaultdict(list)

    for r in per_repo:
        repo_url = r["_id"]
        lang = repo_lang.get(repo_url, "Unknown")

        total = int(r["total_commits"])
        t = int(r["true_commits"])
        s = int(r["semi_commits"])
        f = int(r["false_commits"])

        # commit-weighted accumulators
        lang_totals[lang]["total"] += total
        lang_totals[lang]["true"] += t
        lang_totals[lang]["semi"] += s
        lang_totals[lang]["false"] += f
        lang_totals[lang]["projects"] += 1

        # per-project adoption rates (unweighted mean later)
        true_rate = (t / total) if total > 0 else 0.0
        semi_rate = (s / total) if total > 0 else 0.0
        true_semi_rate = ((t + s) / total) if total > 0 else 0.0
        lang_project_rates[lang].append((true_rate, semi_rate, true_semi_rate))

    # Commit-weighted language adoption output
    lang_weighted_rows = []
    for lang, agg in lang_totals.items():
        total = agg["total"]
        lang_weighted_rows.append({
            "language": lang,
            "projects": agg["projects"],
            "total_commits": total,
            "true_pct": pct(agg["true"], total),
            "semi_pct": pct(agg["semi"], total),
            "true_semi_pct": pct(agg["true"] + agg["semi"], total),
        })
    lang_weighted_rows.sort(key=lambda x: x["total_commits"], reverse=True)

    print("\n" + "=" * 80)
    print("Language-specific adoption (commit-weighted) using TDD-Same")
    print("=" * 80)
    print(lang_weighted_rows)

    # ------------------------------------------------------------------
    # Average adoption per project (language-specific, unweighted mean over repos)
    # ------------------------------------------------------------------
    lang_project_rows = []
    for lang, rates in lang_project_rates.items():
        if not rates:
            continue
        n = len(rates)
        avg_true = sum(x[0] for x in rates) / n
        avg_semi = sum(x[1] for x in rates) / n
        avg_true_semi = sum(x[2] for x in rates) / n
        lang_project_rows.append({
            "language": lang,
            "projects": n,
            "avg_project_true_pct": avg_true * 100.0,
            "avg_project_semi_pct": avg_semi * 100.0,
            "avg_project_true_semi_pct": avg_true_semi * 100.0,
        })
    lang_project_rows.sort(key=lambda x: x["projects"], reverse=True)

    print("\n" + "=" * 80)
    print("Average adoption per project (language-specific, unweighted mean over repos)")
    print("=" * 80)
    print(lang_project_rows)


if __name__ == "__main__":
    main()
