import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

from agent import orbit_instagram_agent as orbit


class _Cookies:
    def __init__(self):
        self.values = {}

    def set(self, name, value, **_kwargs):
        self.values[name] = value


class _Response:
    def __init__(self, payload, url, status_code=200, text="", headers=None):
        self.payload = payload
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

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
    def test_gateway_uses_both_agent_and_sites_tokens(self):
        headers = orbit.gateway_headers(
            {
                "ORBIT_AGENT_TOKEN": "agent-secret",
                "ORBIT_SIWC_BYPASS_TOKEN": "sites-secret",
            }
        )

        self.assertEqual(headers["Authorization"], "Bearer agent-secret")
        self.assertEqual(headers["OAI-Sites-Authorization"], "Bearer sites-secret")

    def test_config_reader_accepts_windows_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.agent"
            path.write_text(
                "ORBIT_DASHBOARD_URL=https://example.test\nORBIT_AGENT_TOKEN=secret\n",
                encoding="utf-8-sig",
            )
            config = orbit.load_config(path)

        self.assertEqual(config["ORBIT_DASHBOARD_URL"], "https://example.test")
        self.assertEqual(config["ORBIT_AGENT_TOKEN"], "secret")

    def test_session_cookie_is_saved_without_hitting_rate_limited_endpoints(self):
        session_id = "1234567890%3A" + ("x" * 40)
        http = _HTTPSession()
        with mock.patch.object(orbit.requests, "Session", return_value=http):
            client = orbit.web_client_from_session_id(session_id, "test.account")

        self.assertEqual(client._orbit_auth_mode, "web")
        self.assertEqual(client._orbit_user_id, "1234567890")
        self.assertEqual(http.cookies.values["sessionid"], session_id)
        self.assertEqual(http.calls, [])

    def test_http_429_becomes_a_deferred_retry(self):
        http = _HTTPSession()
        http.get = mock.Mock(
            return_value=_Response(
                None,
                "https://www.instagram.com/api/v1/friendships/123/followers/",
                status_code=429,
                headers={"Retry-After": "120"},
            )
        )
        client = orbit.InstagramWebSession("1234567890%3A" + ("x" * 40), "test.account", "1234567890")
        client.http = http

        with self.assertRaises(orbit.InstagramRateLimited) as raised:
            client.relation_users("1234567890", "followers", amount=1)

        self.assertEqual(raised.exception.retry_after, 120)

    def test_web_discovery_uses_second_degree_profiles(self):
        candidate = {"pk": "99", "username": "candidate"}
        profile = {
            "id": "99",
            "username": "candidate",
            "full_name": "Candidate",
            "biography": "Mamma italiana a Milano, moda e viaggi",
            "follower_count": 800,
            "following_count": 900,
            "media_count": 20,
            "is_private": False,
            "has_anonymous_profile_picture": False,
            "edge_owner_to_timeline_media": {
                "count": 20,
                "edges": [{"node": {"taken_at_timestamp": int(time.time()) - 86_400}}],
            },
        }
        client = mock.Mock()
        client._orbit_auth_mode = "web"
        client._orbit_user_id = "1234567890"
        client.user_id = "1234567890"
        client.relation_users.return_value = [candidate]
        client.profile_by_username.return_value = profile

        with mock.patch.object(orbit.time, "sleep"):
            result = orbit.discover_candidates(
                client,
                seeds=[],
                own_followers=set(),
                own_following={"affine"},
                per_seed=40,
                max_candidates=10,
                automatic_seeds=[{"pk": "55", "username": "affine"}],
            )

        self.assertEqual([item["username"] for item in result], ["candidate"])
        self.assertTrue(result[0]["italianSignal"])
        self.assertTrue(result[0]["femaleSelfDeclared"])
        client.relation_users.assert_called_once_with("55", "followers", amount=40)
        client.profile_by_username.assert_called_once_with("candidate")

    def test_score_rejects_large_profile_that_follows_very_few(self):
        profile = {
            "biography": "Creator italiana di Milano",
            "follower_count": 16_000,
            "following_count": 120,
            "media_count": 80,
            "is_private": True,
        }

        self.assertIsNone(orbit.score_candidate(profile))

    def test_score_rejects_profile_without_italian_signals(self):
        profile = {
            "biography": "Travel photographer from London",
            "follower_count": 700,
            "following_count": 800,
            "media_count": 30,
            "is_private": True,
        }

        self.assertIsNone(orbit.score_candidate(profile))

    def test_score_marks_female_identity_only_from_public_bio(self):
        profile = {
            "biography": "Imprenditrice italiana, mamma e fotografa a Roma",
            "follower_count": 950,
            "following_count": 1_100,
            "media_count": 25,
            "is_private": True,
        }

        scored = orbit.score_candidate(profile)

        self.assertIsNotNone(scored)
        assert scored is not None
        self.assertTrue(scored[2]["femaleSelfDeclared"])
