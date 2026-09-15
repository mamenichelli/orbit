import time
import unittest
from orbit_manual_instagram import valid_job, assert_general, select_general

class ManualIntentTests(unittest.TestCase):
    def test_general_tab_waits_until_primary_rows_are_replaced(self):
        class Page:
            def __init__(self): self.selected=False; self.samples=0; self.first=self
            def get_by_role(self,*args,**kwargs):return self
            def wait_for(self,**kwargs):pass
            def click(self):self.selected=True
            def wait_for_timeout(self,*args):pass
            def evaluate(self,script):
                if 'const selected=' in script:return self.selected
                if not self.selected:return 'primary-rows'
                self.samples+=1
                return 'primary-rows' if self.samples<=5 else 'general-rows'
        page=Page()
        select_general(page)
        self.assertGreaterEqual(page.samples,10)
    def test_principal_or_uncertain_folder_is_rejected(self):
        class Page:
            def __init__(self, selected): self.selected = selected
            def evaluate(self, script): return self.selected
        assert_general(Page(True))
        with self.assertRaises(RuntimeError): assert_general(Page(False))
    def test_only_recent_single_command(self):
        job = {"id": "test", "shortcode": "ABC_123", "requested_at": time.time() * 1000}
        self.assertTrue(valid_job(job))
        self.assertFalse(valid_job({**job, "requested_at": time.time() * 1000 - 120001}))
        self.assertFalse(valid_job({**job, "shortcode": ["a", "b"]}))
        self.assertFalse(valid_job({**job, "shortcode": "../accounts/login"}))
        self.assertFalse(valid_job({**job, "requested_at": time.time() * 1000 + 10000}))

if __name__ == "__main__": unittest.main()
