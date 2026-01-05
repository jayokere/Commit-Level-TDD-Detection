import re
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List, Any, Optional

# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path("analysis-output")
CHARTS_DIR = ROOT / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

LANGUAGES = ["Java", "Python", "C++"]
COLORS = {"Java": "#e67e22", "Python": "#2ecc71", "C++": "#3498db"}

# ============================================================
# PARSERS
# ============================================================

def parse_creation_analysis(language: str) -> Optional[Dict[str, Any]]:
    """Parses <Lang>_test_source_timing_audit.txt for Before/Same/After counts."""
    path = ROOT / f"{language}_test_source_timing_audit.txt"
    data = {"Language": language, "Before": 0, "Same": 0, "After": 0, "Method": 0, "Name": 0}
    
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    
    # Extract overall counts using Regex
    for key in ["before", "same", "after"]:
        match = re.search(rf"{key}:\s*(\d+)", content)
        if match:
            data[key.capitalize()] = int(match.group(1))

    # Extract provenance counts
    method_match = re.search(r"paired_by_methods:\s*(\d+)", content)
    name_match = re.search(r"paired_by_name:\s*(\d+)", content)
    
    if method_match: data["Method"] = int(method_match.group(1))
    if name_match: data["Name"] = int(name_match.group(1))
    
    return data

def parse_lifecycle_analysis(language: str) -> pd.DataFrame:
    """Parses <Lang>_lifecycle_analysis.txt for Stage 1-4 trends."""
    path = ROOT / f"{language}_lifecycle_analysis.txt"
    rows = []
    
    if not path.exists():
        return pd.DataFrame()

    content = path.read_text(encoding="utf-8")
    # Regex to find table rows: "Stage 1 ... | 15.5%"
    pattern = re.compile(r"Stage\s+(\d+).*?\|\s*([\d\.]+)%")
    
    for match in pattern.finditer(content):
        rows.append({
            "Language": language,
            "Stage": int(match.group(1)),
            "TDD_Percentage": float(match.group(2))
        })
    
    return pd.DataFrame(rows)

def parse_static_analysis_and_years() -> pd.DataFrame:
    """
    Parses <Lang>_static_analysis.txt for per-project TDD % and commits,
    and merges it with project_years.csv.
    """
    rows = []
    
    # 1. Parse Static Analysis Text Files
    for lang in LANGUAGES:
        path = ROOT / f"{lang}_static_analysis.txt"
        if not path.exists(): continue
        
        content = path.read_text(encoding="utf-8")
        
        # Regex block to capture project stats
        # Matches: Checking TDD patterns for project "Name" ... Total commits ... TDD pattern percentage ...
        project_blocks = re.split(r'Checking TDD patterns for project', content)[1:]
        
        for block in project_blocks:
            name_match = re.search(r'"(.*?)"', block)
            commit_match = re.search(r'Total commits in project ".*?":\s*(\d+)', block)
            tdd_match = re.search(r'TDD pattern percentage:\s*([\d\.]+)%', block)
            
            if name_match and commit_match and tdd_match:
                rows.append({
                    "Language": lang,
                    "Project": name_match.group(1),
                    "Commits": int(commit_match.group(1)),
                    "TDD_Score": float(tdd_match.group(1))
                })

    df = pd.DataFrame(rows)
    
    # 2. Merge with Years (if available)
    years_path = ROOT / "project_years.csv"
    if years_path.exists() and not df.empty:
        years_df = pd.read_csv(years_path)
        # Rename 'project' to 'Project' to match
        years_df = years_df.rename(columns={"project": "Project", "start_year": "Start_Year"})
        df = pd.merge(df, years_df, on="Project", how="left")
    
    return df

# ============================================================
# PLOTTING FUNCTIONS
# ============================================================

def plot_timing_distribution():
    """Stacked bar chart of Before/Same/After ratios."""
    data = []
    for lang in LANGUAGES:
        res = parse_creation_analysis(lang)
        if res: data.append(res)
    
    if not data: return
    
    df = pd.DataFrame(data).set_index("Language")
    
    # Calculate percentages
    total = df[["Before", "Same", "After"]].sum(axis=1)
    df_pct = df[["Before", "Same", "After"]].div(total, axis=0) * 100
    
    ax = df_pct.plot(kind="bar", stacked=True, figsize=(8, 5), color=["#27ae60", "#f1c40f", "#e74c3c"])
    
    plt.title("When are tests written relative to source code?")
    plt.ylabel("Percentage of Test Files")
    plt.xticks(rotation=0)
    plt.legend(title="Timing", loc='upper right', bbox_to_anchor=(1.15, 1))
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "creation_timing_stacked.png", dpi=150)
    plt.close()
    print("Generated: creation_timing_stacked.png")

