import time
from functools import wraps

# Decorator to measure execution time of functions
def measure_time(func):
    @wraps(func) # Preserves the metadata of the original function
    def wrapper(*args, **kwargs):
        print(f"⏱️  Starting '{func.__name__}'...")
        start_time = time.perf_counter()
        
        result = func(*args, **kwargs) # Execute the actual function
        
        end_time = time.perf_counter()
        execution_time = end_time - start_time
        print(f"✅ '{func.__name__}' finished in {execution_time:.4f} seconds.")
        return result
    return wrapper