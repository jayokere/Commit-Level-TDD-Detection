import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd
import matplotlib.pyplot as plt


# ============================================================
# Paths
# ============================================================

ROOT = Path(__file__).resolve().parent
ANALYSIS_DIR = ROOT / "analysis-output"
CHARTS_DIR = ANALYSIS_DIR / "charts"
CHARTS_DIR.mkdir(exist_ok=True)

FILES = {
    "C++": ANALYSIS_DIR / "C++_static_analysis.txt",
    "Java": ANALYSIS_DIR / "Java_static_analysis.txt",
    "Python": ANALYSIS_DIR / "Python_static_analysis.txt",
}

PROJECT_YEARS_CSV = ANALYSIS_DIR / "project_years.csv"


# ============================================================
# Parsing static analysis outputs
# ============================================================

def parse_analysis_file(path: Path, language: str):
    text = path.read_text(encoding="utf-8", errors="ignore")

    summary: Dict[str, Any] = {"language": language}
    rows: List[Dict[str, Any]] = []

    # Footer: "Final Results: 18.33% of Python projects (11/60) have TDD patterns detected"
    m = re.search(
        rf"Final Results:\s*([0-9.]+)%\s*of\s*{re.escape(language)}\s*projects\s*\((\d+)\/(\d+)\)",
        text
    )
    if m:
        summary["pct_projects_with_tdd"] = float(m.group(1))
        summary["projects_with_tdd"] = int(m.group(2))
        summary["projects_checked"] = int(m.group(3))

    # Sampled project blocks
    sampled_re = re.compile(
        r'Checking TDD patters for project with name "([^"]+)"\s*'
        r'Total commits in project "[^"]+":\s*(\d+)\s*'
        r'Detected TDD patterns \((\d+) total\):\s*'
        r'TDD pattern percentage:\s*([0-9.]+)%',
        re.MULTILINE
    )

    for m in sampled_re.finditer(text):
        rows.append({
            "language": language,
            "project": m.group(1),
            "sampled": True,
            "total_commits": int(m.group(2)),
            "tdd_patterns": int(m.group(3)),
            "tdd_pattern_pct": float(m.group(4)),
        })

    # Not sampled projects (useful for completeness, not used in charts requiring tdd_pattern_pct)
    not_sampled_re = re.compile(
        r'project with name "([^"]+)" was not sampled\s*It has\s*(\d+)\s*commits',
        re.MULTILINE
    )
    for m in not_sampled_re.finditer(text):
        rows.append({
            "language": language,
            "project": m.group(1),
            "sampled": False,
            "total_commits": int(m.group(2)),
            "tdd_patterns": None,
            "tdd_pattern_pct": None,
        })

    # Optional: Average TDDpct lines (if present)
    # We capture at project-level when available.
    # (If your logs include these lines, they will appear in the CSV and can be charted.)
    # We'll attach them by scanning per project block.
    tddpct_map: Dict[str, Dict[str, Optional[float]]] = {}

    block_re = re.compile(
        r'(Checking TDD patters for project with name "([^"]+)".*?)(?=\n\d+[\-\.)]|\nFinal Results:|\Z)',
        re.DOTALL
    )
    for bm in block_re.finditer(text):
        proj = bm.group(2)
        block = bm.group(1)
        m1 = re.search(r'Average TDDpct \(across sampled commits\):\s*([0-9.]+)%', block)
        m2 = re.search(r'Average TDDpct \(across detected patterns\):\s*([0-9.]+)%', block)
        if m1 or m2:
            tddpct_map[proj] = {
                "avg_tddpct_commits": float(m1.group(1)) if m1 else None,
                "avg_tddpct_patterns": float(m2.group(1)) if m2 else None,
            }

    df = pd.DataFrame(rows).drop_duplicates(subset=["language", "project", "sampled"])

    if not df.empty:
        df["avg_tddpct_commits"] = df.apply(
            lambda r: tddpct_map.get(r["project"], {}).get("avg_tddpct_commits"),
            axis=1
        )
        df["avg_tddpct_patterns"] = df.apply(
            lambda r: tddpct_map.get(r["project"], {}).get("avg_tddpct_patterns"),
            axis=1
        )

    return df, summary


# ============================================================
# Load data
# ============================================================

dfs = []
summary_rows = []

for lang, path in FILES.items():
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df, summ = parse_analysis_file(path, lang)
    dfs.append(df)

    # If footer summary is missing, infer from sampled projects as fallback
    if "projects_checked" not in summ:
        sampled = df[df["sampled"] == True]
        checked = int(sampled["project"].nunique())
        with_tdd = int(sampled[sampled["tdd_patterns"].fillna(0) > 0]["project"].nunique())
        pct = (with_tdd / checked * 100.0) if checked else 0.0
        summ["projects_checked"] = checked
        summ["projects_with_tdd"] = with_tdd
        summ["pct_projects_with_tdd"] = pct

    summary_rows.append(summ)

