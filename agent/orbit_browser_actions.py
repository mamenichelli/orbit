"""Narrow Instagram UI actions: posts shared in General DMs and due unfollows."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import keyring
import requests
from playwright.sync_api import sync_playwright

from orbit_instagram_agent import (
    KEYRING_SERVICE, INSTAGRAM_WEB_APP_ID, WEB_IDENTITY_PATH, authenticated_username, edge_profile_path,
    gateway_headers, load_config, required,
    login_saved,
)


POST_PATH = re.compile(r"^/p/([A-Za-z0-9_-]+)/?$")
USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")


def normalize_usernames(text: str) -> list[str]:
    return sorted({value for part in re.split(r"[\s,;]+", text) if
                   (value := part.strip().lstrip("@").lower()) and USERNAME.fullmatch(value)})


def state_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "browser-actions.json"


def load_state(config_path: Path) -> dict:
    path = state_path(config_path)
    if not path.exists():
        return {"likedPosts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(config_path: Path, state: dict) -> None:
    path = state_path(config_path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def record_like_event(state: dict, shortcode: str, groups: list[dict], status: str,
                      liked_at: str | None = None) -> None:
    events = state.setdefault("likeEvents", {})
    event = events.get(shortcode)
    if event is None:
        event = {"eventId": str(uuid.uuid4()), "shortcode": shortcode, "status": status,
                 "likedAt": liked_at, "observedAt": datetime.now(timezone.utc).isoformat(),
                 "groups": [], "pending": True}
        events[shortcode] = event
    known = {group["threadPath"]: group for group in event["groups"]}
    for group in groups:
        if known.get(group["threadPath"]) != group:
            known[group["threadPath"]] = group
            event["pending"] = True
    event["groups"] = list(known.values())[:50]


def migrate_like_history(state: dict) -> None:
    for shortcode in state.get("likedPosts", []):
        if shortcode not in state.get("likeEvents", {}):
            # The old list has no action timestamp or group: never infer them from file dates.
            record_like_event(state, shortcode, [], "legacy")


def sync_like_events(config_path: Path, config: dict, state: dict) -> bool:
    pending = [event for event in state.get("likeEvents", {}).values() if event.get("pending")]
    for offset in range(0, len(pending), 40):
        batch = pending[offset:offset + 40]
        payload = [{key: event[key] for key in
                    ("eventId", "shortcode", "status", "likedAt", "observedAt", "groups")}
                   for event in batch]
        try:
            response = gateway_post(config, "/api/agent/instagram-likes", {
                "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"), "events": payload})
            if response.get("ok") is not True or response.get("accepted") != len(batch):
                raise RuntimeError("Conferma registro assente")
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            save_state(config_path, state)
            print(f"Invio storico like rinviato ({type(exc).__name__}); registro conservato sul PC.")
            return False
        for event in batch:
            event["pending"] = False
        save_state(config_path, state)
    return True


def conversation_title(page) -> str:
    title = page.get_by_role("button", name=re.compile(
        r"Open the details pane of the chat|Apri.*dettagli.*chat", re.I))
    try:
        title.first.wait_for(state="visible", timeout=20_000)
    except Exception as exc:
        raise RuntimeError("Nome della conversazione non verificabile: post non elaborati") from exc
    value = title.first.inner_text().strip()
    if not value:
        raise RuntimeError("Nome della conversazione vuoto: post non elaborati")
    return value[:200]


def post_id(href: str) -> str | None:
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc not in {"instagram.com", "www.instagram.com"}:
        return None
    match = POST_PATH.fullmatch(parsed.path)
    return match.group(1) if match else None


def gateway_get(config: dict[str, str], path: str) -> dict:
    response = requests.get(required(config, "ORBIT_DASHBOARD_URL").rstrip("/") + path,
                            headers=gateway_headers(config), timeout=35)
    response.raise_for_status()
    return response.json()


def gateway_post(config: dict[str, str], path: str, payload: dict) -> dict:
    response = requests.post(required(config, "ORBIT_DASHBOARD_URL").rstrip("/") + path,
                             headers=gateway_headers(config), json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def browser_context(playwright, config_path: Path, config: dict[str, str]):
    profile = edge_profile_path(config_path)
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    session_id = keyring.get_password(KEYRING_SERVICE, f"{username}:sessionid")
    if session_id:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        user_agent = keyring.get_password(KEYRING_SERVICE, f"{username}:useragent") or ""
        context = browser.new_context(locale="it-IT", viewport={"width": 1440, "height": 1000},
                                      **({"user_agent": user_agent} if user_agent else {}))
        cookies = [{"name": "sessionid", "value": session_id, "domain": ".instagram.com",
                    "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}]
        user_id = re.match(r"^\d+", session_id)
        if user_id:
            cookies.append({"name": "ds_user_id", "value": user_id.group(),
                            "domain": ".instagram.com", "path": "/", "secure": True,
                            "httpOnly": False, "sameSite": "Lax"})
        context.add_cookies(cookies)
        return context, browser
    if not profile.exists():
        raise RuntimeError("Sessione browser Instagram assente: esegui setup.ps1 -AuthMode browser")
    context = playwright.chromium.launch_persistent_context(
        str(profile), channel="msedge", headless=True, locale="it-IT",
        viewport={"width": 1440, "height": 1000})
    return context, None


def checked_navigation(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=25_000)
    page.wait_for_timeout(1200)
    if "/accounts/login" in page.url:
        raise RuntimeError("Sessione Instagram scaduta: accedi di nuovo nel profilo Edge dell'agente")


def assert_account(context, expected_username: str) -> None:
    """Fail closed if the browser is signed in as Primezone or any other account."""
    response = context.request.get(
        "https://www.instagram.com" + WEB_IDENTITY_PATH,
        headers={"X-IG-App-ID": INSTAGRAM_WEB_APP_ID, "Accept": "application/json"},
        timeout=20_000,
    )
    if not response.ok:
        raise RuntimeError("Impossibile verificare il profilo Instagram attivo: nessuna azione eseguita")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Identità Instagram non verificabile: nessuna azione eseguita") from exc
    actual = authenticated_username(payload)
    if actual != expected_username.lower():
        raise RuntimeError(
            f"Profilo attivo @{actual or 'sconosciuto'}, atteso @{expected_username}: nessuna azione eseguita")


def general_conversations(page) -> list[str]:
    checked_navigation(page, "https://www.instagram.com/direct/inbox/")
    general = page.get_by_role("tab", name=re.compile(r"Generali|General", re.I))
    try:
        general.first.wait_for(state="visible", timeout=25_000)
    except Exception:
        pass
    if general.count() == 0:
        general = page.get_by_text(re.compile(r"^Generali$|^General$", re.I))
    if general.count() == 0:
        raise RuntimeError("Scheda Generali non trovata: nessun like eseguito")
    general.first.click()
    page.wait_for_timeout(1500)
    selected = any(general.first.get_attribute(name) in {"true", "active", "page"}
                   for name in ("aria-selected", "data-state", "aria-current"))
    if not selected and "general" not in page.url.lower():
        raise RuntimeError("Impossibile confermare la scheda Generali: nessun like eseguito")
    conversations: set[str] = set()
    previous_count = -1
    # The DM list is virtualized: collect currently rendered threads while scrolling its own pane.
    for _ in range(35):
        links = page.locator('a[href*="/direct/t/"]').evaluate_all(
            "nodes => nodes.map(node => node.getAttribute('href') || '')")
        conversations.update(href for href in links if re.fullmatch(r"/direct/t/[^/]+/?", href))
        if not links or len(conversations) == previous_count:
            break
        previous_count = len(conversations)
        page.locator('a[href*="/direct/t/"]').last.evaluate(
            "node => node.scrollIntoView({block: 'end'})")
        page.wait_for_timeout(450)
    if conversations:
        return sorted(conversations)
    # Current web inbox uses role=button rows rather than thread anchors.
    visited: set[str] = set()
    idle = 0
    for _ in range(35):
        rows = mark_thread_rows(page)
        new_rows = [row for row in rows if row["key"] not in visited]
        for row in new_rows:
            current = mark_thread_rows(page)
            match = next((item for item in current if item["key"] == row["key"]), None)
            if not match:
                continue
            visited.add(row["key"])
            page.locator(f'[data-orbit-thread-row="{match["index"]}"]').click()
            try:
                page.wait_for_url(re.compile(r"https://www\.instagram\.com/direct/t/[^/?#]+/?$"), timeout=10_000)
            except Exception as exc:
                raise RuntimeError("Conversazione Generali non riconosciuta: scansione interrotta") from exc
            conversations.add(urlparse(page.url).path)
        idle = idle + 1 if not new_rows else 0
        if idle >= 3 or not rows:
            break
        page.locator('[data-orbit-thread-row]').first.evaluate('''node => {
            for(let p=node.parentElement;p;p=p.parentElement) {
                if(p.scrollHeight>p.clientHeight && /auto|scroll/.test(getComputedStyle(p).overflowY)) {
                    p.scrollTop += p.clientHeight * .8; break;
                }
            }
        }''')
        page.wait_for_timeout(700)
    return sorted(conversations)


def mark_thread_rows(page) -> list[dict]:
    return page.evaluate('''() => {
        document.querySelectorAll('[data-orbit-thread-row]').forEach(n=>n.removeAttribute('data-orbit-thread-row'));
        const tabs=document.querySelector('[role="tablist"]'); if(!tabs) return [];
        const pane=tabs.getBoundingClientRect();
        const rows=Array.from(document.querySelectorAll('[role="button"]')).filter(n=>{
            const r=n.getBoundingClientRect();
            return Math.abs(r.x-pane.x)<20 && Math.abs(r.width-pane.width)<20 && r.height>=50 && r.height<=110 && n.innerText.trim();
        });
        return rows.map((n,index)=>{n.setAttribute('data-orbit-thread-row',index); return {index,key:n.innerText.split('\\n')[0]};});
    }''')


def shared_post_ids(page) -> set[str]:
    conversation_url = page.url
    page.wait_for_timeout(2500)
    found = {value for href in page.locator('a[href*="/p/"]').evaluate_all(
        "nodes => nodes.map(n=>n.getAttribute('href')||'')") if (value := post_id(href))}

    def mark_cards():
        return page.evaluate('''() => {
            document.querySelectorAll('[data-orbit-share-card]').forEach(n=>n.removeAttribute('data-orbit-share-card'));
            const tabs=document.querySelector('[role="tablist"]'); if(!tabs) return [];
            const edge=tabs.getBoundingClientRect().right;
            const nodes=Array.from(document.querySelectorAll('[role="button"]')).filter(n=>{
                const r=n.getBoundingClientRect();
                return r.x>=edge && r.width>=150 && r.width<=450 && r.height>=120 && n.querySelector('img');
            });
            return nodes.map((n,index)=>{n.setAttribute('data-orbit-share-card',index); return {index,key:n.innerText};});
        }''')

    cards = mark_cards()
    for card in cards:
        current = mark_cards()
        match = next((item for item in current if item["key"] == card["key"]), None)
        if not match:
            continue
        before = list(page.context.pages)
        try:
            page.locator(f'[data-orbit-share-card="{match["index"]}"]').click(timeout=5000)
            page.wait_for_timeout(1500)
            opened = [tab for tab in page.context.pages if tab not in before]
            target = opened[-1] if opened else page
            target.wait_for_load_state("domcontentloaded", timeout=15_000)
            if value := post_id(target.url):
                found.add(value)
        finally:
            for tab in list(page.context.pages):
                if tab not in before:
                    tab.close()
            # Restore the conversation rather than interacting with unknown file/story dialogs.
            checked_navigation(page, conversation_url)
            page.wait_for_timeout(2000)
    return found


def like_post(page, shortcode: str) -> bool:
    checked_navigation(page, f"https://www.instagram.com/p/{shortcode}/")
    main = page.locator("article").first
    if main.count() == 0:
        main = page.locator("main").first
    if main.count() == 0:
        raise RuntimeError(f"Post {shortcode}: contenuto non riconosciuto")
    icons = main.locator('svg[aria-label="Mi piace"],svg[aria-label="Like"],svg[aria-label="Non mi piace più"],svg[aria-label="Unlike"]')
    icons.first.wait_for(state="visible", timeout=25_000)
    selected_label = icons.evaluate_all('''nodes => {
        const icon=nodes.find(n=>{const r=n.getBoundingClientRect();return r.width>=20 && r.height>=20;});
        if(!icon) return null;
        icon.setAttribute('data-orbit-post-like-icon','true'); return icon.getAttribute('aria-label');
    }''')
    if selected_label in {"Non mi piace più", "Unlike"}:
        return False
    button = main.locator('[data-orbit-post-like-icon="true"]')
    if button.count() != 1:
        raise RuntimeError(f"Post {shortcode}: pulsante Mi piace non trovato")
    button.click()
    try:
        page.wait_for_function('''() => {
            const root=document.querySelector('article')||document.querySelector('main');
            return root && Array.from(root.querySelectorAll('svg[aria-label="Non mi piace più"],svg[aria-label="Unlike"]')).some(n=>{
                const r=n.getBoundingClientRect();return r.width>=20 && r.height>=20;
            });
        }''', timeout=15_000)
    except Exception as exc:
        raise RuntimeError(f"Post {shortcode}: like non confermato") from exc
    return True


def run_likes(config_path: Path) -> None:
    config = load_config(config_path)
    state = load_state(config_path)
    liked = set(state.get("likedPosts", []))
    with sync_playwright() as playwright:
        context, browser = browser_context(playwright, config_path, config)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            assert_account(context, required(config, "ORBIT_INSTAGRAM_USERNAME"))
            migrate_like_history(state)
            save_state(config_path, state)
            sync_like_events(config_path, config, state)
            conversations = general_conversations(page)
            post_ids: set[str] = set()
            origins: dict[str, list[dict]] = {}
            for conversation in conversations:
                checked_navigation(page, "https://www.instagram.com" + conversation)
                group = {"title": conversation_title(page), "threadPath": conversation.rstrip("/") + "/"}
                posts = shared_post_ids(page)
                post_ids.update(posts)
                for shortcode in posts:
                    origins.setdefault(shortcode, []).append(group)
                    if shortcode in liked:
                        record_like_event(state, shortcode, [group], "legacy")
                save_state(config_path, state)
            completed = 0
            for shortcode in sorted(post_ids - liked):
                try:
                    added_like = like_post(page, shortcode)
                    record_like_event(state, shortcode, origins[shortcode],
                                      "applied" if added_like else "already_liked",
                                      datetime.now(timezone.utc).isoformat() if added_like else None)
                    liked.add(shortcode)
                    state["likedPosts"] = sorted(liked)
                    save_state(config_path, state)
                    sync_like_events(config_path, config, state)
                    completed += int(added_like)
                    time.sleep(2)
                except RuntimeError as exc:
                    print(str(exc))
            sync_like_events(config_path, config, state)
            print(f"Generali: {len(conversations)} chat, {len(post_ids)} post, {completed} nuovi like verificati")
        finally:
            context.close()
            if browser:
                browser.close()


def due_unfollows(planner: dict, protected: set[str], cache: dict) -> list[dict]:
    if time.time() - int(cache.get("cachedAt", 0)) > 8 * 3600:
        raise RuntimeError("Relazioni locali troppo vecchie: esegui prima sync")
    last_import = planner.get("lastImport") or {}
    if not last_import.get("imported_at"):
        raise RuntimeError("Nessuna sincronizzazione relazioni sul dashboard")
    followers = set(cache["followers"])
    following = set(cache["following"])
    try:
        imported_at = datetime.fromisoformat(str(last_import["imported_at"]).replace("Z", "+00:00"))
        if imported_at.tzinfo is None:
            imported_at = imported_at.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Data sincronizzazione dashboard non valida") from exc
    if imported_at.timestamp() + 300 < int(cache["cachedAt"]):
        raise RuntimeError("Snapshot dashboard più vecchio della cache locale: defollow bloccato")
    if int(last_import.get("followers_count", -1)) != len(followers) or int(last_import.get("following_count", -1)) != len(following):
        raise RuntimeError("Cache locale e dashboard non coincidono: defollow bloccato")
    result = []
    for action in planner.get("actions", []):
        username = str(action.get("username") or "").lower()
        if (action.get("action_type") == "unfollow" and action.get("status") == "pending"
                and USERNAME.fullmatch(username) and username in following
                and username not in followers and username not in protected):
            result.append(action)
    return result


def unfollow_profile(page, username: str) -> bool:
    checked_navigation(page, f"https://www.instagram.com/{username}/")
    header = page.locator("header").first
    if header.count() == 0:
        raise RuntimeError(f"@{username}: profilo non riconosciuto")
    if re.search(r"Ti segue|Follows you", header.inner_text(), re.I):
        return False
    following = header.get_by_role("button", name=re.compile(r"^(Segui già|Following|Amici)$", re.I))
    if following.count() == 0:
        raise RuntimeError(f"@{username}: stato Segui già non trovato")
    following.first.click()
    unfollow = page.get_by_role("button", name=re.compile(r"^(Non seguire più|Unfollow)$", re.I))
    if unfollow.count() == 0:
        raise RuntimeError(f"@{username}: conferma defollow non trovata")
    unfollow.first.click()
    page.wait_for_timeout(650)
    if header.get_by_role("button", name=re.compile(r"^(Segui|Follow)$", re.I)).count() == 0:
        raise RuntimeError(f"@{username}: defollow non confermato")
    return True


def run_unfollows(config_path: Path) -> None:
    config = load_config(config_path)
    local_file = config_path.parent / ".orbit-agent" / "protected-seed.txt"
    if not local_file.exists():
        raise RuntimeError("Lista iniziale intoccabili assente: defollow bloccato")
    seed = set(normalize_usernames(local_file.read_text(encoding="utf-8-sig")))
    if not seed:
        raise RuntimeError("Lista intoccabili vuota: defollow bloccato")
    remote = gateway_get(config, "/api/agent/protected")
    protected = set(remote.get("usernames", []))
    if not seed.issubset(protected):
        raise RuntimeError("Intoccabili iniziali non completamente presenti sul dashboard: defollow bloccato")
    planner = gateway_get(config, "/api/planner")
    cache = json.loads((config_path.parent / ".orbit-agent" / "instagram-relations-cache.json").read_text(encoding="utf-8"))
    candidates = due_unfollows(planner, protected, cache)
    if not candidates:
        print("Nessun defollow dovuto e verificato")
        return
    with sync_playwright() as playwright:
        context, browser = browser_context(playwright, config_path, config)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            assert_account(context, required(config, "ORBIT_INSTAGRAM_USERNAME"))
            completed = 0
            for action in candidates[:20]:
                username = action["username"]
                try:
                    if unfollow_profile(page, username):
                        gateway_post(config, "/api/planner", {"operation": "complete", "actionId": action["id"]})
                        completed += 1
                        time.sleep(3)
                except RuntimeError as exc:
                    print(str(exc))
            print(f"Defollow completati e verificati: {completed}")
        finally:
            context.close()
            if browser:
                browser.close()


def import_protected(config_path: Path, source: Path) -> None:
    config = load_config(config_path)
    usernames = normalize_usernames(source.read_text(encoding="utf-8-sig"))
    if len(usernames) != 549:
        raise RuntimeError(f"Attesi 549 intoccabili validi e distinti, trovati {len(usernames)}")
    result = gateway_post(config, "/api/growth", {"operation": "protect_bulk", "usernames": usernames})
    if not result.get("ok"):
        raise RuntimeError("Importazione intoccabili non confermata")
    remote = gateway_get(config, "/api/agent/protected")
    if not set(usernames).issubset(set(remote.get("usernames", []))):
        raise RuntimeError("La verifica degli intoccabili sul dashboard è fallita")
    local_file = config_path.parent / ".orbit-agent" / "protected-seed.txt"
    local_file.write_text("\n".join("@" + name for name in usernames) + "\n", encoding="utf-8")
    print(f"Intoccabili importati e verificati: {len(usernames)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Azioni browser Instagram Orbit")
    parser.add_argument("command", choices=("like-general-posts", "unfollow-due", "import-protected", "sync-likes"))
    parser.add_argument("--config", default=".env.agent")
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.command == "like-general-posts":
        run_likes(config_path)
    elif args.command == "unfollow-due":
        run_unfollows(config_path)
    elif args.command == "sync-likes":
        config = load_config(config_path)
        login_saved(config, config_path)
        state = load_state(config_path)
        migrate_like_history(state)
        save_state(config_path, state)
        if not sync_like_events(config_path, config, state):
            raise RuntimeError("Storico conservato localmente; invio a Orbit non concluso")
        print("Storico like sincronizzato con Orbit.")
    else:
        if not args.file:
            parser.error("--file obbligatorio per import-protected")
        import_protected(config_path, args.file)


if __name__ == "__main__":
    main()
