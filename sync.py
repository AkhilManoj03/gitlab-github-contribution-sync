import dotenv
import os
import requests
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Generator

dotenv.load_dotenv()

COMMITS_PER_PAGE = 100 # Max number of commits allowed by GitLab API at once
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
    "Content-Type": "application/json",
}
TARGET_BRANCH = os.getenv("GITHUB_BRANCH") or "main"

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

session = requests.Session()
session.headers.update(HEADERS)

def stream_gitlab_events(since_date: str) -> Generator[dict, None, None]:
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
            response = session.get(url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"error: Failed to fetch events: {e}")
            raise

        events = response.json()
        if not events or len(events) == 0:
            print("info: No new events found.")
            break

        for event in events:
            yield event

        page += 1

def sync_events_and_update_state(events: Generator[dict, None, None], repo_path: Path) -> int:
    """
    Creates empty commits for each event, updates the state file,
    and pushes all changes to GitHub.

    Args:
        events: Generator of GitLab events.
        repo_path: Path to the repository.
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
                [
                    'git', 'commit', '--allow-empty',
                    '-m', f'GitLab event ID: {commit_id}',
                    '--date', commit_date,
                ],
                cwd=repo_path, check=True, env=commit_env, capture_output=True, text=True,
            )
            last_event_date = commit_date_str
            commit_count += 1
        except subprocess.CalledProcessError as e:
            print(f"error: Failed to create commit for event {commit_id}: {e.stderr}")
            raise

    if commit_count == 0:
        print("info: No new commits to create.")
        return 0

    print(f"info: Created {commit_count} new commits.")
    print(f"info: Updating state file to: {last_event_date}")

    # We add one second to the next start date to avoid fetching the same last event again
    next_start_dt = datetime.fromisoformat(last_event_date.replace('Z', '+00:00')) + timedelta(seconds=1)
    # Normalize to UTC and ensure seconds precision with trailing 'Z'
    next_start_dt_utc = next_start_dt.astimezone(UTC).replace(microsecond=0)

    state_file_path = repo_path / STATE_FILE
    state_file_path.write_text(next_start_dt_utc.isoformat().replace('+00:00', 'Z'))

    subprocess.run(['git', 'add', STATE_FILE], cwd=repo_path, check=True)

    # Only commit if there are changes (exit code 1 means there are changes)
    result = subprocess.run(
        ['git', 'diff', '--cached', '--quiet'],
        cwd=repo_path, capture_output=True,
    )
    if result.returncode == 1:
        subprocess.run(
            ['git', 'commit', '-m', f'CI: Update sync marker to {last_event_date}'],
            cwd=repo_path, check=True,
        )

    return commit_count

def main() -> None:
    """Main function to run the sync process."""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir) / GITHUB_REPO_NAME
        try:
            print(f"info: Cloning repository '{GITHUB_REPO_NAME}'...")
            subprocess.run(['git', 'clone', GITHUB_REPO_URL, str(repo_path)], check=True)

            # Ensure local target branch is up to date
            try:
                subprocess.run(
                    ['git', 'fetch', 'origin'], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ['git', 'checkout', TARGET_BRANCH], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ['git', 'pull', 'origin', TARGET_BRANCH], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"error: Failed to prepare target branch '{TARGET_BRANCH}': {e.stderr}")
                raise

            # Create a unique branch for this run and switch to it
            timestamp = datetime.now(UTC).strftime('%Y%m%d%H%M%S')
            branch_name = f"sync/gitlab-{timestamp}-{uuid.uuid4().hex[:8]}"
            try:
                subprocess.run(
                    ['git', 'checkout', '-b', branch_name], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"error: Failed to create sync branch '{branch_name}': {e.stderr}")
                raise

            state_file_path = repo_path / STATE_FILE
            try:
                start_date = state_file_path.read_text().strip()
                print(f"info: Found state file. Starting sync from: {start_date}")
            except FileNotFoundError:
                print(
                    f"info: State file '{STATE_FILE}' not found in repo. "
                    f"Starting from default date (1 year ago): {DEFAULT_START_DATE}"
                )
                start_date = DEFAULT_START_DATE
            except Exception as e:
                print(f"error: Failed to read state file: {e}")
                raise

            # Create the generator object with the start date
            gitlab_events = stream_gitlab_events(since_date=start_date)

            # Process the events and update the state file (on the sync branch)
            commit_count = sync_events_and_update_state(gitlab_events, repo_path)

            # Nothing to merge
            if not commit_count:
                try:
                    subprocess.run(
                        ['git', 'checkout', TARGET_BRANCH], 
                        cwd=repo_path, check=True, capture_output=True, text=True,
                    )
                    subprocess.run(
                        ['git', 'branch', '-D', branch_name], 
                        cwd=repo_path, check=True, capture_output=True, text=True,
                    )
                except subprocess.CalledProcessError as e:
                    print(f"warn: Failed to clean up empty sync branch '{branch_name}': {e.stderr}")
                except Exception as e:
                    print(f"warn: Failed to clean up empty sync branch '{branch_name}': {e}")

            # Merge the sync branch into the target branch
            try:
                subprocess.run(
                    ['git', 'checkout', TARGET_BRANCH], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    [
                        'git', 'merge', '--no-ff', branch_name,
                        '-m', f'Merge synchronization branch {branch_name}',
                    ],
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as e:
                print(
                    f"error: Failed to merge sync branch '{branch_name}' into '{TARGET_BRANCH}': {e.stderr}"
                )
                raise

            # Push merged changes
            print("info: Pushing all changes to GitHub...")
            try:
                subprocess.run(
                    ['git', 'push', 'origin', TARGET_BRANCH], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                print("info: Sync complete!")
            except subprocess.CalledProcessError as e:
                print(f"error: Failed to push commits to '{TARGET_BRANCH}': {e.stderr}")
                raise

            # Delete the local sync branch
            try:
                subprocess.run(
                    ['git', 'branch', '-D', branch_name], 
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"warn: Failed to delete local sync branch '{branch_name}': {e.stderr}")

            print(f"info: Finished sync into target branch {TARGET_BRANCH}")
        except Exception as e:
            print(f"error: An unexpected error occurred: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
