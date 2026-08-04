from unittest import TestCase, mock

from agent import orbit_instagram_agent as orbit


class _Cookies:
    def __init__(self):
        self.values = {}

    def set(self, name, value, **_kwargs):
        self.values[name] = value


class _Response:
    def __init__(self, payload, url, status_code=200, text=""):
        self.payload = payload
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = {}

    def json(self):
        return self.payload


class _HTTPSession:
    def __init__(self):
        self.cookies = _Cookies()
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "web_profile_info" in url:
            payload = {
                "data": {
                    "user": {
                        "id": "1234567890",
                        "username": "test.account",
                    }
                }
            }
        else:
            payload = {"users": [], "next_max_id": None, "status": "ok"}
        return _Response(payload, url)


class InstagramWebSessionTests(TestCase):
    def test_session_cookie_uses_only_www_web_json_endpoints(self):
        session_id = "1234567890%3A" + ("x" * 40)
        http = _HTTPSession()
        with mock.patch.object(orbit.requests, "Session", return_value=http):
            client = orbit.web_client_from_session_id(session_id, "test.account")

        self.assertEqual(client._orbit_auth_mode, "web")
        self.assertEqual(client._orbit_user_id, "1234567890")
        self.assertEqual(http.cookies.values["sessionid"], session_id)
        called_urls = [url for url, _kwargs in http.calls]
        self.assertTrue(any("web_profile_info" in url for url in called_urls))
        self.assertTrue(any("friendships/1234567890/followers" in url for url in called_urls))
        self.assertFalse(any("graphql" in url or "i.instagram.com" in url for url in called_urls))

    def test_web_discovery_uses_second_degree_profiles(self):
        candidate = {"pk": "99", "username": "candidate"}
        profile = {
            "id": "99",
            "username": "candidate",
            "full_name": "Candidate",
            "follower_count": 500,
            "following_count": 600,
            "media_count": 20,
            "is_private": False,
            "is_verified": False,
        }

        def profile_by_username(username):
            return {"id": "55", "username": "affine"} if username == "affine" else profile

        client = mock.Mock()
        client._orbit_auth_mode = "web"
        client._orbit_user_id = "1234567890"
        client.user_id = "1234567890"
        client.profile_by_username.side_effect = profile_by_username
        client.relation_users.return_value = [candidate]

        with mock.patch.object(orbit.time, "sleep"):
            result = orbit.discover_candidates(
                client,
                seeds=[],
                own_followers=set(),
                own_following={"affine"},
                per_seed=40,
                max_candidates=10,
                automatic_seeds=["affine"],
            )

        self.assertEqual([item["username"] for item in result], ["candidate"])
        client.relation_users.assert_called_once_with("55", "followers", amount=40)
        client.profile_by_username.assert_any_call("candidate")
