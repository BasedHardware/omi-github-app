"""
Test suite for OMI GitHub Issues Integration
"""
import pytest
from fastapi.testclient import TestClient
from main import app
import os


# Test client
client = TestClient(app)


class TestHealthAndBasics:
    """Test health checks and basic endpoints"""
    
    def test_health_endpoint(self):
        """Test health check endpoint returns 200"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "omi-github-issues"
    
    def test_root_endpoint_without_uid(self):
        """Test root endpoint without UID returns info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "OMI GitHub Issues Integration"
        assert data["version"] == "2.0.0"
        assert "endpoints" in data


class TestManifest:
    """Test Omi tools manifest endpoint"""
    
    def test_manifest_endpoint(self):
        """Test manifest endpoint returns tools"""
        response = client.get("/.well-known/omi-tools.json")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert len(data["tools"]) > 0
    
    def test_manifest_tools_structure(self):
        """Test each tool has required fields"""
        response = client.get("/.well-known/omi-tools.json")
        data = response.json()
        tools = data["tools"]
        
        required_fields = ["name", "description", "endpoint", "method", "parameters"]
        for tool in tools:
            for field in required_fields:
                assert field in tool, f"Tool missing field: {field}"
            
            # Verify tool names
            assert tool["name"] in [
                "create_issue", "list_repos", "list_issues", 
                "get_issue", "list_labels", "add_comment", "code_feature"
            ]


class TestChatTools:
    """Test chat tool endpoints (without authentication)"""
    
    def test_create_issue_without_uid(self):
        """Test create_issue returns error without UID"""
        response = client.post("/tools/create_issue", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "User ID is required" in data["error"]
    
    def test_create_issue_without_title(self):
        """Test create_issue returns error without title"""
        response = client.post("/tools/create_issue", json={"uid": "test-user"})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "title is required" in data["error"]
    
    def test_list_repos_without_uid(self):
        """Test list_repos returns error without UID"""
        response = client.post("/tools/list_repos", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
    
    def test_list_issues_without_uid(self):
        """Test list_issues returns error without UID"""
        response = client.post("/tools/list_issues", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
    
    def test_get_issue_without_uid(self):
        """Test get_issue returns error without UID"""
        response = client.post("/tools/get_issue", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
    
    def test_list_labels_without_uid(self):
        """Test list_labels returns error without UID"""
        response = client.post("/tools/list_labels", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
    
    def test_add_comment_without_uid(self):
        """Test add_comment returns error without UID"""
        response = client.post("/tools/add_comment", json={})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data


class TestSetupEndpoints:
    """Test setup and configuration endpoints"""
    
    def test_setup_completed_unauthenticated(self):
        """Test setup-completed returns false for new user"""
        response = client.get("/setup-completed?uid=new-test-user")
        assert response.status_code == 200
        data = response.json()
        assert "is_setup_completed" in data
        assert data["is_setup_completed"] == False
    
    def test_auth_endpoint_requires_uid(self):
        """Test auth endpoint requires UID parameter"""
        response = client.get("/auth")
        assert response.status_code == 422  # Validation error


class TestModuleImports:
    """Test that all modules can be imported"""
    
    def test_import_github_client(self):
        """Test GitHub client can be imported"""
        import github_client
        assert hasattr(github_client, 'GitHubClient')
    
    def test_import_issue_detector(self):
        """Test issue detector can be imported"""
        import issue_detector
        assert hasattr(issue_detector, 'ai_select_labels')
    
    def test_import_simple_storage(self):
        """Test simple storage can be imported"""
        import simple_storage
        assert hasattr(simple_storage, 'SimpleUserStorage')
    
    def test_import_models(self):
        """Test models can be imported"""
        import models
        assert hasattr(models, 'ChatToolResponse')


class TestEnvironment:
    """Test environment configuration"""
    
    def test_required_env_vars(self):
        """Test that environment variables are loaded"""
        # These should be loaded from .env or .env.example
        from dotenv import load_dotenv
        load_dotenv()
        
        # Check that at least some env vars exist
        assert os.getenv("APP_HOST") is not None
        assert os.getenv("APP_PORT") is not None


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
