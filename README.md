# Apache Projects TDD Miner and Detector

This tool acts as the data collection phase for a larger research project aimed at detecting **Test-Driven Development (TDD)** patterns within open-source software.

Currently, this application connects to the Apache Software Foundation's public API to retrieve a comprehensive list of all projects, filters them for valid GitHub repositories, and creates a local dataset for analysis.

## 📂 Project Structure

```text
.
├── apache_web_miner.py           # The "Tool": Class responsible for fetching and parsing API data
├── main.py                   # The "Workflow": Entry point that manages logic and file persistence
├── requirements.txt          # List of Python dependencies
├── .gitignore                # Specifies files to be ignored by Git (e.g., data/, __pycache__/)
├── tests/                    # Unit tests folder
│   ├── __init__.py
│   ├── apache_web_miner_test.py  # Tests for the mining class
│   └── main_test.py          # Tests for the workflow logic
└── data/                     # Output folder (Generated automatically)
    └── apache_projects.json  # The resulting dataset

```
## 🚀 Getting Started

### Prerequisites
* Python 3.8 or higher
* An internet connection (for the initial data fetch)

### Installation

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone <your-repo-url>
    cd <your-project-folder>
    ```

2.  **Setup Virtual Environment** (recommended):
    ```bash
    # MacOS / Linux
    python3 -m venv venv
    source venv/bin/activate

    # Windows
    python -m venv venv
    venv\Scripts\activate   # command prompt
    venv\Scripts\Activate.ps1 # PowerShell
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4. **.env file setup
   ```bash
   GITHUB_TOKEN={GITHUB_TOKEN}
   MONGODB_USER="MongoDB_username"
   MONGODB_PWD="MongoDB_password"
   ```
   
## ⚙️ Usage

To execute the miner, run the main script from the root directory:

```bash
python main.py
```
### How it works
1.  **Check:** The script looks for a local file at `data/apache_projects.json`.
2.  **Cache Hit:** If the file exists, it loads the data locally to save time and bandwidth.
3.  **Cache Miss:** If the file is missing, it:
    * Connects to `projects.apache.org`.
    * Downloads the full project registry.
    * Filters for repositories hosted on `github.com`.
    * Creates the `data/` directory (if missing).
    * Saves the results to `data/apache_projects.json`.

## 🧪 Testing

This project maintains a suite of unit tests using `unittest`. We use **mocking** to simulate API responses and file operations, ensuring tests are fast and do not rely on a live internet connection.

To run all tests:

```bash
pytest -v tests/*_test.py
```
## 🗺 Roadmap

- [x] **Phase 1:** Mine Apache Project Feed for GitHub links.
- [ ] **Phase 2:** Mine Github Links for commits
- [ ] **Phase 3:** Implement TDD detection logic (scanning commit history).
- [ ] **Phase 4:** Generate reports on TDD adoption rates across Apache projects.

## 📄 License