data = pd.concat(dfs, ignore_index=True)

# Ensure numeric
data["tdd_pattern_pct"] = pd.to_numeric(data["tdd_pattern_pct"], errors="coerce")
data["avg_tddpct_commits"] = pd.to_numeric(data["avg_tddpct_commits"], errors="coerce")
data["avg_tddpct_patterns"] = pd.to_numeric(data["avg_tddpct_patterns"], errors="coerce")

summary_df = pd.DataFrame(summary_rows)

# Save parsed CSV
csv_path = CHARTS_DIR / "static_analysis_parsed.csv"
data.to_csv(csv_path, index=False)


# ============================================================
# Charts
# ============================================================

colors = {"C++": "tab:blue", "Java": "tab:orange", "Python": "tab:green"}
languages = summary_df["language"].tolist()

# 1) % projects with TDD patterns (by language)
plt.figure(figsize=(6, 4))
plt.bar(summary_df["language"], summary_df["pct_projects_with_tdd"])
plt.ylabel("% of projects with TDD patterns")
plt.title("TDD adoption by language (project level)")
plt.tight_layout()
plt.savefig(CHARTS_DIR / "projects_with_tdd_pct.png", dpi=200)
plt.close()

# 2) Distribution of TDD pattern percentage by language (scatter)
sampled = data[(data["sampled"] == True) & (data["tdd_pattern_pct"].notna())].copy()

plt.figure(figsize=(9, 5))
for i, lang in enumerate(languages):
    vals = sampled[sampled["language"] == lang]["tdd_pattern_pct"].values
    if len(vals) == 0:
        continue
    xs = [i] * len(vals)
    plt.scatter(xs, vals, s=12, color=colors.get(lang), alpha=0.8)

plt.xticks(range(len(languages)), languages)
plt.ylabel("TDD pattern percentage per project (%)")
plt.title("Distribution of TDD pattern percentage by language")
plt.tight_layout()
plt.savefig(CHARTS_DIR / "tdd_pattern_distribution.png", dpi=200)
plt.close()

# 3) Top 15 projects by TDD pattern % (per language)
for lang in languages:
    top = sampled[sampled["language"] == lang].sort_values("tdd_pattern_pct", ascending=False).head(15)
    if top.empty:
        continue

    plt.figure(figsize=(8, 5))
    plt.barh(top["project"][::-1], top["tdd_pattern_pct"][::-1])
    plt.xlabel("TDD pattern percentage (%)")
    plt.title(f"Top projects by TDD pattern % ({lang})")
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / f"top_projects_{lang}.png", dpi=200)
    plt.close()

# 4) Average TDDpct by language (only where present)
tddpct_lang = sampled.groupby("language")["avg_tddpct_commits"].mean()
if tddpct_lang.notna().any():
    plt.figure(figsize=(6, 4))
    plt.bar(tddpct_lang.index.tolist(), tddpct_lang.values.tolist())
    plt.ylabel("Average TDDpct (across sampled commits)")
    plt.title("Average TDDpct by language")
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "avg_tddpct_by_language.png", dpi=200)
    plt.close()

# 5) TDD pattern % vs project start year (colours by language)
if PROJECT_YEARS_CSV.exists():
    project_years = pd.read_csv(PROJECT_YEARS_CSV)
    merged = sampled.merge(project_years, on="project", how="left").dropna(subset=["start_year"])
    merged["start_year"] = pd.to_numeric(merged["start_year"], errors="coerce")
    merged = merged.dropna(subset=["start_year"])

    if not merged.empty:
        plt.figure(figsize=(9, 5))
        for lang in languages:
            sub = merged[merged["language"] == lang]
            if sub.empty:
                continue
            plt.scatter(
                sub["start_year"],
                sub["tdd_pattern_pct"],
                label=lang,
                color=colors.get(lang),
                alpha=0.75,
                s=25
            )
        plt.xlabel("Project start year (earliest commit year)")
        plt.ylabel("TDD pattern percentage per project (%)")
        plt.title("TDD adoption vs project start year (by language)")
        plt.legend()
        plt.grid(True, linestyle="--", alpha=0.3)
        plt.tight_layout()
        plt.savefig(CHARTS_DIR / "tdd_vs_project_year.png", dpi=200)
        plt.close()

print("Charts generated successfully.")
print(f"CSV written to: {csv_path}")
print(f"Charts directory: {CHARTS_DIR}")
if not PROJECT_YEARS_CSV.exists():
    print("Note: project_years.csv not found, so tdd_vs_project_year.png was not generated.")