def plot_lifecycle_trends():
    """Line chart of TDD adoption over stages."""
    dfs = []
    for lang in LANGUAGES:
        dfs.append(parse_lifecycle_analysis(lang))
    
    full_df = pd.concat(dfs)
    if full_df.empty: return

    plt.figure(figsize=(8, 5))
    sns.lineplot(data=full_df, x="Stage", y="TDD_Percentage", hue="Language", palette=COLORS, marker="o", linewidth=2.5)
    
    plt.title("Evolution of TDD Adoption over Project Lifecycle")
    plt.ylabel("Average TDD %")
    plt.xlabel("Project Stage (Quartiles)")
    plt.xticks([1, 2, 3, 4], ["Inception", "Growth", "Maturity", "Maintenance"])
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "lifecycle_trends.png", dpi=150)
    plt.close()
    print("Generated: lifecycle_trends.png")

def plot_adoption_vs_year(df: pd.DataFrame):
    """Scatter plot of Project Start Year vs TDD Score."""
    if "Start_Year" not in df.columns or df["Start_Year"].isnull().all():
        print("Skipping Year plot (No year data found)")
        return

    plt.figure(figsize=(9, 6))
    sns.scatterplot(data=df, x="Start_Year", y="TDD_Score", hue="Language", palette=COLORS, alpha=0.7, s=60)
    
    plt.title("Does Project Age Influence TDD Adoption?")
    plt.xlabel("Project Start Year")
    plt.ylabel("TDD Pattern Percentage")
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "tdd_vs_year.png", dpi=150)
    plt.close()
    print("Generated: tdd_vs_year.png")

def plot_adoption_vs_size(df: pd.DataFrame):
    """Scatter plot of Project Size (Commits) vs TDD Score."""
    if df.empty: return

    plt.figure(figsize=(9, 6))
    # Log scale often helps visuals with commit counts ranging from 100 to 100,000
    g = sns.scatterplot(data=df, x="Commits", y="TDD_Score", hue="Language", palette=COLORS, alpha=0.7, s=60)
    g.set(xscale="log")
    
    plt.title("TDD Adoption vs. Project Size")
    plt.xlabel("Total Commits (Log Scale)")
    plt.ylabel("TDD Pattern Percentage")
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "tdd_vs_size.png", dpi=150)
    plt.close()
    print("Generated: tdd_vs_size.png")

def plot_heuristic_performance():
    """Pie/Bar chart of how files were paired (Method vs Name)."""
    data = []
    for lang in LANGUAGES:
        res = parse_creation_analysis(lang)
        if res: data.append(res)
    
    if not data: return
    
    df = pd.DataFrame(data).set_index("Language")
    
    # Create a 100% stacked bar for pairing strategy
    total_pairs = df["Method"] + df["Name"]
    df["Method_Pct"] = (df["Method"] / total_pairs) * 100
    df["Name_Pct"] = (df["Name"] / total_pairs) * 100
    
    ax = df[["Method_Pct", "Name_Pct"]].plot(kind="bar", stacked=True, figsize=(7, 5), color=["#8e44ad", "#95a5a6"])
    
    plt.title("Heuristic Performance: How were test files identified?")
    plt.ylabel("Percentage of Pairs")
    plt.xticks(rotation=0)
    plt.legend(["By Method Analysis", "By Filename"], loc='lower right')
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "heuristic_performance.png", dpi=150)
    plt.close()
    print("Generated: heuristic_performance.png")

# ============================================================
# MAIN EXECUTION
# ============================================================

if __name__ == "__main__":
    print("--- Generarting Charts from Analysis Output ---")
    
    # 1. Generate Timing Charts
    plot_timing_distribution()
    plot_heuristic_performance()
    
    # 2. Generate Lifecycle Charts
    plot_lifecycle_trends()
    
    # 3. Generate Project-Level correlations
    #    (Requires parsing static analysis + CSV)
    main_df = parse_static_analysis_and_years()
    
    if not main_df.empty:
        plot_adoption_vs_size(main_df)
        plot_adoption_vs_year(main_df)
    else:
        print("No static analysis data found to plot correlations.")
        
    print(f"\nDone! Charts saved to: {CHARTS_DIR.absolute()}")