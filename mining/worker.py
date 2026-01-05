import signal
import os
from tqdm import tqdm
from pydriller import Repository
from mining.components import CommitProcessor
from mining.components.file_analyser import VALID_CODE_EXTENSIONS
from utilities import config

class TimeoutException(Exception):
    """Custom exception for worker timeout."""
    pass

def timeout_handler(signum, frame):
    """Signal handler to raise a TimeoutException."""
    raise TimeoutException("Task exceeded maximum execution time.")

def clean_url(url):
    if not url: return None
    url = url.strip().rstrip('/')
    if "github.com:" in url and "github.com:443" not in url:
        url = url.replace("github.com:", "github.com/")
    return url

def mine_repo(args):
    """
    Worker function to mine a single repository (or shard of it).
    Executed in a separate process via ProcessPoolExecutor.
    """
    # Unpack args (including depth)
    project_name, raw_url, start_date, end_date, language, depth, stop_event = args
    
    # Check if we should stop early (e.g. CTRL+C)
    if stop_event.is_set(): return None

    # --- TIMEOUT SETUP ---
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(config.WORKER_TIMEOUT)
    # ---------------------

    repo_url = clean_url(raw_url)
    if not repo_url:
        signal.alarm(0) # Disable alarm
        return (project_name, 0, 0, "Skipped: Invalid or missing URL")

    try:
        year_str = f""
        if config.SHOW_WORKER_ACTIVITY:
            s_str = start_date.strftime('%Y-%m') if start_date else "START"
            e_str = end_date.strftime('%Y-%m') if end_date else "NOW"
            year_str = f"({s_str} to {e_str})"
            # Added depth logging for visibility
            tqdm.write(f"🚀 [Start] {project_name} {year_str} [{language}] (Depth: {depth})")
        
        # Initialise PyDriller with Date Partitioning (if dates provided)
        repo_obj = Repository(
            repo_url,
            since=start_date,
            to=end_date,
            only_modifications_with_file_types=list(VALID_CODE_EXTENSIONS)
        )
        
        processor = CommitProcessor(batch_size=config.BATCH_SIZE)
        new_commits_mined, initial_count = processor.process_commits(
            repo_obj, 
            project_name, 
            repo_url,
            language=language
        )
        
        if config.SHOW_WORKER_ACTIVITY:
            if new_commits_mined > 0:
                tqdm.write(f"✅ [Done] {project_name} {year_str}: {new_commits_mined} commits.")
    
        return (project_name, new_commits_mined, initial_count, None)
        
    except TimeoutException:
        return (project_name, 0, 0, "TIMED OUT")
        
    except Exception as e:
        return (project_name, 0, 0, str(e))
        
    finally:
        # Ensure the alarm is disabled once the function exits
        signal.alarm(0)