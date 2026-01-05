import os
import time
import random
from multiprocessing import Manager
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from collections import defaultdict

# Internal Modules
from utilities import config
from mining.partitioner import prepare_job
from mining.worker import mine_repo
from utilities.utils import measure_time
from utilities.miner_intro import ProgressMonitor
from database.db import (
    get_java_projects_to_mine,
    get_python_projects_to_mine,
    get_cpp_projects_to_mine, 
    ensure_indexes,
    get_completed_project_names,
    mark_project_as_completed
)

class Repo_miner:
    """
    Main controller class for the repository mining programme.
    """
    def __init__(self):
        print("Fetching project list and checking existing quotas...")
        
        already_mined = get_completed_project_names()
        self.projects = []
        
        def fill_quota(candidates, language_name, target_quota=60):
            completed = [p for p in candidates if p['name'] in already_mined]
            current_count = len(completed)
            print(f"[{language_name}] Status: {current_count}/{target_quota} repositories mined.")
            
            if current_count >= target_quota:
                print(f"   -> Quota met. Skipping {language_name}.")
                return []
            
            needed = target_quota - current_count
            available = [p for p in candidates if p['name'] not in already_mined]
            count_to_take = min(len(available), needed)
            
            if count_to_take == 0:
                print(f"   -> No new candidates available for {language_name}.")
                return []
                
            print(f"   -> Queuing {count_to_take} new {language_name} repositories...")
            return random.sample(available, count_to_take)

        self.projects.extend(fill_quota(get_java_projects_to_mine(), "Java"))
        self.projects.extend(fill_quota(get_python_projects_to_mine(), "Python"))
        self.projects.extend(fill_quota(get_cpp_projects_to_mine(), "C++"))

        print(f"\n[Job Summary] Mining {len(self.projects)} new repositories in this run.\n")

    @measure_time
    def run(self):
        jobs = []
        total_projects = len(self.projects)

        # --- PHASE 1: PREPARATION (Multithreaded) ---
        print(f"[INFO] Analysing {total_projects} repositories to determine shard dates...\n")
        monitor = ProgressMonitor(total_projects, label="PREPARING SHARDS")
        monitor.start()

        with ThreadPoolExecutor(max_workers=20) as preparer:
            # Use external scheduler function
            future_to_project = {preparer.submit(prepare_job, p): p for p in self.projects}
            completed_prep = 0
            for future in as_completed(future_to_project):
                try:
                    result_jobs = future.result()
                    jobs.extend(result_jobs)
                except Exception as exc:
                    print(f"\n[WARN] Exception during preparation: {exc}")
                completed_prep += 1
                monitor.update(completed_prep)

        monitor.stop()

        if not jobs:
            print("No new projects found to mine (Quotas may be full).")
            return

        # --- PHASE 2: MINING (Multiprocessing) ---
        total_jobs = len(jobs)
        shards_remaining = defaultdict(int)
        project_errors = defaultdict(bool) 
        retry_counts = defaultdict(int)

        for j in jobs:
            p_name = j[0]
            shards_remaining[p_name] += 1

        print(f"\n[INFO] Preparation complete. Starting parallel mining with {total_jobs} segments.")
        print(f"[INFO] Worker Timeout: {config.WORKER_TIMEOUT}s | Max Retries: {config.MAX_RETRIES}")

        env_max = os.getenv("MAX_WORKERS")
        max_workers = int(env_max) if env_max and env_max.isdigit() else (os.cpu_count() or 6) * 2
        max_workers = max(1, min(total_jobs, max_workers))
        
        print(f"[INFO] Using {max_workers} worker processes\n")

        monitor = ProgressMonitor(total_jobs, label="MINING PROGRESS")
        monitor.start()
        
        with Manager() as manager:
            stop_event = manager.Event()
            
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_to_job = {}

                # 1. Submit initial jobs
                for job_args in jobs:
                    # Pass external worker function
                    f = executor.submit(mine_repo, (*job_args, stop_event))
                    future_to_job[f] = job_args

                completed_mining = 0
                
                try:
                    while future_to_job:
                        done, _ = wait(future_to_job.keys(), return_when=FIRST_COMPLETED)
                        
                        for future in done:
                            job_data = future_to_job.pop(future)
                            p_name = job_data[0]
                            
                            try:
                                result = future.result()
                                if result is None: continue

                                _, added, _, error = result
                                
                                # --- RETRY LOGIC ---
                                if error and "TIMED OUT" in str(error):
                                    retry_counts[job_data] += 1
                                    current_retries = retry_counts[job_data]
                                    
                                    # Unpack including depth
                                    p_name, url, start, end, language, depth = job_data
                                    
                                    if current_retries <= config.MAX_RETRIES:
                                        # Split Check: Retries == 2 AND Depth < Limit
                                        if current_retries == 2 and start and end and depth < config.MAX_SPLIT_DEPTH:
                                            monitor.log(f"⚠️ {p_name} TIMED OUT. Splitting (Depth {depth} -> {depth+1})...")
                                            
                                            total_duration = end - start
                                            segment_duration = total_duration / config.SUB_SHARDS
                                            current_segment_start = start
                                            
                                            for _ in range(config.SUB_SHARDS):
                                                segment_end = current_segment_start + segment_duration
                                                if segment_end > end: segment_end = end
                                                    
                                                # Create new job with INCREMENTED DEPTH
                                                new_job = (p_name, url, current_segment_start, segment_end, language, depth + 1)
                                                retry_counts[new_job] = 0
                                                
                                                f_new = executor.submit(mine_repo, (*new_job, stop_event))
                                                future_to_job[f_new] = new_job
                                                current_segment_start = segment_end

                                            shards_remaining[p_name] += config.SUB_SHARDS - 1
                                            
                                        else:
                                            # Standard Retry
                                            delay = 5 * current_retries
                                            monitor.log(f"⚠️ {p_name} TIMED OUT. Retrying ({current_retries}/{config.MAX_RETRIES})...")
                                            time.sleep(delay)
                                            
                                            new_future = executor.submit(mine_repo, (*job_data, stop_event))
                                            future_to_job[new_future] = job_data
                                        
                                        continue 
                                    else:
                                        monitor.log(f"❌ {p_name} TIMED OUT. Max retries/depth reached.")
                                        project_errors[p_name] = True
                                # -------------------

                                if added > 0:
                                    monitor.log(f"✅ {p_name}: {added} new commits mined.")
                                
                                if error and "TIMED OUT" not in str(error) and "No commits found" not in str(error):
                                    monitor.log(f"❌ {p_name}: {error}")
                                    project_errors[p_name] = True
                                
                                shards_remaining[p_name] -= 1

                                if shards_remaining[p_name] == 0:
                                    if not project_errors[p_name]:
                                        mark_project_as_completed(p_name)
                                        monitor.log(f"🏆 {p_name} FULLY COMPLETED.")
                                    else:
                                        monitor.log(f"⚠️ {p_name} finished with errors.")

                                completed_mining += 1
                                monitor.update(completed_mining)

                            except Exception as exc:
                                monitor.log(f"❌ Critical worker exception: {exc}")
                                shards_remaining[p_name] -= 1
                                completed_mining += 1
                                monitor.update(completed_mining)

                except KeyboardInterrupt:
                    monitor.stop()
                    print("\n\n🛑 STOPPING MINER! Terminating processes...")
                    stop_event.set()
                    for f in future_to_job.keys():
                        f.cancel()
            
            if monitor.running:
                monitor.stop()
        
        print("\n[DB] Optimising database indices...")
        ensure_indexes()
        print("[SUCCESS] Cycle complete.")

if __name__ == "__main__":
    miner = Repo_miner()
    miner.run()