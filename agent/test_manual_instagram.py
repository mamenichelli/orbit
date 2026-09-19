import time
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from pathlib import Path
from itertools import count
from orbit_manual_instagram import valid_job, assert_account_ui, assert_general, select_general, watch_collected_posts

class ManualIntentTests(unittest.TestCase):
    def test_visible_account_header_must_match_configured_account(self):
        class Page:
            def __init__(self,value):self.value=value
            def wait_for_function(self,*args,**kwargs):pass
            def evaluate(self,*args):return self.value
        assert_account_ui(Page(True),'ma.menichelli')
        with self.assertRaises(RuntimeError):assert_account_ui(Page(False),'ma.menichelli')
    def test_roster_excludes_buttons_above_general_and_recovers_non_chat_navigation(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('r.y>=pane.bottom'),2)
        self.assertEqual(source.count('r.width>=pane.width*.6'),2)
        self.assertIn('def return_to_general(page):',source)
        self.assertIn('return_to_general(page)',source[source.index('if not re.fullmatch(r"/direct/t/'):])
    def test_collection_waits_for_real_general_ui_not_document_loaded_event(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertIn('page.goto(url, wait_until="commit", timeout=45000)',source)
        self.assertIn('if "/accounts/login" in page.url:',source)
        self.assertIn('tab.first.wait_for(state="visible", timeout=45000)',source)
    def test_already_open_latest_chat_is_not_skipped(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertNotIn('Chat non cambiata: salto',source)
        self.assertIn('a[href*="/direct/t/"]',source)
        self.assertIn('page.wait_for_url(',source)
    def test_collector_repeats_instead_of_stopping_after_one_scan(self):
        with patch('orbit_manual_instagram.collector_lock', return_value=nullcontext()), \
             patch('orbit_manual_instagram.load_config',return_value={'ORBIT_INSTAGRAM_USERNAME':'test'}), \
             patch('orbit_manual_instagram.gateway_post',return_value={'started_request_at':0}), \
             patch('orbit_manual_instagram.threading.Thread'), \
             patch('orbit_manual_instagram.time.monotonic',side_effect=count(0,61)), \
             patch('orbit_manual_instagram.collect',side_effect=[None,StopIteration]) as scan:
            with self.assertRaises(StopIteration): watch_collected_posts(Path('.env.agent'), True)
        self.assertEqual(scan.call_count,2)
        self.assertTrue(scan.call_args.kwargs['publish_approved'])
        self.assertEqual(scan.call_args_list[0].kwargs['history_pages'],40)
        self.assertEqual(scan.call_args_list[1].kwargs['history_pages'],40)
    def test_refresh_scan_is_fast_but_idle_scan_reads_full_history(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertIn("history_pages=40 if deep_scan else 1",source)
        self.assertIn("max(completed,attempted)",source)
        self.assertIn("Raccolta rinviata per interfaccia Instagram non pronta",source)
    def test_manual_worker_restarts_without_replaying_a_completed_job(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertIn('while True:\n        try:',source)
        self.assertIn('"action": "complete"',source)
        self.assertIn('Conferma Orbit rinviata: il comando non sarà ripetuto',source)
    def test_each_post_is_persisted_before_later_navigation_can_time_out(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertLess(source.index('if on_found: on_found(pid, found[pid])'),source.index('if not opened:'))
        self.assertLess(source.index('show_latest_messages(page)'),source.index('seen: set[str]'))
    def test_continuous_collection_requires_export_approval(self):
        with self.assertRaises(RuntimeError):watch_collected_posts(Path('.env.agent'), False)
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
