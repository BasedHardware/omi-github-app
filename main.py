"""
OMI GitHub Issues Integration - Chat Tools Based

This app provides GitHub integration through OAuth2 authentication
and chat tools for creating and managing GitHub issues.
"""
import sys
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import os
from dotenv import load_dotenv
import secrets

from simple_storage import SimpleUserStorage
from github_client import GitHubClient
from issue_detector import ai_select_labels
from models import ChatToolResponse

load_dotenv()


def log(msg: str):
    """Print and flush immediately for Railway logging."""
    print(msg)
    sys.stdout.flush()


# Initialize services
github_client = GitHubClient()

app = FastAPI(
    title="OMI GitHub Issues Integration",
    description="GitHub issue management via Omi chat tools",
    version="2.0.0"
)

# Store OAuth states temporarily (in production, use Redis or similar)
oauth_states = {}


# ============================================
# Helper Functions
# ============================================

def get_repo_for_request(user: dict, repo_param: str = None) -> tuple[str, str]:
    """
    Get repository for a request.
    Returns (repo_full_name, error_message).
    If error_message is not None, repo_full_name will be None.
    """
    repo_full_name = repo_param or user.get("selected_repo")
    if not repo_full_name:
        return None, "No repository specified. Please set a default repository in settings or provide the 'repo' parameter (format: 'owner/repo')."
    return repo_full_name, None


# ============================================
# Chat Tools Manifest
# ============================================

@app.get("/.well-known/omi-tools.json")
async def get_omi_tools_manifest():
    """
    Omi Chat Tools Manifest endpoint.

    This endpoint returns the chat tools definitions that Omi will fetch
    when the app is created or updated in the Omi App Store.
    """
    return {
        "tools": [
            {
                "name": "create_issue",
                "description": "Create a GitHub issue in a repository. Use this when the user wants to report a bug, request a feature, create a ticket, or log feedback. The issue will be created in the user's default repository unless a different repo is specified.",
                "endpoint": "/tools/create_issue",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The issue title. Required. Keep it concise and descriptive (under 100 characters)."
                        },
                        "body": {
                            "type": "string",
                            "description": "The issue description/body. Supports markdown formatting. Include relevant details like steps to reproduce, expected behavior, etc."
                        },
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Labels to apply to the issue. If provided, must exactly match labels that exist in the repository."
                        },
                        "auto_labels": {
                            "type": "boolean",
                            "description": "If true (default), use AI to automatically select appropriate labels from the repository's available labels based on the issue content."
                        },
                        "repo": {
                            "type": "string",
                            "description": "Repository to create the issue in (format: 'owner/repo'). If not provided, uses the user's default repository."
                        }
                    },
                    "required": ["title"]
                },
                "auth_required": True,
                "status_message": "Creating GitHub issue..."
            },
            {
                "name": "code_feature",
                "description": "Implement a feature in a GitHub repository using AI. Use this when the user asks to 'code', 'implement', 'add feature', 'build', or 'create code' in a repository. This tool uses Claude AI to generate code, create a branch, and open a pull request.",
                "endpoint": "/tools/code_feature",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "feature": {
                            "type": "string",
                            "description": "Description of the feature to implement. Be specific about what needs to be built or changed."
                        },
                        "repo": {
                            "type": "string",
                            "description": "Repository to code in (format: 'owner/repo'). If not provided, uses the user's default repository."
                        }
                    },
                    "required": ["feature"]
                },
                "auth_required": True,
                "status_message": "Generating code with Claude AI..."
            },
            {
                "name": "list_repos",
                "description": "List the user's GitHub repositories. Use this when the user wants to see their repos, check which repositories they can create issues in, or find a repository name.",
                "endpoint": "/tools/list_repos",
                "method": "POST",
                "parameters": {
                    "properties": {},
                    "required": []
                },
                "auth_required": True,
                "status_message": "Getting your repositories..."
            },
            {
                "name": "list_issues",
                "description": "List recent issues in a GitHub repository. Use this when the user wants to see issues, check open bugs, view recent tickets, or find an issue number.",
                "endpoint": "/tools/list_issues",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "repo": {
                            "type": "string",
                            "description": "Repository to list issues from (format: 'owner/repo'). If not provided, uses the user's default repository."
                        },
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "description": "Filter by issue state. Defaults to 'open'."
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of issues to return (default: 10, max: 50)"
                        }
                    },
                    "required": []
                },
                "auth_required": True,
                "status_message": "Getting issues..."
            },
            {
                "name": "get_issue",
                "description": "Get details of a specific GitHub issue including title, body, labels, assignees, and state. Use this when the user wants to see issue details, check an issue's status, or read the full description.",
                "endpoint": "/tools/get_issue",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "issue_number": {
                            "type": "integer",
                            "description": "The issue number to get details for. Required."
                        },
                        "repo": {
                            "type": "string",
                            "description": "Repository the issue is in (format: 'owner/repo'). If not provided, uses the user's default repository."
                        }
                    },
                    "required": ["issue_number"]
                },
                "auth_required": True,
                "status_message": "Getting issue details..."
            },
            {
                "name": "list_labels",
                "description": "List available labels in a GitHub repository. Use this when the user wants to see what labels they can use, check available tags, or find the correct label name.",
                "endpoint": "/tools/list_labels",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "repo": {
                            "type": "string",
                            "description": "Repository to list labels from (format: 'owner/repo'). If not provided, uses the user's default repository."
                        }
                    },
                    "required": []
                },
                "auth_required": True,
                "status_message": "Getting repository labels..."
            },
            {
                "name": "add_comment",
                "description": "Add a comment to an existing GitHub issue. Use this when the user wants to comment on an issue, add information, or respond to a bug report.",
                "endpoint": "/tools/add_comment",
                "method": "POST",
                "parameters": {
                    "properties": {
                        "issue_number": {
                            "type": "integer",
                            "description": "The issue number to comment on. Required."
                        },
                        "body": {
                            "type": "string",
                            "description": "The comment text. Required. Supports markdown formatting."
                        },
                        "repo": {
                            "type": "string",
                            "description": "Repository the issue is in (format: 'owner/repo'). If not provided, uses the user's default repository."
                        }
                    },
                    "required": ["issue_number", "body"]
                },
                "auth_required": True,
                "status_message": "Adding comment..."
            }
        ]
    }


