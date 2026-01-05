import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import matplotlib.pyplot as plt


# ============================================================
# Paths
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
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
# Helpers
# ============================================================

def _extract_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text, re.MULTILINE)
    return int(m.group(1)) if m else None


def _extract_float(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text, re.MULTILINE)
    return float(m.group(1)) if m else None


def _lang_repos_header_pattern(lang: str) -> str:
    # New-style headers contain e.g.:
    # "Total C++ repositories: 59"
    # "Total Java repositories: 60"
    # "Total Python repositories: 60"
    if lang == "C++":
        return r"Total\s+C\+\+\s+repositories:\s*(\d+)"
    return rf"Total\s+{re.escape(lang)}\s+repositories:\s*(\d+)"


# ============================================================
# Parsing static analysis outputs
# ============================================================

def parse_analysis_file(path: Path, language: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")

    summary: Dict[str, Any] = {"language": language}
    rows: List[Dict[str, Any]] = []

    # ----------------------------
    # New-style header extraction
    # ----------------------------
    summary["total_repositories_all"] = _extract_int(text, r"Total repositories:\s*(\d+)")
    summary["total_commits_all"] = _extract_int(text, r"Total commits:\s*(\d+)")
    summary["projects_checked_header"] = _extract_int(text, _lang_repos_header_pattern(language))

    # ----------------------------
    # Old-style footer extraction (keep for backwards compatibility)
    # ----------------------------
    # Example old footer:
    # "Final Results: 18.33% of Python projects (11/60) have TDD patterns detected"
    footer = re.search(
        rf"Final Results:\s*([0-9.]+)%\s*of\s*{re.escape(language)}\s*projects\s*\((\d+)\/(\d+)\)",
        text
    )
    if footer:
        summary["pct_projects_with_tdd_footer"] = float(footer.group(1))
        summary["projects_with_tdd_footer"] = int(footer.group(2))
        summary["projects_checked_footer"] = int(footer.group(3))

    # ----------------------------
    # Per-project blocks (works for both old and new logs)
    # ----------------------------
    # Matches blocks like:
    # 0-0.) Checking TDD patters for project with name "airflow"
    # Total commits in project "airflow": 17000
    # Detected TDD patterns (6407 total):
    # TDD pattern percentage: 37.69% (6407/17000)
    sampled_re = re.compile(
        r'Checking TDD patters for project with name "([^"]+)"\s*'
        r'Total commits in project "[^"]+":\s*(\d+)\s*'
        r'Detected TDD patterns \((\d+) total\):\s*'
        r'TDD pattern percentage:\s*([0-9.]+)%\s*\((\d+)\/(\d+)\)',
        re.MULTILINE
    )

    for m in sampled_re.finditer(text):
        project = m.group(1)
        total_commits = int(m.group(2))
        tdd_patterns = int(m.group(3))
        tdd_pct = float(m.group(4))

        # In case the printed ratio differs from the earlier total commits line, keep both.
        ratio_num = int(m.group(5))
        ratio_den = int(m.group(6))

        rows.append({
            "language": language,
            "project": project,
            "sampled": True,
            "total_commits": total_commits,
            "tdd_patterns": tdd_patterns,
            "tdd_pattern_pct": tdd_pct,
            "ratio_tdd_patterns": ratio_num,
            "ratio_total_commits": ratio_den,
            "high_tdd_flag": (tdd_pct > 20.0),  # robust even if the log line is absent
        })

    # ----------------------------
    # Old logs sometimes include "was not sampled" blocks
    # ----------------------------
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
            "ratio_tdd_patterns": None,
            "ratio_total_commits": None,
            "high_tdd_flag": None,
        })

    df = pd.DataFrame(rows).drop_duplicates(subset=["language", "project", "sampled"])

    # ----------------------------
    # Compute summary metrics from parsed data (works for new logs)
    # ----------------------------
    sampled_df = df[df["sampled"] == True].copy()

    projects_checked_from_rows = int(sampled_df["project"].nunique())
    projects_with_tdd_from_rows = int(sampled_df[sampled_df["tdd_patterns"].fillna(0) > 0]["project"].nunique())
    pct_from_rows = (projects_with_tdd_from_rows / projects_checked_from_rows * 100.0) if projects_checked_from_rows else 0.0

    # Prefer header if present (new logs), else footer if present (old logs), else row-derived fallback
    projects_checked = (
        summary.get("projects_checked_header")
        or summary.get("projects_checked_footer")
        or projects_checked_from_rows
    )

    # Prefer footer if present for backwards compatibility, else row-derived
    projects_with_tdd = summary.get("projects_with_tdd_footer") or projects_with_tdd_from_rows
    pct_projects_with_tdd = summary.get("pct_projects_with_tdd_footer") or (
        (projects_with_tdd / projects_checked * 100.0) if projects_checked else 0.0
    )

    summary["projects_checked"] = int(projects_checked)
    summary["projects_with_tdd"] = int(projects_with_tdd)
    summary["pct_projects_with_tdd"] = float(pct_projects_with_tdd)

    # High-adoption projects (>20%)
    high_count = int(sampled_df[sampled_df["tdd_pattern_pct"].fillna(0) > 20.0]["project"].nunique())
    summary["projects_high_tdd_gt20"] = high_count

    return df, summary


