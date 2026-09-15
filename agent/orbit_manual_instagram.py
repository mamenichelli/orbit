"""Collect shared posts; perform ONLY a single recent, user-clicked like command.

No bulk likes, follow/unfollow actions, or implicit commands are generated here.
"""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
import requests
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
from orbit_instagram_agent import load_config, required
from orbit_browser_actions import (assert_account, browser_context, checked_navigation,
    conversation_title, gateway_post, like_post, mark_thread_rows, post_id,
    load_state, save_state, record_like_event, sync_like_events)


def run_worker(config_path):
    config = load_config(config_path)
    with sync_playwright() as p:
        context, browser = browser_context(p, config_path, config)
        try:
            page = context.new_page()
            logging.info("Avvio collegamento manuale")
            while True:
                # Do not advertise online unless the account identity has just been checked.
                assert_account(context, required(config, "ORBIT_INSTAGRAM_USERNAME"))
                try:
                    result = gateway_post(config, "/api/agent/instagram-manual", {
                        "action": "claim", "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME")})
                except requests.RequestException:
                    logging.warning("Rete Orbit non disponibile: attendo senza eseguire azioni")
                    time.sleep(10)
                    continue
                job = result.get("job")
                if not job:
                    time.sleep(5)
                    continue
                status, message = "failed", "Richiesta scaduta: nessuna azione eseguita"
                if valid_job(job):
                    try:
                        assert_account(context, required(config, "ORBIT_INSTAGRAM_USERNAME"))
                        added = like_post(page, job["shortcode"])
                        status = "applied" if added else "already_liked"
                        message = "Mi piace verificato" if added else "Mi piace già presente"
                    except Exception:
                        message = "Instagram non ha confermato il like: controlla il post prima di riprovare"
                # Never replay a command after an interrupted execution or acknowledgment.
                gateway_post(config, "/api/agent/instagram-manual", {
                    "action": "complete", "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
                    "id": job["id"], "status": status, "message": message})
                print(message, flush=True)
        finally:
            context.close()
            if browser: browser.close()


def valid_job(job):
    return (isinstance(job, dict) and isinstance(job.get("shortcode"), str)
        and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", job["shortcode"]) is not None
        and isinstance(job.get("id"), str)
        and isinstance(job.get("requested_at"), (int, float))
        and 0 <= time.time() * 1000 - job["requested_at"] < 120_000)


def scroll_chat(page):
    return page.evaluate('''() => {
      const tabs=document.querySelector('[role="tablist"]'); if(!tabs) return false;
      const edge=tabs.getBoundingClientRect().right;
      const panes=Array.from(document.querySelectorAll('div')).filter(n=>{
        const r=n.getBoundingClientRect(); return r.x>=edge-10 && r.width>250 && r.height>200
          && n.scrollHeight>n.clientHeight+10 && /auto|scroll/.test(getComputedStyle(n).overflowY);
      }).sort((a,b)=>b.clientHeight-a.clientHeight);
      const pane=panes[0]; if(!pane) return false;
      const old=pane.scrollTop; pane.scrollTop=Math.max(0,old-pane.clientHeight*.8);
      return pane.scrollTop!==old;
    }''')


def general_selected(page):
    return page.evaluate('''() => {
      const selected=Array.from(document.querySelectorAll('[role="tab"]')).filter(n=>n.getAttribute('aria-selected')==='true');
      return selected.length===1 && /^(General|Generali|Generale)$/i.test(selected[0].innerText.trim());
    }''')


def assert_general(page):
    if not general_selected(page):
        raise RuntimeError("Scheda Generale non confermata: raccolta fermata, nessun post di Principale importato")


def select_general(page):
    tab = page.get_by_role("tab", name=re.compile(r"^General$|^Generali$|^Generale$", re.I))
    tab.first.wait_for(state="visible", timeout=30000)
    if not general_selected(page):
        tab.first.click()
        deadline = time.monotonic() + 15
        while not general_selected(page) and time.monotonic() < deadline:
            page.wait_for_timeout(250)
        page.wait_for_timeout(2500)
    assert_general(page)


