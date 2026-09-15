import time
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from pathlib import Path
from itertools import count
from orbit_manual_instagram import valid_job, assert_general, select_general, watch_collected_posts

class ManualIntentTests(unittest.TestCase):
    def test_roster_excludes_buttons_above_general_and_recovers_non_chat_navigation(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('r.y>=pane.bottom'),2)
        guard=source.index('if not re.fullmatch(r"/direct/t/')
        self.assertLess(guard,source.index('select_general(page)',guard))
        self.assertIn('checked_collection_navigation(page, "https://www.instagram.com/direct/inbox/")',source[guard:guard+550])
    def test_collection_waits_for_real_general_ui_not_document_loaded_event(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertIn('page.goto(url, wait_until="commit", timeout=45000)',source)
        self.assertIn('if "/accounts/login" in page.url:',source)
        self.assertIn('tab.first.wait_for(state="visible", timeout=45000)',source)
    def test_already_open_latest_chat_is_not_skipped(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertNotIn('Chat non cambiata: salto',source)
        self.assertIn('header.inner_text().strip()[:200] != observed_title[:200]',source)
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
        self.assertEqual(scan.call_args.kwargs['history_pages'],1)
    def test_each_post_is_persisted_before_later_navigation_can_time_out(self):
        source=Path(__file__).with_name('orbit_manual_instagram.py').read_text(encoding='utf-8')
        self.assertLess(source.index('if on_found: on_found(pid, found[pid])'),source.index('if not opened:'))
        self.assertLess(source.index('show_latest_messages(page)\n'),source.index('seen = set()'))
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
