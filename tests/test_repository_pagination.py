import json
import unittest
from unittest.mock import patch

import requests

with patch("dotenv.load_dotenv"):
    from github_client import GitHubClient


def repository(number):
    return {
        "name": f"repo-{number}",
        "full_name": f"example/repo-{number}",
        "owner": {"login": "example"},
        "private": True,
        "description": None,
        "html_url": f"https://github.com/example/repo-{number}",
    }


def response(items, next_page=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(items).encode()
    if next_page:
        result.headers["Link"] = (
            f'<https://api.github.com/user/repos?page={next_page}>; rel="next"'
        )
    return result


class RepositoryPaginationTests(unittest.TestCase):
    def setUp(self):
        self.client = GitHubClient()

    @patch("github_client.requests.get")
    def test_repository_101_is_available(self, get):
        get.side_effect = [
            response([repository(i) for i in range(100)], next_page=2),
            response([repository(100)]),
        ]
        repos = self.client.list_user_repos("test-token")
        self.assertEqual(len(repos), 101)
        self.assertEqual(repos[-1]["full_name"], "example/repo-100")
        self.assertEqual(repos[-1]["owner"], "example")
        self.assertTrue(repos[-1]["private"])
        self.assertIsNone(repos[-1]["description"])
        self.assertEqual(get.call_count, 2)

    @patch("github_client.requests.get")
    def test_custom_page_size_and_three_pages(self, get):
        get.side_effect = [
            response([repository(1)], next_page=2),
            response([repository(2)], next_page=3),
            response([repository(3)]),
        ]
        repos = self.client.list_user_repos("test-token", per_page=1)
        self.assertEqual([r["name"] for r in repos], ["repo-1", "repo-2", "repo-3"])
        self.assertEqual([c.kwargs["params"]["page"] for c in get.call_args_list], [1, 2, 3])
        for call in get.call_args_list:
            self.assertEqual(call.args[0], "https://api.github.com/user/repos")
            self.assertEqual(call.kwargs["params"]["per_page"], 1)
            self.assertEqual(call.kwargs["params"]["sort"], "updated")
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-token")

    @patch("github_client.requests.get")
    def test_single_full_page_does_not_request_another_without_next_link(self, get):
        get.return_value = response([repository(1)])
        self.assertEqual(len(self.client.list_user_repos("test-token", per_page=1)), 1)
        get.assert_called_once()

    @patch("github_client.requests.get")
    def test_empty_account(self, get):
        get.return_value = response([])
        self.assertEqual(self.client.list_user_repos("test-token"), [])
        get.assert_called_once()

    @patch("github_client.requests.get")
    def test_later_page_error_does_not_return_incomplete_list(self, get):
        get.side_effect = [
            response([repository(1)], next_page=2),
            response({"message": "rate limited"}, status=403),
        ]
        self.assertEqual(self.client.list_user_repos("test-token"), [])
        self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