def mark_general_rows(page):
    assert_general(page)
    return page.evaluate('''() => {
      document.querySelectorAll('[data-orbit-thread-row]').forEach(n=>n.removeAttribute('data-orbit-thread-row'));
      const tabs=document.querySelector('[role="tablist"]');if(!tabs)return [];
      const pane=tabs.getBoundingClientRect();
      const rows=Array.from(document.querySelectorAll('[role="button"]')).filter(n=>{
        const r=n.getBoundingClientRect();return Math.abs(r.x-pane.x)<20 && Math.abs(r.width-pane.width)<20
          && r.height>=50 && r.height<=160 && n.querySelector('img') && n.innerText.trim();
      });
      return rows.map((n,index)=>{
        const title=n.innerText.trim().split(String.fromCharCode(10)).map(s=>s.trim()).filter(Boolean)[0];
        n.setAttribute('data-orbit-thread-row',index);
        return {index,title,key:title+'|'+(n.querySelector('img')?.src||'').split('?')[0]};
      });
    }''')


def read_visible_posts(page):
    """Follow only actual Instagram /p/ links. Stories and file dialogs are ignored."""
    assert_general(page)
    found = {pid: {} for href in page.locator('a[href*="/p/"]').evaluate_all(
        "nodes=>nodes.map(n=>n.getAttribute('href')||'')") if (pid := post_id(href))}
    def mark_cards():
        return page.evaluate('''() => {
      document.querySelectorAll('[data-orbit-manual-card]').forEach(n=>n.removeAttribute('data-orbit-manual-card'));
      const tabs=document.querySelector('[role="tablist"]'); if(!tabs) return [];
      const edge=tabs.getBoundingClientRect().right;
      return Array.from(document.querySelectorAll('[role="button"]')).filter(n=>{
        const r=n.getBoundingClientRect(); return r.x>=edge && r.width>=150 && r.width<=450
          && r.height>=120 && n.querySelector('img');
      }).map((n,i)=>{n.setAttribute('data-orbit-manual-card',i); return {index:i,key:n.innerText+'|'+(n.querySelector('img')?.src||'').split('?')[0]};});
    }''')
    cards = mark_cards()
    conversation_url = page.url
    preserved = True
    for item in cards:
        match = next((card for card in mark_cards() if card["key"] == item["key"]), None)
        if not match: continue
        index = match["index"]
        before = list(page.context.pages)
        try:
            card = page.locator(f'[data-orbit-manual-card="{index}"]')
            if card.count() != 1: continue
            card.click(timeout=5000)
            page.wait_for_timeout(1500)
            opened = [tab for tab in page.context.pages if tab not in before]
            target = opened[-1] if opened else page
            target.wait_for_load_state("domcontentloaded", timeout=15000)
            if pid := post_id(target.url):
                target.wait_for_timeout(1200)
                found[pid] = target.evaluate('''() => {
                  const root=document.querySelector('article')||document.querySelector('main');
                  const image=root && Array.from(root.querySelectorAll('img')).find(n=>{
                    const r=n.getBoundingClientRect(); return r.width>=200 && r.height>=180;
                  });
                  const caption=document.querySelector('meta[property="og:description"]')?.content
                    ||root?.querySelector('h1')?.innerText||image?.alt||'';
                  const candidate=document.querySelector('meta[property="og:image"]')?.content||image?.src||root?.querySelector('video')?.poster||'';
                  let previewUrl=''; try {const u=new URL(candidate);if(u.protocol==='https:' && /(^|\\.)(cdninstagram\\.com|fbcdn\\.net)$/.test(u.hostname)) previewUrl=u.href;}catch{}
                  let authorUsername='';
                  const links=root ? Array.from(root.querySelectorAll('header a[href],h2 a[href],a[href]:has(img)')):[];
                  for(const link of links){try{const path=new URL(link.href).pathname;const m=path.match(/^\/([a-zA-Z0-9._]{1,30})\/?$/);if(m&&!['explore','accounts','direct','reels','stories'].includes(m[1])){authorUsername=m[1];break;}}catch{}}
                  const times=root ? Array.from(root.querySelectorAll('a[href] time[datetime]')):[];
                  const time=times.find(n=>{try{return /^\/(p|reel)\/[a-zA-Z0-9_-]+\/?$/.test(new URL(n.closest('a').href).pathname);}catch{return false;}});
                  const rawDate=time?.getAttribute('datetime');const publishedAt=rawDate && Number.isFinite(Date.parse(rawDate)) ? new Date(rawDate).toISOString():null;
                  return {caption:caption.slice(0,2000),previewUrl,authorUsername,publishedAt};
                }''')
            if not opened:
                # Unknown inline dialogs are not clicked. Stop history traversal after reset.
                checked_navigation(page, conversation_url)
                select_general(page)
                page.wait_for_timeout(2000)
                preserved = False
        except BrowserTimeout:
            print("Anteprima non caricata: post non importato senza verifica", flush=True)
            checked_navigation(page, conversation_url)
            select_general(page)
            preserved = False
        finally:
            for tab in list(page.context.pages):
                if tab not in before: tab.close()
    assert_general(page)
    return found, preserved


