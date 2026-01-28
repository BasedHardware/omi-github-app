"""
Claude Code integration - AI-powered coding using Anthropic API.
"""
import os
import tempfile
import shutil
from typing import Optional, Dict, Any
from anthropic import Anthropic
import git


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

Please provide:
1. The complete code changes needed
2. Which files to modify/create
3. Clear explanations of what you changed

Format your response as:
FILE: path/to/file.py
```python
# code here
```

EXPLANATION:
What this does and why
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


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
        Dict with success status and branch name
    """
    # Create temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Clone repo with auth
        auth_url = repo_url.replace('https://', f'https://{github_token}@')
        repo = git.Repo.clone_from(auth_url, tmpdir)

        # Create new branch
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()

        # Parse changes and apply to files
        # TODO: Parse the Claude response and write to actual files
        # For now, create a simple file with the changes
        changes_file = os.path.join(tmpdir, 'CLAUDE_CHANGES.md')
        with open(changes_file, 'w') as f:
            f.write(f"# Changes by Claude AI\n\n{changes}")

        # Stage all changes
        repo.git.add(A=True)

        # Commit
        repo.index.commit(commit_message)

        # Push to remote
        origin = repo.remote('origin')
        origin.push(new_branch)

        return {
            'success': True,
            'branch': branch_name,
            'message': f'Pushed changes to branch {branch_name}'
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
    github_token: str
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
        'base': 'main'  # or 'master' depending on repo
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 201:
        return response.json().get('html_url')
    else:
        print(f"Failed to create PR: {response.status_code} - {response.text}")
        return None
