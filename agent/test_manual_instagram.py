import time
import unittest
from orbit_manual_instagram import valid_job

class ManualIntentTests(unittest.TestCase):
    def test_only_recent_single_command(self):
        job = {"id": "test", "shortcode": "ABC_123", "requested_at": time.time() * 1000}
        self.assertTrue(valid_job(job))
        self.assertFalse(valid_job({**job, "requested_at": time.time() * 1000 - 120001}))
        self.assertFalse(valid_job({**job, "shortcode": ["a", "b"]}))
        self.assertFalse(valid_job({**job, "shortcode": "../accounts/login"}))
        self.assertFalse(valid_job({**job, "requested_at": time.time() * 1000 + 10000}))

if __name__ == "__main__": unittest.main()