def collect(config_path, publish_approved=False, history_pages=40):
    config, state = load_config(config_path), load_state(config_path)
    groups = posts = 0
    with sync_playwright() as p:
        context, browser = browser_context(p, config_path, config)
        try:
            assert_account(context, required(config, "ORBIT_INSTAGRAM_USERNAME"))
            page = context.new_page()
            checked_navigation(page, "https://www.instagram.com/direct/inbox/")
            select_general(page)
            deadline = time.monotonic() + 30
            while not mark_general_rows(page) and time.monotonic() < deadline:
                page.wait_for_timeout(1000)
            if not mark_general_rows(page): raise RuntimeError("Conversazioni non caricate: raccolta interrotta, non zero gruppi")
            visited = set()
            idle = 0
            for _ in range(80):
                assert_general(page)
                rows = mark_general_rows(page)
                new = [row for row in rows if row["key"] not in visited]
                for row in new:
                    assert_general(page)
                    current = mark_general_rows(page)
                    match = next((r for r in current if r["key"] == row["key"]), None)
                    if not match: continue
                    before_url = page.url
                    try:
                        page.locator(f'[data-orbit-thread-row="{match["index"]}"]').click(timeout=10000)
                    except BrowserTimeout:
                        visited.add(row["key"])
                        assert_general(page)
                        continue
                    try:
                        page.wait_for_url(lambda url: str(url) != before_url and '/direct/t/' in str(url), timeout=10000)
                    except Exception:
                        visited.add(row["key"])
                        print("Chat non cambiata: salto senza assegnare un gruppo errato", flush=True)
                        continue
                    page.wait_for_timeout(2500)
                    select_general(page)
                    if not re.fullmatch(r"/direct/t/[^/]+/?", urlparse(page.url).path):
                        visited.add(row["key"])
                        print("Conversazione non verificata: salto senza azioni", flush=True)
                        continue
                    visited.add(row["key"])
                    observed_title = str(row["title"]).strip()
                    if not observed_title: continue
                    group = {"title": observed_title[:200], "threadPath": urlparse(page.url).path.rstrip("/") + "/", "folder": "general"}
                    groups += 1
                    seen = set()
                    for _ in range(history_pages):
                        found, preserved = read_visible_posts(page)
                        assert_general(page)
                        for pid in found:
                            record_like_event(state, pid, [group], "discovered")
                            if found[pid]:
                                state["likeEvents"][pid]["metadata"] = found[pid]
                                state["likeEvents"][pid]["pending"] = True
                        posts += len(found.keys() - seen); seen.update(found)
                        save_state(config_path, state)
                        if publish_approved:
                            sync_like_events(config_path, config, state)
                        if not preserved or not scroll_chat(page): break
                        page.wait_for_timeout(1200)
                    print(f"Raccolta: {groups} conversazioni, {posts} post; nessun like eseguito", flush=True)
                idle = idle + 1 if not new else 0
                if idle >= 3 or not rows: break
                mark_general_rows(page)
                assert_general(page)
                page.locator('[data-orbit-thread-row]').first.evaluate('''n=>{
                  for(let p=n.parentElement;p;p=p.parentElement) {
                    if(p.scrollHeight>p.clientHeight && /auto|scroll/.test(getComputedStyle(p).overflowY)) {
                      p.scrollTop+=p.clientHeight*.8;break;
                    }
                  }
                }''')
                page.wait_for_timeout(1500)
        finally:
            context.close()
            if browser: browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["worker", "collect"])
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / ".env.agent")
    parser.add_argument("--publish-collected-posts", action="store_true", help="Export post references, group names and available previews to Orbit only after explicit authorization")
    parser.add_argument("--history-pages", type=int, default=40)
    args = parser.parse_args()
    logging.basicConfig(filename=str(args.config.resolve().parent / ".orbit-agent" / "manual-agent.log"),
                        encoding="utf-8", level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        if args.command == "worker": run_worker(args.config.resolve())
        else: collect(args.config.resolve(), publish_approved=args.publish_collected_posts, history_pages=max(1, min(40, args.history_pages)))
    except Exception as exc:
        logging.error("Agente fermato: %s", type(exc).__name__)
        if isinstance(exc, RuntimeError): print(str(exc), flush=True)
        print(f"Agente manuale fermato: {type(exc).__name__}. Nessuna azione sarà ripetuta automaticamente.", flush=True)
        raise SystemExit(1)
