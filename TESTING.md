# Testing Guide

This document describes the test suite for the OMI GitHub Issues Integration application.

## Overview

The project includes a comprehensive test suite with **33 unit tests** covering all major functionality:

- ✅ API endpoint testing
- ✅ Chat tools functionality
- ✅ Authentication flows
- ✅ Repository management
- ✅ Error handling
- ✅ Input validation

## Running Tests

### Prerequisites

Install the test dependencies:

```bash
pip install -r requirements.txt
```

This installs:
- `pytest==7.4.3` - Testing framework
- `pytest-asyncio==0.21.1` - Async test support

### Run All Tests

```bash
pytest test_main.py -v
```

### Run Specific Test Classes

```bash
# Test health endpoint only
pytest test_main.py::TestHealthEndpoint -v

# Test create issue tool
pytest test_main.py::TestCreateIssueTool -v

# Test authentication
pytest test_main.py::TestAuthEndpoints -v
```

### Run with Coverage (optional)

```bash
pip install pytest-cov
pytest test_main.py --cov=main --cov-report=html
```

## Test Structure

### Test Classes

The test suite is organized into the following test classes:

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestHealthEndpoint` | 1 | Health check endpoint |
| `TestRootEndpoint` | 3 | Homepage and authentication UI |
| `TestOmiToolsManifest` | 3 | Chat tools manifest validation |
| `TestGetRepoForRequest` | 3 | Repository selection logic |
| `TestSetupEndpoint` | 2 | Setup completion checks |
| `TestUpdateRepoEndpoint` | 2 | Repository update functionality |
| `TestRefreshReposEndpoint` | 2 | Repository list refresh |
| `TestCreateIssueTool` | 4 | Issue creation via chat |
| `TestListReposTool` | 2 | Repository listing |
| `TestListIssuesTool` | 2 | Issue listing |
| `TestGetIssueTool` | 2 | Get issue details |
| `TestAddCommentTool` | 2 | Add comments to issues |
| `TestListLabelsTool` | 1 | List repository labels |
| `TestAuthEndpoints` | 2 | OAuth authentication flow |
| `TestAnthropicKeyEndpoints` | 2 | API key management |

**Total: 33 tests**

### Key Features Tested

#### 1. Chat Tools
- ✅ `create_issue` - Create GitHub issues with validation
- ✅ `list_repos` - List user repositories
- ✅ `list_issues` - List repository issues
- ✅ `get_issue` - Get issue details
- ✅ `add_comment` - Add comments to issues
- ✅ `list_labels` - List repository labels

#### 2. Authentication
- ✅ OAuth flow initiation
- ✅ Callback handling
- ✅ User authentication checks
- ✅ Error handling for missing credentials

#### 3. Repository Management
- ✅ Default repository selection
- ✅ Repository override via parameters
- ✅ Repository list refresh
- ✅ Error handling for missing repositories

#### 4. API Key Management
- ✅ Save Anthropic API key
- ✅ Delete Anthropic API key
- ✅ Key validation

#### 5. Error Handling
- ✅ Missing required parameters
- ✅ Unauthenticated users
- ✅ Invalid requests
- ✅ GitHub API errors

## Test Coverage

Current test coverage includes:

- **Endpoints**: All public API endpoints
- **Chat Tools**: All 7 chat tools defined in manifest
- **Authentication**: OAuth flow and session management
- **Validation**: Input validation for all tools
- **Error Cases**: Common error scenarios

## Test Data

Tests use mock objects and fixtures:

```python
@pytest.fixture
def mock_user():
    """Mock authenticated user with repositories"""
    return {
        "uid": "test-user-123",
        "access_token": "mock_token_123",
        "github_username": "testuser",
        "selected_repo": "testuser/test-repo",
        "available_repos": [...]
    }
```

## Environment Setup

Tests automatically set up required environment variables:

- `OPENAI_API_KEY` - Mock OpenAI API key
- `GITHUB_CLIENT_ID` - Mock GitHub OAuth client ID
- `GITHUB_CLIENT_SECRET` - Mock GitHub OAuth client secret

These are set to dummy values for testing purposes.

## Continuous Integration

To integrate with CI/CD pipelines (GitHub Actions, etc.):

```yaml
# .github/workflows/test.yml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest test_main.py -v
```

## Adding New Tests

When adding new features, follow this pattern:

```python
class TestNewFeature:
    """Tests for new feature."""
    
    @patch('main.some_dependency')
    def test_feature_success(self, mock_dep, client):
        """Test successful feature execution."""
        mock_dep.return_value = expected_value
        
        response = client.post("/endpoint", json={...})
        assert response.status_code == 200
        assert "expected" in response.json()
    
    def test_feature_error(self, client):
        """Test error handling."""
        response = client.post("/endpoint", json={})
        assert response.status_code == 200
        assert response.json().get("error") is not None
```

## Test Results

All 33 tests pass successfully:

```
============================= test session starts ==============================
test_main.py::TestHealthEndpoint::test_health_check PASSED               [  3%]
test_main.py::TestRootEndpoint::test_root_without_uid PASSED             [  6%]
[... 31 more tests ...]
============================== 33 passed in 0.61s ===============================
```

## Troubleshooting

### Import Errors

If you see `ModuleNotFoundError`, ensure all dependencies are installed:

```bash
pip install -r requirements.txt
```

### Environment Variable Errors

Tests should automatically set dummy environment variables. If you see errors about missing API keys, check that `test_main.py` sets them before importing `main`.

### Mock Failures

If mocks aren't working correctly, ensure you're patching the correct path:

```python
# Correct: Patch where it's used
@patch('main.SimpleUserStorage.get_user')

# Incorrect: Patching the original definition
@patch('simple_storage.SimpleUserStorage.get_user')
```

## Future Improvements

Potential enhancements to the test suite:

- [ ] Integration tests with real GitHub API (using test tokens)
- [ ] End-to-end tests for complete workflows
- [ ] Performance/load testing
- [ ] Test coverage reporting in CI
- [ ] Mutation testing for test quality validation

## Contributing

When contributing new tests:

1. Follow existing naming conventions
2. Use descriptive test names: `test_<feature>_<scenario>`
3. Add docstrings explaining what each test validates
4. Group related tests in classes
5. Mock external dependencies (GitHub API, OpenAI, etc.)
6. Ensure tests are independent and can run in any order

---

**Test Suite Version**: 1.0  
**Last Updated**: 2026-01-31  
**Maintainer**: Development Team