# ============================================================
# Load data
# ============================================================

dfs: List[pd.DataFrame] = []
summary_rows: List[Dict[str, Any]] = []

for lang, path in FILES.items():
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df, summ = parse_analysis_file(path, lang)
    dfs.append(df)
    summary_rows.append(summ)

data = pd.concat(dfs, ignore_index=True)

# Ensure numeric
data["tdd_pattern_pct"] = pd.to_numeric(data["tdd_pattern_pct"], errors="coerce")
data["tdd_patterns"] = pd.to_numeric(data["tdd_patterns"], errors="coerce")
data["total_commits"] = pd.to_numeric(data["total_commits"], errors="coerce")

summary_df = pd.DataFrame(summary_rows)

# Save parsed CSV for debugging / reuse
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

# 1b) High-adoption projects (>20%) count (by language) — useful with new logs
plt.figure(figsize=(6, 4))
plt.bar(summary_df["language"], summary_df["projects_high_tdd_gt20"])
plt.ylabel("Projects with >20% TDD adoption")
plt.title("High TDD adoption projects by language (>20%)")
plt.tight_layout()
plt.savefig(CHARTS_DIR / "projects_high_tdd_gt20.png", dpi=200)
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

# 4) TDD pattern % vs project size (number of commits), coloured by language

# Use sampled projects with valid TDD percentages and commit counts
size_data = sampled.dropna(subset=["tdd_pattern_pct", "total_commits"]).copy()
size_data["total_commits"] = pd.to_numeric(size_data["total_commits"], errors="coerce")
size_data = size_data.dropna(subset=["total_commits"])

if not size_data.empty:
    max_commits = int(size_data["total_commits"].max())

    plt.figure(figsize=(9, 5))

    for lang in languages:
        sub = size_data[size_data["language"] == lang]
        if sub.empty:
            continue

        plt.scatter(
            sub["total_commits"],
            sub["tdd_pattern_pct"],
            label=lang,
            color=colors.get(lang),
            alpha=0.7,
            s=25
        )

    plt.xlim(0, max_commits)
    plt.xlabel("Project size (total number of commits)")
    plt.ylabel("TDD pattern percentage per project (%)")
    plt.title("TDD adoption vs project size (by language)")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()

    plt.savefig(CHARTS_DIR / "tdd_vs_project_size.png", dpi=200)
    plt.close()

   # ============================================================
# Heatmap: Language × Lifecycle Stage (Average TDD adoption %)
# ============================================================

LIFECYCLE_FILES = {
    "C++": ANALYSIS_DIR / "C++_lifecycle_analysis.txt",
    "Java": ANALYSIS_DIR / "Java_lifecycle_analysis.txt",
    "Python": ANALYSIS_DIR / "Python_lifecycle_analysis.txt",
}

STAGES = [1, 2, 3, 4]
STAGE_LABELS = ["Stage 1\n(Inception)", "Stage 2\n(Growth)", "Stage 3\n(Maturity)", "Stage 4\n(Maintenance)"]
LANG_ORDER = ["C++", "Java", "Python"]


def parse_lifecycle_stage_avgs(path: Path) -> Dict[int, float]:
    """
    Extracts stage averages from the FINAL LIFECYCLE TREND table.
    Returns {stage: avg_pct}.
    Accepts lines like:
      Stage 1 (Inception) | ... | 12.34%
    """
    text = path.read_text(encoding="utf-8", errors="ignore")

    # Match "Stage <n> ... | <number>%"
    # Works as long as the last column is a percentage.
    stage_re = re.compile(r"Stage\s+(\d+).*?\|\s*([0-9]+(?:\.[0-9]+)?)%")

    out: Dict[int, float] = {}
    for m in stage_re.finditer(text):
        stage = int(m.group(1))
        pct = float(m.group(2))
        if stage in STAGES:
            out[stage] = pct

    return out


