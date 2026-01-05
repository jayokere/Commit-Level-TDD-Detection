# Apache Projects TDD Miner and Detector

A comprehensive tool for mining Apache Software Foundation repositories and detecting **Test-Driven Development (TDD)** patterns through static analysis of commit history.

This application:
1. Connects to the Apache Software Foundation's GitHub API to discover repositories
2. Mines commit history from repositories using PyDriller
3. Performs static analysis to detect TDD patterns (test-first development)
4. Generates detailed reports on TDD adoption across projects

## 📂 Project Structure

```text
.
├── main.py                       # Entry point - orchestrates mining and analysis
├── requirements.txt              # Python dependencies
├── TESTING_GUIDE.md              # Guide for running and understanding tests
│
├── analysis/                     # TDD detection and analysis modules
│   ├── static_analysis.py        # Core TDD pattern detection algorithm
│   ├── lifecycle_analysis.py     # TDD adoption across project lifecycle stages
│   ├── creation_analysis.py      # Test file timing analysis (before/after source)
│   ├── source_file_calculator.py # Source file statistics
│   ├── demo_test_detection.py    # Interactive demo of test detection
│   └── run_analysis.py           # Analysis runner script
│
├── mining/                       # Repository mining modules
│   ├── apache_miner.py           # Apache GitHub API miner
│   ├── repo_miner.py             # Commit mining orchestrator
│   ├── worker.py                 # Parallel worker for mining commits
│   ├── partitioner.py            # Date range partitioning for large repos
│   └── components/               # Mining sub-components
│       ├── commit_processor.py   # Commit data extraction
│       ├── file_analyser.py      # File type detection
│       └── test_analyser.py      # Test coverage analysis
│
├── database/                     # MongoDB integration
│   ├── db.py                     # Database connection and operations
│   ├── check_status.py           # Mining progress checker
│   ├── clean_db.py               # Database cleanup utilities
│   └── sync_counts.py            # Commit count synchronization
│
├── utilities/                    # Shared utilities
│   ├── config.py                 # Configuration constants
│   ├── utils.py                  # Helper functions
│   └── miner_intro.py            # CLI banner display
│
├── visualisation/                # Chart generation
│   └── charts.py                 # Analysis result visualization
│
├── tests/                        # Unit tests (69 tests)
│   ├── test_static_analysis.py   # TDD detection tests
│   ├── test_lifecycle_analysis.py
│   ├── test_creation_analysis.py
│   ├── repo_miner_test.py
│   ├── apache_miner_test.py
│   └── ...
│
└── analysis-output/              # Generated analysis results
    ├── Java_static_analysis.txt
    ├── Python_static_analysis.txt
    ├── C++_static_analysis.txt
    └── ...
```
## 🚀 Getting Started

### Prerequisites
* Python 3.8 or higher
* MongoDB Atlas account (or local MongoDB instance)
* GitHub Personal Access Token
* An internet connection

### Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/jayokere/Apache-TDD-Detector.git
    cd Apache-TDD-Detector
    ```

2.  **Setup Virtual Environment** (recommended):
    ```bash
    # MacOS / Linux
    python3 -m venv venv
    source venv/bin/activate

    # Windows
    py -m venv venv
    venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables** - Create a `.env` file:
    ```bash
    GITHUB_TOKEN=your_github_personal_access_token
    MONGODB_USER=your_mongodb_username
    MONGODB_PWD=your_mongodb_password
    ```

## ⚙️ Usage

### Main Menu
Run the main script to access all features:
```bash
python main.py
```

This presents an interactive menu:
1. **Mine Apache Repositories** - Discover and catalog Apache GitHub repos
2. **Mine Commits** - Extract commit data from repositories
3. **Run Analysis** - Perform TDD detection analysis
4. **View Charts** - Generate visualizations of results

### Direct Analysis
Run analysis scripts directly:
```bash
# Static TDD Analysis
python analysis/static_analysis.py

# Lifecycle Analysis (TDD adoption over time)
python analysis/lifecycle_analysis.py

# Creation Timing Analysis
python analysis/creation_analysis.py -l Java
python analysis/creation_analysis.py -l Python
python analysis/creation_analysis.py -l C++
```

### Analysis Output
Results are saved to `analysis-output/`:
- `{Language}_static_analysis.txt` - TDD detection results
- `{Language}_lifecycle_analysis.txt` - TDD adoption by project stage
- `{Language}_test_source_timing_audit.txt` - Test/source timing analysis

## 🧪 Testing

This project maintains 69 unit tests using `pytest`. Tests use mocking to avoid database dependencies.

```bash
# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_static_analysis.py -v
pytest tests/test_lifecycle_analysis.py -v
pytest tests/repo_miner_test.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

See [TESTING_GUIDE.md](TESTING_GUIDE.md) for detailed testing documentation.

## 📊 TDD Detection Algorithm

The tool detects two types of TDD patterns:

1. **Same-Commit TDD**: Test and source files modified in the same commit with related names
2. **Diff-Commit TDD**: Test file committed before its corresponding source file

Detection uses:
- File name matching (e.g., `CalculatorTest.java` → `Calculator.java`)
- Method name analysis (e.g., `test_square_area` → `square.py`)
- Changed method overlap between test and source files

## 🗺 Roadmap

- [x] **Phase 1:** Mine Apache Project Feed for GitHub links
- [x] **Phase 2:** Mine GitHub repositories for commits
- [x] **Phase 3:** Implement TDD detection logic (static analysis)
- [x] **Phase 4:** Lifecycle analysis (TDD adoption over project maturity)
- [x] **Phase 5:** Creation timing analysis (test-first detection)
- [ ] **Phase 6:** Extended reporting and visualization

## 📄 License
