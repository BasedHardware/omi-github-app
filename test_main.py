"""
Unit tests for OMI GitHub Issues Integration
"""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
import json

# Set dummy environment variables before importing modules
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-testing")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-client-secret")

from main import app, get_repo_for_request
from models import ChatToolResponse


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_user():
    """Create a mock user with GitHub authentication."""
    return {
        "uid": "test-user-123",
        "access_token": "mock_token_123",
        "github_username": "testuser",
        "selected_repo": "testuser/test-repo",
        "available_repos": [
            {"full_name": "testuser/test-repo", "private": False},
            {"full_name": "testuser/private-repo", "private": True}
        ]
    }


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Test health check endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "healthy",
            "service": "omi-github-issues"
        }


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_without_uid(self, client):
        """Test root endpoint without UID returns app info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "OMI GitHub Issues Integration"
        assert data["version"] == "2.0.0"
        assert "endpoints" in data

    @patch('main.SimpleUserStorage.get_user')
    def test_root_with_unauthenticated_user(self, mock_get_user, client):
        """Test root endpoint with unauthenticated user shows auth page."""
        mock_get_user.return_value = None
        response = client.get("/?uid=test-user")
        assert response.status_code == 200
        assert "Connect GitHub Account" in response.text

    @patch('main.SimpleUserStorage.get_user')
    def test_root_with_authenticated_user(self, mock_get_user, client, mock_user):
        """Test root endpoint with authenticated user shows settings."""
        mock_get_user.return_value = mock_user
        response = client.get(f"/?uid={mock_user['uid']}")
        assert response.status_code == 200
        assert "Default Repository" in response.text
        assert mock_user["github_username"] in response.text


class TestOmiToolsManifest:
    """Tests for Omi tools manifest endpoint."""

    def test_manifest_structure(self, client):
        """Test that manifest has correct structure."""
        response = client.get("/.well-known/omi-tools.json")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)

    def test_manifest_tools(self, client):
        """Test that all expected tools are in manifest."""
        response = client.get("/.well-known/omi-tools.json")
        data = response.json()
        tools = {tool["name"] for tool in data["tools"]}
        
        expected_tools = {
            "create_issue",
            "code_feature",
            "list_repos",
            "list_issues",
            "get_issue",
            "list_labels",
            "add_comment"
        }
        assert tools == expected_tools

    def test_create_issue_tool_definition(self, client):
        """Test create_issue tool has correct definition."""
        response = client.get("/.well-known/omi-tools.json")
        data = response.json()
        
        create_issue_tool = next(
            tool for tool in data["tools"] if tool["name"] == "create_issue"
        )
        
        assert create_issue_tool["endpoint"] == "/tools/create_issue"
        assert create_issue_tool["method"] == "POST"
        assert create_issue_tool["auth_required"] is True
        assert "title" in create_issue_tool["parameters"]["required"]


class TestGetRepoForRequest:
    """Tests for get_repo_for_request helper function."""

    def test_with_repo_param(self, mock_user):
        """Test getting repo when repo parameter is provided."""
        repo, error = get_repo_for_request(mock_user, "owner/custom-repo")
        assert repo == "owner/custom-repo"
        assert error is None

    def test_with_selected_repo(self, mock_user):
        """Test getting repo from user's selected repo."""
        repo, error = get_repo_for_request(mock_user, None)
        assert repo == mock_user["selected_repo"]
        assert error is None

    def test_without_repo(self):
        """Test error when no repo is available."""
        user = {"selected_repo": None}
        repo, error = get_repo_for_request(user, None)
        assert repo is None
        assert "No repository specified" in error


class TestSetupEndpoint:
    """Tests for setup-completed endpoint."""

    @patch('main.SimpleUserStorage.is_authenticated')
    @patch('main.SimpleUserStorage.has_selected_repo')
    def test_setup_completed_true(self, mock_has_repo, mock_is_auth, client):
        """Test setup completed when user is authenticated and has repo."""
        mock_is_auth.return_value = True
        mock_has_repo.return_value = True
        
        response = client.get("/setup-completed?uid=test-user")
        assert response.status_code == 200
        assert response.json()["is_setup_completed"] is True

    @patch('main.SimpleUserStorage.is_authenticated')
    @patch('main.SimpleUserStorage.has_selected_repo')
    def test_setup_not_completed(self, mock_has_repo, mock_is_auth, client):
        """Test setup not completed when missing auth or repo."""
        mock_is_auth.return_value = True
        mock_has_repo.return_value = False
        
        response = client.get("/setup-completed?uid=test-user")
        assert response.status_code == 200
        assert response.json()["is_setup_completed"] is False


