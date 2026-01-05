import time
import requests
from functools import wraps

def measure_time(func):
    """
    Decorator to measure and print the execution time of a function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        
        if execution_time > 60:
            mins = int(execution_time // 60)
            secs = int(execution_time % 60)
            print(f"\n⏱️  Execution Time: {mins}m {secs}s")
        else:
            print(f"\n⏱️  Execution Time: {execution_time:.2f} seconds")
            
        return result
    return wrapper

def ping_target(url: str, timeout: int = 5) -> bool:
    """
    Checks if a target URL is reachable.
    Explicitly checks for Rate Limit (403/429) errors.
    """
    try:
        response = requests.head(url, timeout=timeout)
        
        # Specific check for Rate Limits or Bans
        if response.status_code in [403, 429]:
            print(f"🛑 Access Denied: {url} returned status {response.status_code}.")
            print("   (This usually means your IP or Token is Rate Limited by GitHub)")
            return False
            
        if 200 <= response.status_code < 400:
            print(f"✅ Connection verified: {url} is online.")
            return True
        else:
            print(f"⚠️ Target {url} returned unexpected status code: {response.status_code}")
            return False
            
    except requests.ConnectionError:
        print(f"❌ Connection Error: Unable to reach {url}. Check your internet connection.")
        return False
    except requests.Timeout:
        print(f"❌ Timeout: Connection to {url} timed out after {timeout}s.")
        return False
    except Exception as e:
        print(f"❌ Unexpected error pinging {url}: {e}")
        return False