# Build matrix (rows=languages, cols=stages)
matrix = []
missing_any = False

for lang in LANG_ORDER:
    p = LIFECYCLE_FILES.get(lang)
    if not p or not p.exists():
        missing_any = True
        matrix.append([float("nan")] * len(STAGES))
        continue

    stage_map = parse_lifecycle_stage_avgs(p)
    row = []
    for s in STAGES:
        if s not in stage_map:
            missing_any = True
            row.append(float("nan"))
        else:
            row.append(stage_map[s])
    matrix.append(row)

# Plot heatmap
plt.figure(figsize=(9, 3.8))
ax = plt.gca()

im = ax.imshow(matrix, aspect="auto")  # default colormap; do not set colors explicitly

# Axis labels
ax.set_xticks(range(len(STAGES)))
ax.set_xticklabels(STAGE_LABELS)
ax.set_yticks(range(len(LANG_ORDER)))
ax.set_yticklabels(LANG_ORDER)

ax.set_xlabel("Project lifecycle stage (by commit quartiles)")
ax.set_ylabel("Language")
ax.set_title("Average TDD adoption across project lifecycle stages")

# Annotate values in each cell (skip NaN)
for i, lang in enumerate(LANG_ORDER):
    for j, s in enumerate(STAGES):
        val = matrix[i][j]
        if val == val:  # NaN check
            ax.text(j, i, f"{val:.1f}%", ha="center", va="center")

# Colorbar
cbar = plt.colorbar(im, ax=ax)
cbar.set_label("Average TDD adoption (%)")

plt.tight_layout()
plt.savefig(CHARTS_DIR / "tdd_lifecycle_heatmap.png", dpi=250)
plt.close()

if missing_any:
    print("Heatmap note: some lifecycle stages/languages were missing and are shown as blank cells.")
else:
    print("Lifecycle heatmap generated: analysis-output/charts/tdd_lifecycle_heatmap.png")


# ============================================================
# 5) Lifecycle trend: TDD adoption vs project maturity stage
# ============================================================

LIFECYCLE_FILES = {
    "C++": ANALYSIS_DIR / "C++_lifecycle_analysis.txt",
    "Java": ANALYSIS_DIR / "Java_lifecycle_analysis.txt",
    "Python": ANALYSIS_DIR / "Python_lifecycle_analysis.txt",
}

def parse_lifecycle_trend(path: Path) -> Dict[int, float]:
    """
    Parses the FINAL LIFECYCLE TREND table and returns:
    { stage_number (1-4): average_tdd_pct }
    """
    text = path.read_text(encoding="utf-8", errors="ignore")

    stage_re = re.compile(
        r"Stage\s+(\d+).*?\|\s*([0-9.]+)%"
    )

    stages: Dict[int, float] = {}
    for m in stage_re.finditer(text):
        stage = int(m.group(1))
        pct = float(m.group(2))
        stages[stage] = pct

    return stages


# Collect lifecycle data
lifecycle_data: Dict[str, Dict[int, float]] = {}

for lang, path in LIFECYCLE_FILES.items():
    if not path.exists():
        print(f"Lifecycle file missing for {lang}, skipping.")
        continue
    lifecycle_data[lang] = parse_lifecycle_trend(path)

# Plot lifecycle trend
if lifecycle_data:
    plt.figure(figsize=(8, 5))

    for lang, stages in lifecycle_data.items():
        if not stages:
            continue

        xs = sorted(stages.keys())
        ys = [stages[s] for s in xs]

        plt.plot(
            xs,
            ys,
            marker="o",
            linewidth=2,
            label=lang,
            color=colors.get(lang)
        )

    plt.xticks([1, 2, 3, 4], [
        "Stage 1\n(Inception)",
        "Stage 2\n(Growth)",
        "Stage 3\n(Maturity)",
        "Stage 4\n(Maintenance)"
    ])

    plt.ylabel("Average TDD adoption (%)")
    plt.xlabel("Project lifecycle stage (by commit quartiles)")
    plt.title("TDD adoption across project lifecycle stages")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()

    plt.savefig(CHARTS_DIR / "tdd_lifecycle_trend.png", dpi=200)
    plt.close()




print("Charts generated successfully.")
print(f"Parsed CSV written to: {csv_path}")
print(f"Charts directory: {CHARTS_DIR}")
if not PROJECT_YEARS_CSV.exists():
    print("Note: project_years.csv not found, so tdd_vs_project_year.png was not generated.")