class TestUpdateRepoEndpoint:
    """Tests for update-repo endpoint."""

    @patch('main.SimpleUserStorage.update_repo_selection')
    def test_update_repo_success(self, mock_update, client):
        """Test successful repository update."""
        mock_update.return_value = True
        
        response = client.post(
            "/update-repo?uid=test-user&repo=owner/new-repo"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "owner/new-repo" in data["message"]

    @patch('main.SimpleUserStorage.update_repo_selection')
    def test_update_repo_user_not_found(self, mock_update, client):
        """Test update repo when user not found."""
        mock_update.return_value = False
        
        response = client.post(
            "/update-repo?uid=invalid-user&repo=owner/repo"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["error"]


class TestRefreshReposEndpoint:
    """Tests for refresh-repos endpoint."""

    @patch('main.github_client.list_user_repos')
    @patch('main.SimpleUserStorage.save_user')
    @patch('main.SimpleUserStorage.get_user')
    def test_refresh_repos_success(self, mock_get_user, mock_save, mock_list_repos, client, mock_user):
        """Test successful repository refresh."""
        mock_get_user.return_value = mock_user
        mock_list_repos.return_value = mock_user["available_repos"]
        
        response = client.post(f"/refresh-repos?uid={mock_user['uid']}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["repos_count"] == len(mock_user["available_repos"])

    @patch('main.SimpleUserStorage.get_user')
    def test_refresh_repos_unauthenticated(self, mock_get_user, client):
        """Test refresh repos with unauthenticated user."""
        mock_get_user.return_value = None
        
        response = client.post("/refresh-repos?uid=invalid-user")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not authenticated" in data["error"]


class TestCreateIssueTool:
    """Tests for create_issue chat tool."""

    @patch('main.github_client.create_issue')
    @patch('main.SimpleUserStorage.get_user')
    def test_create_issue_success(self, mock_get_user, mock_create_issue, client, mock_user):
        """Test successful issue creation."""
        mock_get_user.return_value = mock_user
        mock_create_issue.return_value = {
            "success": True,
            "issue_url": "https://github.com/testuser/test-repo/issues/1",
            "issue_number": 1
        }
        
        payload = {
            "uid": mock_user["uid"],
            "title": "Test Issue",
            "body": "Test description",
            "labels": [],
            "auto_labels": False
        }
        
        response = client.post("/tools/create_issue", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "Issue Created" in data.get("result", "")
        assert "#1" in data.get("result", "")

    @patch('main.SimpleUserStorage.get_user')
    def test_create_issue_missing_uid(self, mock_get_user, client):
        """Test create issue without UID."""
        payload = {
            "title": "Test Issue"
        }
        
        response = client.post("/tools/create_issue", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is not None
        assert "User ID is required" in data["error"]

    @patch('main.SimpleUserStorage.get_user')
    def test_create_issue_missing_title(self, mock_get_user, client, mock_user):
        """Test create issue without title."""
        mock_get_user.return_value = mock_user
        payload = {
            "uid": mock_user["uid"],
            "body": "Test body"
        }
        
        response = client.post("/tools/create_issue", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is not None
        assert "title is required" in data["error"]

    @patch('main.SimpleUserStorage.get_user')
    def test_create_issue_unauthenticated(self, mock_get_user, client):
        """Test create issue with unauthenticated user."""
        mock_get_user.return_value = None
        payload = {
            "uid": "invalid-user",
            "title": "Test Issue"
        }
        
        response = client.post("/tools/create_issue", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is not None
        assert "connect your GitHub account" in data["error"]


class TestListReposTool:
    """Tests for list_repos chat tool."""

    @patch('main.SimpleUserStorage.get_user')
    def test_list_repos_success(self, mock_get_user, client, mock_user):
        """Test successful repository listing."""
        mock_get_user.return_value = mock_user
        
        payload = {"uid": mock_user["uid"]}
        response = client.post("/tools/list_repos", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "Your GitHub Repositories" in data.get("result", "")
        assert "testuser/test-repo" in data.get("result", "")

    @patch('main.SimpleUserStorage.get_user')
    def test_list_repos_unauthenticated(self, mock_get_user, client):
        """Test list repos with unauthenticated user."""
        mock_get_user.return_value = None
        
        payload = {"uid": "invalid-user"}
        response = client.post("/tools/list_repos", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is not None


class TestListIssuesTool:
    """Tests for list_issues chat tool."""

    @patch('main.github_client.list_issues')
    @patch('main.SimpleUserStorage.get_user')
    def test_list_issues_success(self, mock_get_user, mock_list_issues, client, mock_user):
        """Test successful issue listing."""
        mock_get_user.return_value = mock_user
        mock_list_issues.return_value = [
            {
                "number": 1,
                "title": "Test Issue 1",
                "labels": ["bug"]
            },
            {
                "number": 2,
                "title": "Test Issue 2",
                "labels": []
            }
        ]
        
        payload = {"uid": mock_user["uid"]}
        response = client.post("/tools/list_issues", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "Test Issue 1" in data.get("result", "")
        assert "#1" in data.get("result", "")

    @patch('main.github_client.list_issues')
    @patch('main.SimpleUserStorage.get_user')
    def test_list_issues_empty(self, mock_get_user, mock_list_issues, client, mock_user):
        """Test list issues when no issues exist."""
        mock_get_user.return_value = mock_user
        mock_list_issues.return_value = []
        
        payload = {"uid": mock_user["uid"]}
        response = client.post("/tools/list_issues", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "No open issues found" in data.get("result", "")


class TestGetIssueTool:
    """Tests for get_issue chat tool."""

    @patch('main.github_client.get_issue')
    @patch('main.SimpleUserStorage.get_user')
    def test_get_issue_success(self, mock_get_user, mock_get_issue, client, mock_user):
        """Test successful issue retrieval."""
        mock_get_user.return_value = mock_user
        mock_get_issue.return_value = {
            "number": 42,
            "title": "Test Issue",
            "body": "Test description",
            "state": "open",
            "labels": ["bug"],
            "assignees": ["testuser"],
            "user": "testuser",
            "comments": 5,
            "url": "https://github.com/testuser/test-repo/issues/42"
        }
        
        payload = {
            "uid": mock_user["uid"],
            "issue_number": 42
        }
        response = client.post("/tools/get_issue", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "#42" in data.get("result", "")
        assert "Test Issue" in data.get("result", "")

    @patch('main.SimpleUserStorage.get_user')
    def test_get_issue_missing_number(self, mock_get_user, client, mock_user):
        """Test get issue without issue number."""
        mock_get_user.return_value = mock_user
        
        payload = {"uid": mock_user["uid"]}
        response = client.post("/tools/get_issue", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is not None
        assert "Issue number is required" in data["error"]


class TestAddCommentTool:
    """Tests for add_comment chat tool."""

    @patch('main.github_client.add_issue_comment')
    @patch('main.SimpleUserStorage.get_user')
    def test_add_comment_success(self, mock_get_user, mock_add_comment, client, mock_user):
        """Test successful comment addition."""
        mock_get_user.return_value = mock_user
        mock_add_comment.return_value = {"success": True}
        
        payload = {
            "uid": mock_user["uid"],
            "issue_number": 42,
            "body": "Test comment"
        }
        response = client.post("/tools/add_comment", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "Comment Added" in data.get("result", "")

    @patch('main.SimpleUserStorage.get_user')
    def test_add_comment_missing_body(self, mock_get_user, client, mock_user):
        """Test add comment without comment body."""
        mock_get_user.return_value = mock_user
        
        payload = {
            "uid": mock_user["uid"],
            "issue_number": 42
        }
        response = client.post("/tools/add_comment", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is not None
        assert "Comment body is required" in data["error"]


class TestListLabelsTool:
    """Tests for list_labels chat tool."""

    @patch('main.github_client.get_repo_labels_with_details')
    @patch('main.SimpleUserStorage.get_user')
    def test_list_labels_success(self, mock_get_user, mock_get_labels, client, mock_user):
        """Test successful label listing."""
        mock_get_user.return_value = mock_user
        mock_get_labels.return_value = [
            {"name": "bug", "description": "Something isn't working"},
            {"name": "enhancement", "description": "New feature"}
        ]
        
        payload = {"uid": mock_user["uid"]}
        response = client.post("/tools/list_labels", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("error") is None
        assert "bug" in data.get("result", "")
        assert "enhancement" in data.get("result", "")


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    @patch('main.github_client.get_authorization_url')
    def test_auth_start(self, mock_get_auth_url, client):
        """Test OAuth flow start."""
        mock_get_auth_url.return_value = "https://github.com/login/oauth/authorize?..."
        
        response = client.get("/auth?uid=test-user", follow_redirects=False)
        assert response.status_code == 307  # Redirect
        assert "github.com" in response.headers.get("location", "")

    def test_auth_callback_missing_code(self, client):
        """Test auth callback without code."""
        response = client.get("/auth/callback")
        assert response.status_code == 400
        assert "Authentication Failed" in response.text


class TestAnthropicKeyEndpoints:
    """Tests for Anthropic API key management."""

    @patch('main.SimpleUserStorage.save_anthropic_key')
    @patch('main.SimpleUserStorage.get_user')
    def test_save_anthropic_key(self, mock_get_user, mock_save_key, client, mock_user):
        """Test saving Anthropic API key."""
        mock_get_user.return_value = mock_user
        mock_save_key.return_value = True
        
        response = client.post(
            "/save-anthropic-key?uid=test-user&key=sk-ant-test123"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch('main.SimpleUserStorage.delete_anthropic_key')
    def test_delete_anthropic_key(self, mock_delete_key, client):
        """Test deleting Anthropic API key."""
        mock_delete_key.return_value = True
        
        response = client.post("/delete-anthropic-key?uid=test-user")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
