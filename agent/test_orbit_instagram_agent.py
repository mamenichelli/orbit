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

    def raise_for_status(self):
        if self.status_code >= 400:
            raise orbit.requests.HTTPError(f"HTTP {self.status_code}")


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
    def test_official_recurring_interactions_are_prioritized(self):
        session = _Response(
            {"gatewayUrl": "https://gateway.test/snapshot", "accessToken": "short-token"},
            "https://dashboard.test/api/meta/snapshot",
        )
        gateway = _Response(
            {"opportunities": [
                {"platform": "Instagram", "username": "candidate.it", "interactions": 6, "score": 90},
                {"platform": "Instagram", "username": "already.followed", "interactions": 12, "score": 99},
            ]},
            "https://gateway.test/snapshot",
        )
        config = {
            "ORBIT_DASHBOARD_URL": "https://dashboard.test",
            "ORBIT_AGENT_TOKEN": "agent-token",
            "ORBIT_SIWC_BYPASS_TOKEN": "sites-token",
        }

        with mock.patch.object(orbit.requests, "get", side_effect=[session, gateway]):
            result = orbit.fetch_interaction_signals(config, set(), {"already.followed"})

        self.assertEqual(result["candidate.it"]["interactions"], 6)
        self.assertNotIn("already.followed", result)

    def test_compact_instagram_counts_are_parsed(self):
        self.assertEqual(orbit.parse_compact_count("1.693"), 1_693)
        self.assertEqual(orbit.parse_compact_count("1,2 mila"), 1_200)
        self.assertEqual(orbit.parse_compact_count("3.4K"), 3_400)

    def test_browser_profile_text_builds_scoring_payload(self):
        profile = orbit.browser_profile_payload(
            "850 follower, 1.100 profili seguiti, 24 post - Foto di Giulia",
            "Giulia\nMamma italiana a Roma, benessere e viaggi\nQuesto account è privato",
            "Giulia (@giulia.roma) • Instagram photos and videos",
        )

        scored = orbit.score_candidate(profile)

        self.assertEqual(profile["follower_count"], 850)
        self.assertEqual(profile["following_count"], 1_100)
        self.assertEqual(profile["media_count"], 24)
        self.assertTrue(profile["is_private"])
        self.assertIsNotNone(scored)
        assert scored is not None
        self.assertTrue(scored[2]["femaleSelfDeclared"])

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

    def test_relation_cache_and_seed_rotation_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / ".env.agent"
            config_path.write_text("ORBIT_INSTAGRAM_USERNAME=test.account\n", encoding="utf-8")
            orbit.save_relation_cache(
                config_path,
                ["follower"],
                ["seed.one", "seed.two"],
                {
                    "seed.one": {"pk": "11", "username": "seed.one"},
                    "seed.two": {"pk": "22", "username": "seed.two"},
                },
            )
            cached = orbit.load_relation_cache(config_path)
            first = orbit.next_discovery_seed(config_path, cached["automaticSeeds"])
            second = orbit.next_discovery_seed(config_path, cached["automaticSeeds"])

        self.assertEqual(cached["followers"], ["follower"])
        self.assertEqual(first["username"], "seed.one")
        self.assertEqual(second["username"], "seed.two")

    def test_discovery_respects_saved_rate_limit_before_login(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / ".env.agent"
            config_path.write_text("ORBIT_INSTAGRAM_USERNAME=test.account\n", encoding="utf-8")
            orbit.save_relation_cache(config_path, ["follower"], ["following"], {})
            orbit.record_rate_limit(config_path, 600)
            with mock.patch.object(orbit, "login_saved") as login_saved, mock.patch.object(
                orbit,
                "discover_candidates_with_browser",
                side_effect=RuntimeError("browser unavailable"),
            ):
                orbit.discover(config_path)

        login_saved.assert_not_called()

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

    def test_web_search_extracts_public_user_results(self):
        http = _HTTPSession()
        http.get = mock.Mock(return_value=_Response(
            {"users": [{"user": {"pk": "99", "username": "candidate.it"}}]},
            "https://www.instagram.com/web/search/topsearch/",
        ))
        client = orbit.InstagramWebSession("1234567890%3A" + ("x" * 40), "test.account", "1234567890")
        client.http = http

        users = client.search_users("psicologa roma", amount=10)

        self.assertEqual([item["username"] for item in users], ["candidate.it"])

    def test_web_discovery_uses_topic_search_without_opening_followers(self):
        candidate = {"pk": "99", "username": "candidate"}
        profile = {
            "id": "99",
            "username": "candidate",
            "full_name": "Candidate",
            "biography": "Psicologa e mamma italiana a Roma",
            "follower_count": 800,
            "following_count": 900,
            "media_count": 20,
            "is_private": True,
            "has_anonymous_profile_picture": False,
        }
        client = mock.Mock()
        client._orbit_auth_mode = "web"
        client._orbit_user_id = "1234567890"
        client.user_id = "1234567890"
        client.search_users.return_value = [candidate]
        client.profile_by_username.return_value = profile

        with mock.patch.object(orbit.time, "sleep"):
            result = orbit.discover_candidates(
                client,
                seeds=[],
                own_followers=set(),
                own_following=set(),
                per_seed=12,
                max_candidates=3,
                automatic_seeds=[],
                search_queries=["psicologa roma"],
            )

        self.assertEqual([item["username"] for item in result], ["candidate"])
        client.search_users.assert_called_once_with("psicologa roma", amount=12)
        client.relation_users.assert_not_called()

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

    def test_score_rejects_italian_language_without_declared_location_or_identity(self):
        profile = {
            "biography": "Mamma, moda, bellezza e viaggi",
            "follower_count": 700,
            "following_count": 800,
            "media_count": 30,
            "is_private": True,
        }

        self.assertIsNone(orbit.score_candidate(profile))

    def test_score_rejects_male_profile_even_when_italian_and_active(self):
        profile = {
            "biography": "Creator italiano di Milano, moda e viaggi",
            "follower_count": 700,
            "following_count": 800,
            "media_count": 30,
            "is_private": True,
        }

        self.assertIsNone(orbit.score_candidate(profile))

    def test_score_accepts_italian_profile_with_gender_not_declared(self):
        profile = {
            "biography": "Psicologia e benessere a Bologna",
            "follower_count": 700,
            "following_count": 800,
            "media_count": 30,
            "is_private": True,
        }

        scored = orbit.score_candidate(profile)

        self.assertIsNotNone(scored)
        assert scored is not None
        self.assertFalse(scored[2]["femaleSelfDeclared"])

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
