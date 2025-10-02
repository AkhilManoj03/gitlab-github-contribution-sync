# GitLab to GitHub Contribution Sync

Automatically sync your GitLab push events to a GitHub repository as timestamped commits, adding
your GitLab activity to your GitHub contribution graph.

## What It Does

This script fetches push events from your GitLab account and creates corresponding empty commits in
a GitHub repository with matching timestamps. This ensures your GitHub contribution graph reflects
your GitLab activity, useful for developers who work across both platforms.

**Key Features:**
- 📅 Syncs GitLab push events with accurate timestamps
- 🔄 Incremental syncing using state tracking
- 🌿 Uses temporary branches for safe merging
- 💾 Memory-efficient streaming of events
- ⚡ Automatic state management to avoid duplicate syncs

## How It Works

1. Clones the target GitHub repository
2. Reads the last sync date from a state file (or uses default: 1 year ago)
3. Fetches GitLab push events since the last sync date
4. Creates empty commits on a temporary branch with matching timestamps
5. Merges the temporary branch into the target branch
6. Updates the state file and pushes to GitHub

## Prerequisites

- Python 3.7+
- Git installed and configured
- GitLab account with API access
- GitHub repository for storing sync commits

## Environment Variables

Create a `.env` file in the project root with the following variables:

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GITLAB_USER_ID` | Your GitLab user ID | `12345678` |
| `GITLAB_URL` | GitLab instance URL | `https://gitlab.com` |
| `GITLAB_TOKEN` | GitLab personal access token with `read_api` scope | `glpat-xxxxxxxxxxxx` |
| `GITHUB_USERNAME` | Your GitHub username | `johndoe` |
| `GITHUB_REPO_NAME` | Target GitHub repository name | `gitlab-sync` |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` scope | `ghp_xxxxxxxxxxxx` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `STATE_FILE_NAME` | Name of the state file to track last sync | `last_sync_date.txt` |
| `GITHUB_BRANCH` | Target branch for commits | `main` |

### Getting API Tokens

**GitHub Token:** Read the following guide to create a GitHub personal access token with `repo`
scope: [Creating a personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

**GitLab Token:** Read the following guide to create a GitLab personal access token with `read_api`
scope: [Creating a personal access token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html)

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AkhilManoj03/gitlab-github-contribution-sync.git
   cd gitlab-github-contribution-sync
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create `.env` file:**
   ```bash
   touch .env  # Or create manually
   ```
   Then edit `.env` with your credentials.

4. **Create target GitHub repository:**
   - Create a new repository on GitHub (e.g., `gitlab-sync`)
   - Initialize it with a README or first commit
   - Make sure it matches `GITHUB_REPO_NAME` in your `.env`

## Running Locally

Simply execute the script:

```bash
python3 sync.py
```
