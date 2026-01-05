import os
import requests
from datetime import datetime, timedelta
from urllib.parse import urlparse

def prepare_job(project):
    """
    Calculates shards for a single project.
    Splits C++ projects into 1-year chunks (or smaller) to prevent timeouts.
    Initialises all jobs with depth=0.
    """
    jobs = []
    
    name = project.get('name')
    raw_url = project.get('repo_url') or project.get('url')
    language = project.get('language')

    if isinstance(raw_url, list) and len(raw_url) > 0:
        raw_url = raw_url[0]
    
    if not (isinstance(raw_url, str) and raw_url):
        return []

    start_year = 2000
    
    # Special handling for C++: Fetch creation date from API
    if language == 'C++':
        try:
            if raw_url:
                parsed_url = urlparse(raw_url)
                hostname = parsed_url.hostname.lower() if parsed_url.hostname else None
                if hostname in ("github.com", "www.github.com"):
                    parts = raw_url.strip("/").split("/")
                    if len(parts) >= 2:
                        owner, repo = parts[-2], parts[-1]
                        api_url = f"https://api.github.com/repos/{owner}/{repo}"
                        token = os.getenv('GITHUB_TOKEN') 
                        headers = {}
                        if token:
                            headers['Authorization'] = f'token {token}'

                        response = requests.get(api_url, headers=headers, timeout=5)
                        if response.status_code == 200:
                            data = response.json()
                            created_at = data.get("created_at")
                            if created_at:
                                start_year = int(created_at[:4])
        except Exception:
            # Fallback to default start year if API fails
            pass

        # --- LOGIC: Split by years ---
        current_date = datetime(start_year, 1, 1)
        now = datetime.now()

        while current_date < now:
            # Calculate end of this shard (1 year later)
            next_date = current_date + timedelta(days=365)
            
            # Cap the end date at 'now' so we don't mine the future
            if next_date > now:
                next_date = now

            # Tuple structure: (name, url, start, end, language, DEPTH)
            jobs.append((name, raw_url, current_date, next_date, language, 0))
            
            # Move cursor forward
            current_date = next_date
            
            # Safety break
            if current_date >= now:
                break
        # -----------------------------

    else:
        # Java/Python: Keep as one big job
        # Tuple structure: (name, url, start, end, language, DEPTH)
        jobs.append((name, raw_url, None, None, language, 0))
        
    return jobs