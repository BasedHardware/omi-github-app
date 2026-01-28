"""
Simple storage with file persistence - survives server restarts!
Stores user OAuth tokens and selected repositories.
"""
from typing import Dict, Optional
from datetime import datetime
import json
import os

# Storage file paths - use /app/data for Railway persistence
STORAGE_DIR = os.getenv("STORAGE_DIR", os.path.dirname(os.path.abspath(__file__)))
# Check if we're on Railway (has /app/data volume)
if os.path.exists("/app/data"):
    STORAGE_DIR = "/app/data"
    print(f"Using persistent storage at: /app/data", flush=True)
else:
    STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))
    print(f"Using local storage at: {STORAGE_DIR}", flush=True)

USERS_FILE = os.path.join(STORAGE_DIR, "users_data.json")

# In-memory storage
users: Dict[str, dict] = {}


def load_storage():
    """Load user data from file on startup."""
    global users
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r') as f:
                users = json.load(f)
                print(f"Loaded {len(users)} users from storage")
    except Exception as e:
        print(f"Could not load users: {e}")


def save_users():
    """Save user data to file."""
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, default=str, indent=2)
    except Exception as e:
        print(f"Could not save users: {e}")


# Load on module import
load_storage()


class SimpleUserStorage:
    """Store user OAuth tokens and repository preferences."""

    @staticmethod
    def save_user(
        uid: str,
        access_token: str,
        github_username: Optional[str] = None,
        selected_repo: Optional[str] = None,
        available_repos: Optional[list] = None
    ):
        """Save or update user data."""
        if uid not in users:
            users[uid] = {
                "uid": uid,
                "created_at": datetime.utcnow().isoformat()
            }

        users[uid].update({
            "access_token": access_token,
            "updated_at": datetime.utcnow().isoformat()
        })

        if github_username:
            users[uid]["github_username"] = github_username
        if selected_repo:
            users[uid]["selected_repo"] = selected_repo
        if available_repos is not None:
            users[uid]["available_repos"] = available_repos

        save_users()
        print(f"Saved data for user {uid[:10]}...")

    @staticmethod
    def update_repo_selection(uid: str, selected_repo: str):
        """Update user's selected repository."""
        if uid in users:
            users[uid]["selected_repo"] = selected_repo
            users[uid]["updated_at"] = datetime.utcnow().isoformat()
            save_users()
            print(f"Updated repo for {uid[:10]}... to {selected_repo}")
            return True
        return False

    @staticmethod
    def get_user(uid: str) -> Optional[dict]:
        """Get user by uid."""
        return users.get(uid)

    @staticmethod
    def is_authenticated(uid: str) -> bool:
        """Check if user is authenticated."""
        user = users.get(uid)
        return user is not None and user.get("access_token") is not None

    @staticmethod
    def has_selected_repo(uid: str) -> bool:
        """Check if user has selected a repository."""
        user = users.get(uid)
        return user is not None and user.get("selected_repo") is not None

    @staticmethod
    def save_anthropic_key(uid: str, anthropic_key: str):
        """Save user's Anthropic API key."""
        if uid in users:
            users[uid]["anthropic_key"] = anthropic_key
            users[uid]["updated_at"] = datetime.utcnow().isoformat()
            save_users()
            print(f"Saved Anthropic key for {uid[:10]}...")
            return True
        return False

    @staticmethod
    def get_anthropic_key(uid: str) -> Optional[str]:
        """Get user's Anthropic API key."""
        user = users.get(uid)
        return user.get("anthropic_key") if user else None

    @staticmethod
    def delete_anthropic_key(uid: str):
        """Delete user's Anthropic API key."""
        if uid in users and "anthropic_key" in users[uid]:
            del users[uid]["anthropic_key"]
            users[uid]["updated_at"] = datetime.utcnow().isoformat()
            save_users()
            print(f"Deleted Anthropic key for {uid[:10]}...")
            return True
        return False
