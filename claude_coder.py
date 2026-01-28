"""
Claude Code integration - AI-powered coding using Anthropic API.
"""
import os
import re
import tempfile
import shutil
from typing import Optional, Dict, Any, List, Tuple
from anthropic import Anthropic
import git
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_code_with_claude(feature_description: str, repo_context: str, anthropic_key: str) -> str:
    """
    Generate code using Claude API.

    Args:
        feature_description: What the user wants to implement
        repo_context: Context about the repository (structure, files, etc.)
        anthropic_key: User's Anthropic API key

    Returns:
        Generated code/changes as a string
    """
    client = Anthropic(api_key=anthropic_key)

    prompt = f"""You are an expert software engineer. Generate code to implement the following feature:

Feature Request: {feature_description}

Repository Context:
{repo_context}

Please provide the complete code changes needed. Format your response as:

FILE: path/to/file.py
```python
# complete file contents here
```

FILE: path/to/another/file.js
```javascript
// complete file contents here
```

EXPLANATION:
What this does and why

Be specific about which files to create or modify. Include the full file contents for each file.
"""

    logger.info(f"Generating code with Claude for: {feature_description}")
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def parse_code_changes(changes: str) -> List[Tuple[str, str]]:
    """
    Parse Claude's response to extract file paths and their contents.

    Args:
        changes: Raw text from Claude with FILE: markers and code blocks

    Returns:
        List of (file_path, file_content) tuples
    """
    files = []

    # Pattern to match: FILE: path/to/file.ext followed by ```lang\ncode\n```
    pattern = r'FILE:\s*([^\n]+)\s*```(?:\w+)?\s*\n(.*?)```'

    matches = re.finditer(pattern, changes, re.DOTALL)

    for match in matches:
        file_path = match.group(1).strip()
        file_content = match.group(2)
        files.append((file_path, file_content))
        logger.info(f"Parsed file: {file_path} ({len(file_content)} chars)")

    # If no structured format found, create a simple change file
    if not files:
        logger.warning("No structured file changes found, creating CLAUDE_CHANGES.md")
        files.append(('CLAUDE_CHANGES.md', f"# Changes by Claude AI\n\n{changes}"))

    return files


def get_default_branch(repo_url: str, github_token: str) -> str:
    """
    Get the default branch of a GitHub repository.

    Args:
        repo_url: GitHub repo URL (https://github.com/owner/repo)
        github_token: GitHub access token

    Returns:
        Default branch name (e.g., 'main', 'master', 'flutterflow')
    """
    import requests

    # Extract owner/repo from URL
    parts = repo_url.replace('https://github.com/', '').split('/')
    owner, repo = parts[0], parts[1]

    url = f'https://api.github.com/repos/{owner}/{repo}'
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            default_branch = response.json().get('default_branch', 'main')
            logger.info(f"Default branch for {owner}/{repo}: {default_branch}")
            return default_branch
    except Exception as e:
        logger.error(f"Failed to get default branch: {e}")

    # Fallback to 'main'
    return 'main'


def apply_changes_to_repo(
    repo_url: str,
    branch_name: str,
    commit_message: str,
    changes: str,
    github_token: str
) -> Dict[str, Any]:
    """
    Clone repo, apply changes, commit, and push.

    Args:
        repo_url: GitHub repo URL
        branch_name: New branch name for changes
        commit_message: Commit message
        changes: Code changes to apply (from Claude)
        github_token: GitHub access token

    Returns:
        Dict with success status, branch name, and default_branch
    """
    try:
        # Get default branch first
        default_branch = get_default_branch(repo_url, github_token)

        # Create temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info(f"Cloning {repo_url} to {tmpdir}")

            # Clone repo with auth
            auth_url = repo_url.replace('https://', f'https://{github_token}@')
            repo = git.Repo.clone_from(auth_url, tmpdir, depth=1)

            logger.info(f"Creating branch: {branch_name}")

            # Create new branch from default branch
            new_branch = repo.create_head(branch_name)
            new_branch.checkout()

            # Parse changes and apply to files
            file_changes = parse_code_changes(changes)

            for file_path, file_content in file_changes:
                full_path = os.path.join(tmpdir, file_path)

                # Create directory if needed
                os.makedirs(os.path.dirname(full_path), exist_ok=True)

                # Write file
                with open(full_path, 'w') as f:
                    f.write(file_content)

                logger.info(f"Written file: {file_path}")

            # Stage all changes
            repo.git.add(A=True)

            # Check if there are changes to commit
            if repo.is_dirty() or repo.untracked_files:
                # Commit
                repo.index.commit(commit_message)
                logger.info(f"Committed changes: {commit_message}")

                # Push to remote - use branch_name string, not new_branch object
                origin = repo.remote('origin')
                logger.info(f"Pushing branch {branch_name} to remote...")
                origin.push(f"{branch_name}:{branch_name}")

                logger.info(f"Successfully pushed to branch {branch_name}")

                return {
                    'success': True,
                    'branch': branch_name,
                    'default_branch': default_branch,
                    'message': f'Pushed changes to branch {branch_name}'
                }
            else:
                logger.warning("No changes to commit")
                return {
                    'success': False,
                    'message': 'No changes were made'
                }

    except Exception as e:
        logger.error(f"Error applying changes: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Failed to apply changes: {str(e)}'
        }


def get_repo_context(repo_path: str, max_files: int = 20) -> str:
    """
    Get context about the repository structure.

    Args:
        repo_path: Path to cloned repository
        max_files: Maximum number of files to include in context

    Returns:
        String describing the repo structure
    """
    context = []
    context.append("Repository Structure:")

    file_count = 0
    for root, dirs, files in os.walk(repo_path):
        # Skip hidden and common ignored directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__']]

        level = root.replace(repo_path, '').count(os.sep)
        indent = ' ' * 2 * level
        context.append(f'{indent}{os.path.basename(root)}/')

        sub_indent = ' ' * 2 * (level + 1)
        for file in files[:5]:  # Limit files per directory
            if not file.startswith('.'):
                context.append(f'{sub_indent}{file}')
                file_count += 1
                if file_count >= max_files:
                    context.append(f'\n... and more files')
                    return '\n'.join(context)

    return '\n'.join(context)


def create_pr_with_github_api(
    owner: str,
    repo: str,
    branch: str,
    title: str,
    body: str,
    github_token: str,
    base_branch: str = 'main'
) -> Optional[str]:
    """
    Create a pull request using GitHub API.

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch with changes
        title: PR title
        body: PR description
        github_token: GitHub access token
        base_branch: Base branch to merge into (default: 'main')

    Returns:
        PR URL if successful, None otherwise
    """
    import requests

    url = f'https://api.github.com/repos/{owner}/{repo}/pulls'
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    data = {
        'title': title,
        'body': body,
        'head': branch,
        'base': base_branch
    }

    logger.info(f"Creating PR: {branch} -> {base_branch}")

    try:
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 201:
            pr_url = response.json().get('html_url')
            logger.info(f"PR created successfully: {pr_url}")
            return pr_url
        else:
            error_msg = f"Failed to create PR: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return None
    except Exception as e:
        logger.error(f"Exception creating PR: {e}", exc_info=True)
        return None
