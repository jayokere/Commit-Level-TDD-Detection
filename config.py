import os

# --- DATABASE CONFIG ---
# The number of commits to hold in memory before performing a bulk write to MongoDB.
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "250")) 

# --- WORKER CONFIG ---
# Whether to print per-worker activity logs.
SHOW_WORKER_ACTIVITY = os.getenv("SHOW_WORKER_ACTIVITY", "0") == "1"

# Hard timeout for a single worker task (in seconds). Default: 45 minutes.
WORKER_TIMEOUT = int(os.getenv("WORKER_TIMEOUT", "2700"))

# --- ORCHESTRATION CONFIG ---
# Maximum number of times to retry a shard if it times out.
MAX_RETRIES = 3
# Number of sub-shards to create when splitting a failed job
SUB_SHARDS = 12
# Maximum depth for splitting shards (prevents infinite loops)
MAX_SPLIT_DEPTH = 3