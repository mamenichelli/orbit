"""Narrow Instagram UI actions: posts shared in General DMs and due unfollows."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import keyring
import requests
from playwright.sync_api import sync_playwright

from orbit_instagram_agent import KEYRING_SERVICE, INSTAGRAM_WEB_APP_ID, gateway_headers, load_config, required


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
    profile = config_path.parent / ".orbit-agent" / "edge-profile"
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    session_id = keyring.get_password(KEYRING_SERVICE, f"{username}:sessionid")
    if session_id:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(locale="it-IT", viewport={"width": 1440, "height": 1000})
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
        "https://www.instagram.com/api/v1/accounts/current_user/?edit=true",
        headers={"X-IG-App-ID": INSTAGRAM_WEB_APP_ID, "Accept": "application/json"},
        timeout=20_000,
    )
    if not response.ok:
        raise RuntimeError("Impossibile verificare il profilo Instagram attivo: nessuna azione eseguita")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Identità Instagram non verificabile: nessuna azione eseguita") from exc
    user = payload.get("user") or payload.get("data", {}).get("user") or {}
    actual = str(user.get("username") or "").lower()
    if actual != expected_username.lower():
        raise RuntimeError(
            f"Profilo attivo @{actual or 'sconosciuto'}, atteso @{expected_username}: nessuna azione eseguita")


def general_conversations(page) -> list[str]:
    checked_navigation(page, "https://www.instagram.com/direct/inbox/")
    general = page.get_by_role("tab", name=re.compile(r"Generali|General", re.I))
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
    # The DM list is virtualized: collect currently rendered threads while scrolling its own pane.
    for _ in range(35):
        links = page.locator('a[href*="/direct/t/"]').evaluate_all(
            "nodes => nodes.map(node => node.getAttribute('href') || '')")
        conversations.update(href for href in links if re.fullmatch(r"/direct/t/[^/]+/?", href))
        if not links:
            break
        before = len(conversations)
        page.locator('a[href*="/direct/t/"]').last.evaluate(
            "node => node.scrollIntoView({block: 'end'})")
        page.wait_for_timeout(450)
        if len(conversations) == before:
            break
    return sorted(conversations)


def like_post(page, shortcode: str) -> bool:
    checked_navigation(page, f"https://www.instagram.com/p/{shortcode}/")
    main = page.locator("article").first
    if main.count() == 0:
        main = page.locator("main").first
    if main.count() == 0:
        raise RuntimeError(f"Post {shortcode}: contenuto non riconosciuto")
    if main.locator('svg[aria-label="Non mi piace più"],svg[aria-label="Unlike"]').count():
        return False
    button = main.locator('button:has(svg[aria-label="Mi piace"]),button:has(svg[aria-label="Like"])').first
    if button.count() == 0:
        raise RuntimeError(f"Post {shortcode}: pulsante Mi piace non trovato")
    button.click()
    page.wait_for_timeout(500)
    if main.locator('svg[aria-label="Non mi piace più"],svg[aria-label="Unlike"]').count() == 0:
        raise RuntimeError(f"Post {shortcode}: like non confermato")
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
            conversations = general_conversations(page)
            post_ids: set[str] = set()
            for conversation in conversations:
                checked_navigation(page, "https://www.instagram.com" + conversation)
                for href in page.locator('a[href*="/p/"]').evaluate_all(
                        "nodes => nodes.map(node => node.getAttribute('href') || '')"):
                    if (shortcode := post_id(href)):
                        post_ids.add(shortcode)
            completed = 0
            for shortcode in sorted(post_ids - liked):
                try:
                    like_post(page, shortcode)
                    liked.add(shortcode)
                    state["likedPosts"] = sorted(liked)
                    save_state(config_path, state)
                    completed += 1
                    time.sleep(2)
                except RuntimeError as exc:
                    print(str(exc))
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
    parser.add_argument("command", choices=("like-general-posts", "unfollow-due", "import-protected"))
    parser.add_argument("--config", default=".env.agent")
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.command == "like-general-posts":
        run_likes(config_path)
    elif args.command == "unfollow-due":
        run_unfollows(config_path)
    else:
        if not args.file:
            parser.error("--file obbligatorio per import-protected")
        import_protected(config_path, args.file)


if __name__ == "__main__":
    main()