# ============================================
# Chat Tool Endpoints
# ============================================

@app.post("/tools/create_issue", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_create_issue(request: Request):
    """
    Create a GitHub issue.
    Chat tool for Omi - creates an issue in the specified or default repository.
    """
    try:
        body = await request.json()
        log(f"=== CREATE_ISSUE START ===")
        log(f"Request: {body}")

        uid = body.get("uid")
        title = body.get("title")
        issue_body = body.get("body", "")
        labels = body.get("labels", [])
        auto_labels = body.get("auto_labels", True)
        repo = body.get("repo")

        if not uid:
            return ChatToolResponse(error="User ID is required")

        if not title:
            return ChatToolResponse(error="Issue title is required")

        # Get user and validate auth
        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        # Determine repository
        repo_full_name, error = get_repo_for_request(user, repo)
        if error:
            return ChatToolResponse(error=error)

        access_token = user["access_token"]

        # Auto-select labels if enabled and no labels provided
        if auto_labels and not labels:
            repo_labels = github_client.get_repo_labels(access_token, repo_full_name)
            if repo_labels:
                log(f"Found {len(repo_labels)} labels, running AI selection...")
                labels = await ai_select_labels(title, issue_body or "", repo_labels)
                if labels:
                    log(f"AI selected labels: {labels}")

        # Add footer to issue body
        footer = "\n\n---\n*Created via Omi*"
        full_body = (issue_body + footer) if issue_body else footer.strip()

        # Create the issue
        result = await github_client.create_issue(
            access_token=access_token,
            repo_full_name=repo_full_name,
            title=title,
            body=full_body,
            labels=labels
        )

        if result and result.get("success"):
            issue_url = result.get("issue_url")
            issue_number = result.get("issue_number")

            result_parts = [
                "**Issue Created!**",
                "",
                f"**#{issue_number}** - {title}",
                f"Repository: {repo_full_name}",
            ]
            if labels:
                result_parts.append(f"Labels: {', '.join(labels)}")
            result_parts.append(f"URL: {issue_url}")

            log(f"SUCCESS: Issue #{issue_number} created")
            return ChatToolResponse(result="\n".join(result_parts))
        else:
            error = result.get("error", "Unknown error") if result else "Failed"
            log(f"ERROR: {error}")
            return ChatToolResponse(error=f"Failed to create issue: {error}")

    except Exception as e:
        import traceback
        log(f"EXCEPTION: {e}")
        log(traceback.format_exc())
        return ChatToolResponse(error=f"Failed to create issue: {str(e)}")


@app.post("/tools/list_repos", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_list_repos(request: Request):
    """
    List user's GitHub repositories.
    """
    try:
        body = await request.json()
        uid = body.get("uid")

        if not uid:
            return ChatToolResponse(error="User ID is required")

        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        repos = user.get("available_repos", [])
        if not repos:
            # Fetch fresh if not cached
            repos = github_client.list_user_repos(user["access_token"])

        if not repos:
            return ChatToolResponse(result="You don't have any repositories on GitHub.")

        default_repo = user.get("selected_repo", "")

        result_parts = [f"**Your GitHub Repositories ({len(repos)})**", ""]
        for i, repo in enumerate(repos[:20], 1):  # Limit to 20
            privacy = "Private" if repo.get("private") else "Public"
            default_marker = " (default)" if repo["full_name"] == default_repo else ""
            result_parts.append(f"{i}. **{repo['full_name']}**{default_marker} - {privacy}")

        if len(repos) > 20:
            result_parts.append(f"\n... and {len(repos) - 20} more repositories")

        return ChatToolResponse(result="\n".join(result_parts))

    except Exception as e:
        log(f"Error listing repos: {e}")
        return ChatToolResponse(error=f"Failed to list repositories: {str(e)}")


@app.post("/tools/list_issues", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_list_issues(request: Request):
    """
    List issues in a GitHub repository.
    """
    try:
        body = await request.json()
        uid = body.get("uid")
        repo = body.get("repo")
        state = body.get("state", "open")
        limit = min(body.get("limit", 10), 50)

        if not uid:
            return ChatToolResponse(error="User ID is required")

        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        repo_full_name, error = get_repo_for_request(user, repo)
        if error:
            return ChatToolResponse(error=error)

        issues = github_client.list_issues(
            access_token=user["access_token"],
            repo_full_name=repo_full_name,
            state=state,
            per_page=limit
        )

        if not issues:
            return ChatToolResponse(result=f"No {state} issues found in {repo_full_name}.")

        result_parts = [f"**{state.title()} Issues in {repo_full_name} ({len(issues)})**", ""]
        for issue in issues:
            labels_str = f" [{', '.join(issue['labels'])}]" if issue.get('labels') else ""
            result_parts.append(f"• **#{issue['number']}** - {issue['title']}{labels_str}")

        return ChatToolResponse(result="\n".join(result_parts))

    except Exception as e:
        log(f"Error listing issues: {e}")
        return ChatToolResponse(error=f"Failed to list issues: {str(e)}")


@app.post("/tools/get_issue", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_get_issue(request: Request):
    """
    Get details of a specific GitHub issue.
    """
    try:
        body = await request.json()
        uid = body.get("uid")
        issue_number = body.get("issue_number")
        repo = body.get("repo")

        if not uid:
            return ChatToolResponse(error="User ID is required")

        if not issue_number:
            return ChatToolResponse(error="Issue number is required")

        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        repo_full_name, error = get_repo_for_request(user, repo)
        if error:
            return ChatToolResponse(error=error)

        issue = github_client.get_issue(
            access_token=user["access_token"],
            repo_full_name=repo_full_name,
            issue_number=int(issue_number)
        )

        if not issue:
            return ChatToolResponse(error=f"Issue #{issue_number} not found in {repo_full_name}")

        result_parts = [
            f"**Issue #{issue['number']}** - {issue['state'].upper()}",
            "",
            f"**{issue['title']}**",
            "",
        ]

        if issue.get('body'):
            # Truncate long bodies
            body_preview = issue['body'][:500]
            if len(issue['body']) > 500:
                body_preview += "..."
            result_parts.append(body_preview)
            result_parts.append("")

        if issue.get('labels'):
            result_parts.append(f"**Labels:** {', '.join(issue['labels'])}")
        if issue.get('assignees'):
            result_parts.append(f"**Assignees:** {', '.join(issue['assignees'])}")
        result_parts.append(f"**Created by:** {issue.get('user', 'Unknown')}")
        result_parts.append(f"**Comments:** {issue.get('comments', 0)}")
        result_parts.append(f"**URL:** {issue['url']}")

        return ChatToolResponse(result="\n".join(result_parts))

    except Exception as e:
        log(f"Error getting issue: {e}")
        return ChatToolResponse(error=f"Failed to get issue: {str(e)}")


@app.post("/tools/list_labels", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_list_labels(request: Request):
    """
    List available labels in a repository.
    """
    try:
        body = await request.json()
        uid = body.get("uid")
        repo = body.get("repo")

        if not uid:
            return ChatToolResponse(error="User ID is required")

        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        repo_full_name, error = get_repo_for_request(user, repo)
        if error:
            return ChatToolResponse(error=error)

        labels = github_client.get_repo_labels_with_details(
            access_token=user["access_token"],
            repo_full_name=repo_full_name
        )

        if not labels:
            return ChatToolResponse(result=f"No labels found in {repo_full_name}.")

        result_parts = [f"**Labels in {repo_full_name} ({len(labels)})**", ""]
        for label in labels:
            desc = f" - {label['description']}" if label.get('description') else ""
            result_parts.append(f"• **{label['name']}**{desc}")

        return ChatToolResponse(result="\n".join(result_parts))

    except Exception as e:
        log(f"Error listing labels: {e}")
        return ChatToolResponse(error=f"Failed to list labels: {str(e)}")


@app.post("/tools/add_comment", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_add_comment(request: Request):
    """
    Add a comment to a GitHub issue.
    """
    try:
        body = await request.json()
        uid = body.get("uid")
        issue_number = body.get("issue_number")
        comment_body = body.get("body")
        repo = body.get("repo")

        if not uid:
            return ChatToolResponse(error="User ID is required")

        if not issue_number:
            return ChatToolResponse(error="Issue number is required")

        if not comment_body:
            return ChatToolResponse(error="Comment body is required")

        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        repo_full_name, error = get_repo_for_request(user, repo)
        if error:
            return ChatToolResponse(error=error)

        result = github_client.add_issue_comment(
            access_token=user["access_token"],
            repo_full_name=repo_full_name,
            issue_number=int(issue_number),
            body=comment_body
        )

        if result and result.get("success"):
            return ChatToolResponse(
                result=f"**Comment Added**\n\nAdded comment to issue #{issue_number} in {repo_full_name}"
            )
        else:
            error = result.get("error", "Unknown error") if result else "Failed"
            return ChatToolResponse(error=f"Failed to add comment: {error}")

    except Exception as e:
        log(f"Error adding comment: {e}")
        return ChatToolResponse(error=f"Failed to add comment: {str(e)}")


# ============================================
# OAuth & Setup Endpoints
# ============================================

@app.get("/")
async def root(uid: str = Query(None)):
    """Root endpoint - Homepage with repo selection (mobile-first UI)."""
    if not uid:
        return {
            "app": "OMI GitHub Issues Integration",
            "version": "2.0.0",
            "status": "active",
            "endpoints": {
                "auth": "/auth?uid=<user_id>",
                "setup_check": "/setup-completed?uid=<user_id>",
                "tools_manifest": "/.well-known/omi-tools.json"
            }
        }

    # Get user info
    user = SimpleUserStorage.get_user(uid)

    if not user or not user.get("access_token"):
        # Not authenticated - show auth page
        auth_url = f"/auth?uid={uid}"
        return HTMLResponse(content=f"""
        <html>
            <head>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    {get_mobile_css()}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon">🐙</div>
                    <h1>GitHub Issues</h1>
                    <p style="font-size: 18px;">Create and manage GitHub issues through Omi chat</p>

                    <a href="{auth_url}" class="btn btn-primary btn-block" style="font-size: 17px; padding: 16px;">
                        Connect GitHub Account
                    </a>

                    <div class="card">
                        <h3>How It Works</h3>
                        <div class="steps">
                            <div class="step">
                                <div class="step-number">1</div>
                                <div class="step-content">
                                    <strong>Connect</strong> your GitHub account securely
                                </div>
                            </div>
                            <div class="step">
                                <div class="step-number">2</div>
                                <div class="step-content">
                                    <strong>Select</strong> your default repository
                                </div>
                            </div>
                            <div class="step">
                                <div class="step-number">3</div>
                                <div class="step-content">
                                    <strong>Chat</strong> with Omi to create and manage issues
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <h3>What You Can Do</h3>
                        <ul style="list-style: none; padding: 0;">
                            <li style="padding: 10px 0; border-bottom: 1px solid #21262d;">
                                <strong>Create Issues</strong> - Report bugs, request features
                            </li>
                            <li style="padding: 10px 0; border-bottom: 1px solid #21262d;">
                                <strong>List Issues</strong> - View open/closed issues
                            </li>
                            <li style="padding: 10px 0; border-bottom: 1px solid #21262d;">
                                <strong>Add Comments</strong> - Respond to issues
                            </li>
                            <li style="padding: 10px 0;">
                                <strong>Auto-Labels</strong> - AI selects appropriate tags
                            </li>
                        </ul>
                    </div>

                    <div class="footer">
                        <p>Powered by <strong>Omi</strong></p>
                    </div>
                </div>
            </body>
        </html>
        """)

    # Authenticated - show repo selection page
    repos = user.get("available_repos", [])
    selected_repo = user.get("selected_repo", "")
    github_username = user.get("github_username", "Unknown")

    repo_options = ""
    for repo in repos:
        selected_attr = 'selected' if repo['full_name'] == selected_repo else ''
        privacy = "Private" if repo.get('private') else "Public"
        repo_options += f'<option value="{repo["full_name"]}" {selected_attr}>{repo["full_name"]} ({privacy})</option>'

    return HTMLResponse(content=f"""
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>GitHub Issues - Settings</title>
            <style>
                {get_mobile_css()}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card" style="margin-top: 20px;">
                    <h2>Default Repository</h2>
                    <p style="text-align: left; font-size: 14px; margin-bottom: 8px; color: #8b949e;">
                        Logged in as <span class="username">@{github_username}</span>
                    </p>
                    <p style="text-align: left; font-size: 14px; margin-bottom: 16px;">
                        Issues will be created here by default:
                    </p>

                    <select id="repoSelect" class="repo-select">
                        {repo_options if repo_options else '<option>No repositories found</option>'}
                    </select>

                    <button class="btn btn-primary btn-block" onclick="updateRepo()">
                        Save Repository
                    </button>
                    <button class="btn btn-secondary btn-block" onclick="refreshRepos()">
                        Refresh Repositories
                    </button>
                </div>

                <div class="card">
                    <h3>Claude Code Settings</h3>
                    <p style="text-align: left; font-size: 14px; margin-bottom: 16px;">
                        Add your Anthropic API key to enable AI coding features through chat
                    </p>

                    <input type="password"
                           id="anthropicKey"
                           placeholder="sk-ant-..."
                           style="width: 100%; padding: 12px; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 14px; margin-bottom: 12px;"
                           value="{user.get('anthropic_key', '')[:10] + '...' if user.get('anthropic_key') else ''}">

                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-primary" onclick="saveAnthropicKey()" style="flex: 1;">
                            Save API Key
                        </button>
                        <button class="btn btn-secondary" onclick="deleteAnthropicKey()">
                            Remove
                        </button>
                    </div>

                    <p style="text-align: left; font-size: 12px; color: #8b949e; margin-top: 12px;">
                        Get your API key from <a href="https://console.anthropic.com/" target="_blank" style="color: #58a6ff;">console.anthropic.com</a>
                    </p>
                </div>

                <div class="card">
                    <h3>Using Chat Commands</h3>
                    <p style="text-align: left; margin-bottom: 16px;">
                        Just chat with Omi naturally:
                    </p>
                    <div class="example">
                        "Create an issue for the login bug"
                    </div>
                    <div class="example">
                        "Show me recent issues"
                    </div>
                    <div class="example">
                        "Add a comment to issue #42"
                    </div>
                </div>

                <div class="card">
                    <h3>Tips</h3>
                    <ul style="list-style: none; padding: 0;">
                        <li style="padding: 8px 0;">
                            <strong>Be specific</strong> - Include details in issue descriptions
                        </li>
                        <li style="padding: 8px 0;">
                            <strong>Auto-labels</strong> - AI picks relevant labels automatically
                        </li>
                        <li style="padding: 8px 0;">
                            <strong>Different repos</strong> - Specify repo name to override default
                        </li>
                    </ul>
                </div>

                <div class="footer">
                    <p>Powered by <strong>Omi</strong></p>
                </div>
            </div>

            <script>
                async function updateRepo() {{
                    const select = document.getElementById('repoSelect');
                    const repo = select.value;

                    if (!repo || repo === 'No repositories found') {{
                        alert('Please select a valid repository');
                        return;
                    }}

                    try {{
                        const response = await fetch('/update-repo?uid={uid}&repo=' + encodeURIComponent(repo), {{
                            method: 'POST'
                        }});

                        const data = await response.json();

                        if (data.success) {{
                            alert('Repository updated successfully!');
                        }} else {{
                            alert('Failed to update: ' + data.error);
                        }}
                    }} catch (error) {{
                        alert('Error: ' + error.message);
                    }}
                }}

                async function refreshRepos() {{
                    if (!confirm('Refresh your repository list from GitHub?')) return;

                    try {{
                        const response = await fetch('/refresh-repos?uid={uid}', {{
                            method: 'POST'
                        }});

                        const data = await response.json();

                        if (data.success) {{
                            alert('Repositories refreshed! Reloading page...');
                            window.location.reload();
                        }} else {{
                            alert('Failed to refresh: ' + data.error);
                        }}
                    }} catch (error) {{
                        alert('Error: ' + error.message);
                    }}
                }}

                async function saveAnthropicKey() {{
                    const keyInput = document.getElementById('anthropicKey');
                    const apiKey = keyInput.value.trim();

                    if (!apiKey) {{
                        alert('Please enter an API key');
                        return;
                    }}

                    if (!apiKey.startsWith('sk-ant-')) {{
                        alert('Invalid API key format. Should start with sk-ant-');
                        return;
                    }}

                    try {{
                        // Save locally first
                        await fetch('/save-anthropic-key?uid={uid}&key=' + encodeURIComponent(apiKey), {{
                            method: 'POST'
                        }});

                        alert('Anthropic API key saved successfully!');
                    }} catch (error) {{
                        alert('Error: ' + error.message);
                    }}
                }}

                async function deleteAnthropicKey() {{
                    if (!confirm('Remove your Anthropic API key?')) return;

                    try {{
                        await fetch('/delete-anthropic-key?uid={uid}', {{
                            method: 'POST'
                        }});

                        document.getElementById('anthropicKey').value = '';
                        alert('API key removed successfully!');
                    }} catch (error) {{
                        alert('Error: ' + error.message);
                    }}
                }}
            </script>
        </body>
    </html>
    """)


@app.get("/auth")
async def auth_start(uid: str = Query(..., description="User ID from OMI")):
    """Start OAuth flow for GitHub authentication."""
    redirect_uri = os.getenv("OAUTH_REDIRECT_URL", "http://localhost:8000/auth/callback")

    try:
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        oauth_states[state] = uid

        # Get authorization URL
        auth_url = github_client.get_authorization_url(redirect_uri, state)

        return RedirectResponse(url=auth_url)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OAuth initialization failed: {str(e)}")


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None)
):
    """Handle OAuth callback from GitHub."""
    if not code or not state:
        return HTMLResponse(
            content=f"""
            <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>{get_mobile_css()}</style>
                </head>
                <body>
                    <div class="container">
                        <div class="error-box" style="margin-top: 40px; padding: 40px 24px;">
                            <h2 style="font-size: 24px; margin-bottom: 12px;">Authentication Failed</h2>
                            <p style="margin-bottom: 0;">Authorization code not received. Please try again.</p>
                        </div>
                    </div>
                </body>
            </html>
            """,
            status_code=400
        )

    # Verify state and get uid
    uid = oauth_states.get(state)
    if not uid:
        return HTMLResponse(
            content=f"""
            <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>{get_mobile_css()}</style>
                </head>
                <body>
                    <div class="container">
                        <div class="error-box" style="margin-top: 40px; padding: 40px 24px;">
                            <h2 style="font-size: 24px; margin-bottom: 12px;">Invalid State</h2>
                            <p style="margin-bottom: 0;">OAuth state mismatch. Please try again.</p>
                        </div>
                    </div>
                </body>
            </html>
            """,
            status_code=400
        )

    try:
        # Exchange code for access token
        token_data = github_client.exchange_code_for_token(code)
        access_token = token_data.get("access_token")

        # Get user info
        user_info = github_client.get_user_info(access_token)
        github_username = user_info.get("login", "Unknown")

        # Get user's repositories
        repos = github_client.list_user_repos(access_token)

        # Save user data
        SimpleUserStorage.save_user(
            uid=uid,
            access_token=access_token,
            github_username=github_username,
            selected_repo=repos[0]["full_name"] if repos else None,
            available_repos=repos
        )

        # Clean up state
        if state in oauth_states:
            del oauth_states[state]

        return HTMLResponse(
            content=f"""
            <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <title>Connected Successfully!</title>
                    <style>
                        {get_mobile_css()}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="success-box" style="padding: 40px 24px;">
                            <div class="icon" style="font-size: 72px;">🎉</div>
                            <h2 style="font-size: 28px; margin: 16px 0;">Successfully Connected!</h2>
                            <p style="font-size: 17px; margin: 12px 0;">
                                Your GitHub account <strong>@{github_username}</strong> is now linked
                            </p>
                            <p style="font-size: 16px; margin: 8px 0;">
                                Found <strong>{len(repos)}</strong> {('repository' if len(repos) == 1 else 'repositories')}
                            </p>
                        </div>

                        <a href="/?uid={uid}" class="btn btn-primary btn-block" style="font-size: 17px; padding: 16px; margin-top: 24px;">
                            Continue to Settings
                        </a>

                        <div class="card" style="margin-top: 20px; text-align: center;">
                            <h3>Ready to Go!</h3>
                            <p style="font-size: 16px; line-height: 1.8;">
                                You can now manage GitHub issues by chatting with Omi.
                                <br><br>
                                Try saying:<br>
                                <strong>"Create an issue for..."</strong> or
                                <strong>"Show me open issues"</strong>
                            </p>
                        </div>
                    </div>
                </body>
            </html>
            """
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(
            content=f"""
            <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>{get_mobile_css()}</style>
                </head>
                <body>
                    <div class="container">
                        <div class="error-box" style="margin-top: 40px; padding: 40px 24px;">
                            <h2 style="font-size: 24px; margin-bottom: 12px;">Authentication Error</h2>
                            <p style="margin-bottom: 16px;">Failed to complete authentication: {str(e)}</p>
                            <a href="/auth?uid={uid}" class="btn btn-primary">Try again</a>
                        </div>
                    </div>
                </body>
            </html>
            """,
            status_code=500
        )


@app.get("/setup-completed")
async def check_setup(uid: str = Query(..., description="User ID from OMI")):
    """Check if user has completed setup (authenticated with GitHub)."""
    is_authenticated = SimpleUserStorage.is_authenticated(uid)
    has_repo = SimpleUserStorage.has_selected_repo(uid)

    return {
        "is_setup_completed": is_authenticated and has_repo
    }


@app.post("/update-repo")
async def update_repo(
    uid: str = Query(...),
    repo: str = Query(...)
):
    """Update user's selected repository."""
    try:
        success = SimpleUserStorage.update_repo_selection(uid, repo)
        if success:
            return {"success": True, "message": f"Repository updated to {repo}"}
        else:
            return {"success": False, "error": "User not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/refresh-repos")
async def refresh_repos(uid: str = Query(...)):
    """Refresh user's repository list from GitHub."""
    try:
        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return {"success": False, "error": "User not authenticated"}

        # Fetch fresh repo list
        repos = github_client.list_user_repos(user["access_token"])

        # Update storage
        SimpleUserStorage.save_user(
            uid=uid,
            access_token=user["access_token"],
            github_username=user.get("github_username"),
            selected_repo=user.get("selected_repo"),
            available_repos=repos
        )

        return {"success": True, "repos_count": len(repos)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/get-anthropic-key")
async def get_anthropic_key(uid: str = Query(...)):
    """Get user's Anthropic API key."""
    try:
        key = SimpleUserStorage.get_anthropic_key(uid)
        if key:
            return {"success": True, "key": key}
        else:
            return {"success": False, "error": "No key found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/save-anthropic-key")
async def save_anthropic_key(
    uid: str = Query(...),
    key: str = Query(...)
):
    """Save user's Anthropic API key."""
    try:
        # Create user if doesn't exist
        user = SimpleUserStorage.get_user(uid)
        if not user:
            SimpleUserStorage.save_user(uid=uid, access_token="", github_username="", selected_repo="", available_repos=[])

        success = SimpleUserStorage.save_anthropic_key(uid, key)
        if success:
            return {"success": True, "message": "Anthropic API key saved"}
        else:
            return {"success": False, "error": "Failed to save"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/delete-anthropic-key")
async def delete_anthropic_key(uid: str = Query(...)):
    """Delete user's Anthropic API key."""
    try:
        success = SimpleUserStorage.delete_anthropic_key(uid)
        if success:
            return {"success": True, "message": "Anthropic API key deleted"}
        else:
            return {"success": False, "error": "Key not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/tools/code_feature", tags=["chat_tools"], response_model=ChatToolResponse)
async def tool_code_feature(request: Request):
    """
    AI-powered coding tool - implement features using Claude.
    """
    try:
        body = await request.json()
        uid = body.get("uid")
        feature = body.get("feature")
        repo = body.get("repo")  # Optional: owner/repo format

        if not uid or not feature:
            return ChatToolResponse(error="User ID and feature description are required")

        user = SimpleUserStorage.get_user(uid)
        if not user or not user.get("access_token"):
            return ChatToolResponse(
                error="Please connect your GitHub account first in the app settings."
            )

        # Get Anthropic API key
        anthropic_key = SimpleUserStorage.get_anthropic_key(uid)
        if not anthropic_key:
            return ChatToolResponse(
                error="Please add your Anthropic API key in GitHub settings at https://omi-github.up.railway.app"
            )

        # Determine target repository
        repo_full_name = repo or user.get("selected_repo")
        if not repo_full_name:
            return ChatToolResponse(
                error="No repository specified. Please set a default repository in settings."
            )

        # Start coding session
        from claude_coder import (
            generate_code_with_claude,
            create_pr_with_github_api,
            get_repo_context_via_api,
            get_default_branch,
            parse_code_changes,
            create_or_update_files_via_api
        )
        import time

        owner, repo_name = repo_full_name.split('/')
        branch_name = f"claude-code-{int(time.time())}"

        # Get repo context via API (no git clone needed)
        log(f"Getting repository context for {repo_full_name}")
        repo_context = get_repo_context_via_api(owner, repo_name, user["access_token"])

        # Get default branch
        default_branch = get_default_branch(owner, repo_name, user["access_token"])
        log(f"Default branch: {default_branch}")

        # Generate code with Claude
        log(f"Generating code for: {feature}")
        code_changes = generate_code_with_claude(feature, repo_context, anthropic_key)

        # Parse the code changes
        log(f"Parsing code changes...")
        files = parse_code_changes(code_changes)
        log(f"Parsed {len(files)} files")

        # Apply changes via GitHub API
        log(f"Creating branch and committing files to {repo_full_name}")
        commit_message = f"feat: {feature}\n\nGenerated by Claude AI via Omi"

        result = create_or_update_files_via_api(
            owner=owner,
            repo=repo_name,
            branch_name=branch_name,
            files=files,
            commit_message=commit_message,
            github_token=user["access_token"],
            base_branch=default_branch
        )

        if not result.get('success'):
            return ChatToolResponse(error=f"Failed to apply changes: {result.get('message')}")

        log(f"Successfully created branch {branch_name}")

        # Create pull request
        pr_title = f"AI: {feature[:60]}"
        pr_body = f"""## Feature Request
{feature}

## AI Generated Changes

{code_changes[:500]}...

---
*Generated by Claude AI via Omi*
"""

        pr_url = create_pr_with_github_api(
            owner=owner,
            repo=repo_name,
            branch=branch_name,
            title=pr_title,
            body=pr_body,
            github_token=user["access_token"],
            base_branch=default_branch
        )

        if pr_url:
            return ChatToolResponse(
                result=f"✅ **Feature implemented!**\n\n**Pull Request:** {pr_url}\n\nReview the AI-generated code and merge when ready."
            )
        else:
            return ChatToolResponse(
                error=f"Code pushed to branch `{branch_name}` but failed to create PR. You can manually create it on GitHub."
            )

    except Exception as e:
        import traceback
        log(f"Error in code_feature tool: {e}")
        log(traceback.format_exc())
        return ChatToolResponse(error=f"Failed to implement feature: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "omi-github-issues"}


# ============================================
# CSS Styles
# ============================================

def get_mobile_css() -> str:
    """Returns GitHub dark theme inspired CSS styles."""
    return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
            padding: 20px;
            line-height: 1.6;
        }

        .container {
            max-width: 650px;
            margin: 0 auto;
        }

        .icon {
            font-size: 64px;
            text-align: center;
            margin-bottom: 20px;
        }

        h1 {
            color: #c9d1d9;
            font-size: 32px;
            font-weight: 600;
            text-align: center;
            margin-bottom: 12px;
        }

        h2 {
            color: #c9d1d9;
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 15px;
            border-bottom: 1px solid #21262d;
            padding-bottom: 10px;
        }

        h3 {
            color: #c9d1d9;
            font-size: 19px;
            font-weight: 600;
            margin-bottom: 12px;
        }

        p {
            color: #8b949e;
            text-align: center;
            margin-bottom: 24px;
            font-size: 16px;
        }

        .username {
            color: #58a6ff;
            font-weight: 600;
            font-size: 18px;
        }

        .card {
            background: #161b22;
            border-radius: 6px;
            padding: 24px;
            margin-bottom: 16px;
            border: 1px solid #30363d;
        }

        .btn {
            display: inline-block;
            padding: 9px 20px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
            font-size: 14px;
            border: 1px solid;
            cursor: pointer;
            transition: all 0.2s ease-in-out;
            margin: 8px 8px 8px 0;
            text-align: center;
            line-height: 20px;
        }

        .btn-primary {
            background: #238636;
            color: #ffffff;
            border-color: #238636;
        }

        .btn-primary:hover {
            background: #2ea043;
            border-color: #2ea043;
        }

        .btn-secondary {
            background: transparent;
            color: #c9d1d9;
            border-color: #30363d;
        }

        .btn-secondary:hover {
            background: #30363d;
            border-color: #8b949e;
        }

        .btn-block {
            display: block;
            width: 100%;
            text-align: center;
        }

        .repo-select {
            width: 100%;
            padding: 9px 12px;
            border: 1px solid #30363d;
            border-radius: 6px;
            font-size: 14px;
            margin-bottom: 18px;
            font-family: inherit;
            background: #0d1117;
            color: #c9d1d9;
            cursor: pointer;
        }

        .repo-select:focus {
            outline: none;
            border-color: #58a6ff;
            box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.3);
        }

        .steps {
            margin: 20px 0;
        }

        .step {
            display: flex;
            margin: 18px 0;
            align-items: flex-start;
            padding: 12px;
            border-radius: 6px;
        }

        .step-number {
            background: #238636;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            margin-right: 14px;
            flex-shrink: 0;
            font-size: 14px;
        }

        .step-content {
            flex: 1;
            padding-top: 4px;
            font-size: 14px;
            line-height: 1.6;
            color: #8b949e;
        }

        .step-content strong {
            color: #c9d1d9;
        }

        .example {
            background: #0d1117;
            padding: 12px 16px;
            border-radius: 6px;
            margin: 8px 0;
            font-size: 14px;
            border: 1px solid #30363d;
            color: #8b949e;
            font-style: italic;
        }

        .success-box {
            background: rgba(35, 134, 54, 0.15);
            color: #3fb950;
            padding: 24px;
            border-radius: 6px;
            margin: 18px 0;
            text-align: center;
            border: 1px solid #238636;
        }

        .error-box {
            background: rgba(248, 81, 73, 0.15);
            color: #f85149;
            padding: 18px;
            border-radius: 6px;
            margin: 14px 0;
            border: 1px solid #f85149;
        }

        ul {
            margin-left: 20px;
        }

        li {
            margin: 8px 0;
            color: #8b949e;
        }

        strong {
            color: #c9d1d9;
            font-weight: 600;
        }

        .footer {
            text-align: center;
            color: #8b949e;
            margin-top: 40px;
            padding: 20px;
            font-size: 14px;
            border-top: 1px solid #21262d;
        }

        .footer strong {
            color: #58a6ff;
        }

        @media (max-width: 480px) {
            body {
                padding: 12px;
            }

            .card {
                padding: 18px;
            }

            h1 {
                font-size: 26px;
            }

            .btn {
                display: block;
                width: 100%;
                margin: 10px 0;
            }

            .icon {
                font-size: 52px;
            }
        }
    """


# ============================================
# Main Entry Point
# ============================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    host = os.getenv("APP_HOST", "0.0.0.0")

    print("OMI GitHub Issues Integration (Chat Tools)")
    print("=" * 50)
    print("Using file-based storage")
    print(f"Starting on {host}:{port}")
    print("=" * 50)

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True
    )
