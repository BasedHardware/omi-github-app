"""
Simple tests for the OMI GitHub Issues Integration
"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_endpoint():
    """Test the health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "omi-github-issues"


def test_root_endpoint():
    """Test the root endpoint without uid"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "OMI GitHub Issues Integration"
    assert data["version"] == "2.0.0"
    assert data["status"] == "active"


def test_omi_tools_manifest():
    """Test the OMI tools manifest endpoint"""
    response = client.get("/.well-known/omi-tools.json")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) > 0
    
    # Verify key tools exist
    tool_names = [tool["name"] for tool in data["tools"]]
    assert "create_issue" in tool_names
    assert "list_repos" in tool_names
    assert "list_issues" in tool_names
    assert "code_feature" in tool_names


def test_setup_completed_endpoint():
    """Test setup check endpoint"""
    response = client.get("/setup-completed?uid=test-user")
    assert response.status_code == 200
    data = response.json()
    assert "is_setup_completed" in data
    # Should be False for non-existent user
    assert data["is_setup_completed"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
