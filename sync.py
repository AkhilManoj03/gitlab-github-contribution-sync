import dotenv
import json
import os
import shutil
import requests
import subprocess
import sys
from datetime import datetime, timedelta, UTC

dotenv.load_dotenv()

COMMITS_PER_PAGE = 100
DEFAULT_START_DATE = (
    datetime.now(UTC).replace(microsecond=0) - timedelta(days=365)
).strftime("%Y-%m-%dT%H:%M:%SZ") # Default start date is 1 year ago

# Secrets
GITLAB_USER_ID = os.getenv("GITLAB_USER_ID")
GITLAB_URL = os.getenv("GITLAB_URL")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")

# Project details
GITLAB_API_URL = f"{GITLAB_URL}/api/v4"
GITHUB_REPO_URL = f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com/{GITHUB_USERNAME}/{GITHUB_REPO_NAME}.git"
STATE_FILE = os.getenv("STATE_FILE_NAME") or "last_sync_date.txt"
HEADERS = {
    "Authorization": f"Bearer {GITLAB_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# List all required environment variables
required_vars = [
    "GITLAB_USER_ID",
    "GITLAB_URL",
    "GITLAB_TOKEN",
    "GITHUB_REPO_NAME",
    "GITHUB_TOKEN",
    "GITHUB_USERNAME",
]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    print(f"error: Missing required environment variables: {', '.join(missing)}")
    sys.exit(1)

def setup_github_repo():
    """Clones the GitHub repo if it doesn't exist, or pulls the latest changes if it does."""
    if os.path.exists(GITHUB_REPO_NAME):
        print(f"info: Repository '{GITHUB_REPO_NAME}' already exists. Pulling latest changes...")
        os.chdir(GITHUB_REPO_NAME)
        subprocess.run(['git', 'pull'], check=True)
    else:
        print(f"info: Cloning repository '{GITHUB_REPO_NAME}'...")
        subprocess.run(['git', 'clone', GITHUB_REPO_URL], check=True)
        os.chdir(GITHUB_REPO_NAME)

def get_last_sync_date():
    """
    Reads the last sync date from the state file within the repo,
    or returns the default if the file doesn't exist.
    """
    try:
        with open(STATE_FILE, 'r') as f:
            date_str = f.read().strip()
            print(f"info: Found state file. Starting sync from: {date_str}")
            return date_str
    except FileNotFoundError:
        print(
            f"info: State file '{STATE_FILE}' not found in repo. "
            f"Starting from default date (1 year ago): {DEFAULT_START_DATE}"
        )
        return DEFAULT_START_DATE

def stream_gitlab_events(since_date):
    """
    Fetches GitLab events page by page using a generator.
    Yields events one by one to save memory.
    """
    page = 1
    print(f"info: Fetching new GitLab events since {since_date}...")
    while True:
        url = (
            f"{GITLAB_API_URL}/users/{GITLAB_USER_ID}/events"
            f"?after={since_date}&per_page={COMMITS_PER_PAGE}&page={page}&action=pushed&sort=asc"
        )
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"error: Failed to fetch events: {e}")
            return

        events = response.json()
        if not events or len(events) == 0:
            print("info: No new events found.")
            break

        for event in events:
            yield event

        page += 1

def sync_events_and_update_state(events):
    """
    Creates empty commits for each event, updates the state file,
    and pushes all changes to GitHub.
    """
    last_event_date = None
    commit_count = 0

    for event in events:
        commit_id = event["id"]
        commit_date_str = event["created_at"]
        commit_date = (
            datetime.fromisoformat(
                commit_date_str.replace("Z", "+00:00")
            ).strftime("%Y-%m-%d %H:%M:%S")
        ) # Convert the commit date to a string in the format YYYY-MM-DD HH:MM:SS
        commit_env = os.environ.copy()
        commit_env['GIT_AUTHOR_DATE'] = commit_date
        commit_env['GIT_COMMITTER_DATE'] = commit_date

        try:
            subprocess.run(
                ['git', 'commit', '--allow-empty', '-m', f'GitLab event ID: {commit_id}', '--date', commit_date],
                check=True, env=commit_env, capture_output=True, text=True
            )
            last_event_date = commit_date_str
            commit_count += 1
        except subprocess.CalledProcessError as e:
            print(f"error: Failed to create commit for event {commit_id}: {e.stderr}")
            continue

    if commit_count == 0:
        print("info: No new commits to create.")
        return

    print(f"info: Created {commit_count} new commits.")
    print(f"info: Updating state file to: {last_event_date}")

    # We add one second to the next start date to avoid fetching the same last event again
    next_start_dt = datetime.fromisoformat(last_event_date.replace('Z', '+00:00')) + timedelta(seconds=1)
    # Normalize to UTC and ensure seconds precision with trailing 'Z'
    next_start_dt_utc = next_start_dt.astimezone(UTC).replace(microsecond=0)

    with open(STATE_FILE, 'w') as f:
        f.write(next_start_dt_utc.isoformat().replace('+00:00', 'Z'))

    subprocess.run(['git', 'add', STATE_FILE], check=True)
    subprocess.run(
        ['git', 'commit', '-m', f'CI: Update sync marker to {last_event_date}'],
        check=True
    )

    print("info: Pushing all changes to GitHub...")
    try:
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print("info: Sync complete!")
    except subprocess.CalledProcessError as e:
        print(f"error: Failed to push commits: {e.stderr}")

def main():
    """Main function to run the sync process."""
    original_cwd = os.getcwd()
    repo_path = os.path.join(original_cwd, GITHUB_REPO_NAME)
    try:
        setup_github_repo()
        start_date = get_last_sync_date()

        # Create the generator object with the start date
        gitlab_events = stream_gitlab_events(since_date=start_date)

        # Process the events and update the state file
        sync_events_and_update_state(gitlab_events)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        os.chdir(original_cwd)
        # Remove the local clone from the parent directory
        try:
            if os.path.isdir(repo_path):
                shutil.rmtree(repo_path)
                print(f"info: Removed local clone at: {repo_path}")
        except Exception as e:
            print(f"warn: Failed to remove local repo at {repo_path}: {e}")

if __name__ == "__main__":
    main()
