import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orbit_browser_actions as actions


class LikeHistoryTests(TestCase):
    def test_legacy_does_not_invent_time_or_group(self):
        state = {"likedPosts": ["post"]}
        actions.migrate_like_history(state)
        event = state["likeEvents"]["post"]
        self.assertIsNone(event["likedAt"])
        self.assertEqual(event["groups"], [])
        self.assertEqual(event["status"], "legacy")

    def test_same_post_merges_groups_without_overwriting_action_time(self):
        state = {}
        actions.record_like_event(state, "post", [{"title": "A", "threadPath": "/direct/t/1/"}], "applied", "2026-09-15T11:00:00Z")
        event_id = state["likeEvents"]["post"]["eventId"]
        actions.record_like_event(state, "post", [{"title": "B", "threadPath": "/direct/t/2/"}], "legacy")
        event = state["likeEvents"]["post"]
        self.assertEqual(len(event["groups"]), 2)
        self.assertEqual(event["eventId"], event_id)
        self.assertEqual(event["likedAt"], "2026-09-15T11:00:00Z")
        self.assertEqual(event["status"], "applied")

    def test_failed_upload_remains_pending_and_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.agent"
            state = {}
            actions.record_like_event(state, "post", [], "legacy")
            config = {"ORBIT_INSTAGRAM_USERNAME": "ma.menichelli"}
            with mock.patch.object(actions, "gateway_post", side_effect=actions.requests.ConnectionError):
                self.assertFalse(actions.sync_like_events(path, config, state))
            self.assertTrue(state["likeEvents"]["post"]["pending"])
            with mock.patch.object(actions, "gateway_post", return_value={"ok": True, "accepted": 1}) as send:
                self.assertTrue(actions.sync_like_events(path, config, state))
                self.assertFalse(state["likeEvents"]["post"]["pending"])
                self.assertNotIn("pending", send.call_args.args[2]["events"][0])
                actions.sync_like_events(path, config, state)
                self.assertEqual(send.call_count, 1)
