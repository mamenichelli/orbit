from types import SimpleNamespace
from unittest import TestCase, mock

from agent import orbit_instagram_agent as orbit


class _Cookies:
    def __init__(self):
        self.values = {}

    def set(self, name, value, **_kwargs):
        self.values[name] = value


class _Session:
    def __init__(self):
        self.cookies = _Cookies()
        self.headers = {"Authorization": "mobile-header"}


class _WebClient:
    def __init__(self):
        self.settings = {}
        self.private = _Session()
        self.public = _Session()
        self.authorization_data = {"old": "value"}
        self.username = None

    def init(self):
        for name, value in self.settings.get("cookies", {}).items():
            self.private.cookies.set(name, value)

    def user_short_gql(self, user_id, use_cache=True):
        assert use_cache is False
        assert user_id == "1234567890"
        return SimpleNamespace(pk=user_id, username="test.account")


class InstagramWebSessionTests(TestCase):
    def test_session_cookie_never_calls_mobile_login(self):
        session_id = "1234567890%3A" + ("x" * 40)
        with mock.patch.object(orbit, "Client", _WebClient):
            client = orbit.web_client_from_session_id(session_id, "test.account")

        self.assertEqual(client._orbit_auth_mode, "web")
        self.assertEqual(client._orbit_user_id, "1234567890")
        self.assertEqual(client.authorization_data, {})
        self.assertNotIn("Authorization", client.private.headers)
        self.assertEqual(client.public.cookies.values["sessionid"], session_id)

    def test_web_discovery_uses_second_degree_profiles(self):
        candidate = SimpleNamespace(pk="99", username="candidate")
        profile = SimpleNamespace(
            pk="99",
            username="candidate",
            full_name="Candidate",
            follower_count=500,
            following_count=600,
            media_count=20,
            is_private=False,
            is_verified=False,
        )
        client = SimpleNamespace(
            _orbit_auth_mode="web",
            _orbit_user_id="1234567890",
            user_id="1234567890",
            user_info_by_username_v2_gql=mock.Mock(return_value=SimpleNamespace(pk="55")),
            user_followers_gql=mock.Mock(return_value=[candidate]),
            user_info_v2_gql=mock.Mock(return_value=profile),
        )

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
        client.user_followers_gql.assert_called_once_with("55", amount=40)
        client.user_info_v2_gql.assert_called_once_with("99")
