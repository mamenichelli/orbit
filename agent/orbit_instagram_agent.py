from __future__ import annotations

import argparse
import getpass
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Iterable

import keyring
import requests
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, TwoFactorRequired


KEYRING_SERVICE = "Orbit Social Growth - Instagram"
INSTAGRAM_WEB_APP_ID = "936619743392459"


class InstagramRateLimited(RuntimeError):
    def __init__(self, retry_after: int):
        self.retry_after = max(60, int(retry_after))
        super().__init__(f"Limite Instagram attivo; riprova tra {self.retry_after} secondi")


def load_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise RuntimeError(f"Configurazione mancante: {path}")
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lstrip("\ufeff")] = value.strip().strip('"').strip("'")
    return values


def required(config: dict[str, str], key: str) -> str:
    value = config.get(key, "").strip()
    if not value:
        raise RuntimeError(f"Valore obbligatorio mancante: {key}")
    return value


def session_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-session.json"


def cooldown_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-cooldown.json"


def record_rate_limit(config_path: Path, retry_after: int) -> int:
    retry_at = int(time.time()) + max(60, int(retry_after))
    cooldown_path(config_path).write_text(
        json.dumps({"retry_at": retry_at}, separators=(",", ":")),
        encoding="utf-8",
    )
    return retry_at


class InstagramWebSession:
    """Small cookie-based client for Instagram's web JSON endpoints."""

    _orbit_auth_mode = "web"

    def __init__(self, session_id: str, expected_username: str, user_id: str):
        self.username = expected_username.strip().lstrip("@").lower()
        self.user_id = str(user_id)
        self._orbit_user_id = self.user_id
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Accept": "*/*",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                "X-ASBD-ID": "129477",
                "X-IG-App-ID": INSTAGRAM_WEB_APP_ID,
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.http.cookies.set("sessionid", session_id, domain=".instagram.com")
        self.http.cookies.set("ds_user_id", self.user_id, domain=".instagram.com")

    def _json_get(self, path: str, params: dict[str, Any], referer: str) -> dict[str, Any]:
        url = "https://www.instagram.com" + path
        response = self.http.get(
            url,
            params=params,
            headers={"Referer": referer},
            timeout=60,
            allow_redirects=False,
        )
        if response.status_code == 429:
            raw_retry_after = response.headers.get("Retry-After", "")
            try:
                retry_after = int(raw_retry_after)
            except (TypeError, ValueError):
                retry_after = 30 * 60
            raise InstagramRateLimited(retry_after)
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location", "")
            raise RuntimeError(
                f"Instagram ha reindirizzato la sessione ({response.status_code}, {location or 'login'}). "
                "Copia un nuovo cookie sessionid da una scheda Instagram ancora autenticata."
            )
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else "pagina HTML"
            raise RuntimeError(
                f"Instagram Web ha restituito {title!r} invece dei dati JSON "
                f"(HTTP {response.status_code}, endpoint {path})."
            ) from exc
        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error_title") or "richiesta rifiutata"
            raise RuntimeError(f"Instagram Web: {message} (HTTP {response.status_code})")
        if payload.get("status") == "fail" or payload.get("message") == "login_required":
            raise RuntimeError(
                "Instagram richiede un nuovo accesso web. Copia nuovamente il cookie sessionid."
            )
        return payload

    def profile_by_username(self, username: str) -> dict[str, Any]:
        normalized = username.strip().lstrip("@").lower()
        payload = self._json_get(
            "/api/v1/users/web_profile_info/",
            {"username": normalized},
            f"https://www.instagram.com/{normalized}/",
        )
        user = (payload.get("data") or {}).get("user") or payload.get("user")
        if not isinstance(user, dict):
            raise RuntimeError(f"Profilo Instagram @{normalized} non trovato")
        return user

    def relation_users(self, user_id: str, relation: str, amount: int = 0) -> list[dict[str, Any]]:
        if relation not in {"followers", "following"}:
            raise ValueError("Relazione Instagram non valida")
        users: list[dict[str, Any]] = []
        max_id = ""
        seen_cursors: set[str] = set()
        while True:
            remaining = amount - len(users) if amount else 100
            params: dict[str, Any] = {
                "count": max(1, min(100, remaining)),
                "search_surface": "follow_list_page",
                "query": "",
                "enable_groups": "true",
            }
            if max_id:
                params["max_id"] = max_id
            payload = self._json_get(
                f"/api/v1/friendships/{user_id}/{relation}/",
                params,
                f"https://www.instagram.com/{self.username}/{relation}/",
            )
            page_users = payload.get("users") or []
            users.extend(item for item in page_users if isinstance(item, dict))
            max_id = str(payload.get("next_max_id") or "")
            if not max_id or max_id in seen_cursors or (amount and len(users) >= amount):
                break
            seen_cursors.add(max_id)
            time.sleep(random.uniform(1.0, 2.0))
        return users[:amount] if amount else users


def login_for_setup(username: str, password: str, settings_file: Path) -> Client:
    client = Client()
    try:
        client.login(username, password)
    except TwoFactorRequired:
        code = input("Codice Instagram 2FA: ").strip()
        client = Client()
        client.login(username, password, verification_code=code)
    client.get_timeline_feed()
    client.dump_settings(settings_file)
    return client


def web_client_from_session_id(session_id: str, expected_username: str) -> InstagramWebSession:
    """Create a read-only web session; validation happens during sync."""
    user_match = re.match(r"^\d+", session_id)
    if not user_match or len(session_id) <= 30:
        raise RuntimeError("Session ID non valido")

    user_id = user_match.group(0)
    client = InstagramWebSession(session_id, expected_username, user_id)
    return client


def login_with_browser(username: str, config_path: Path) -> InstagramWebSession:
    """Use Edge only to obtain a normal web cookie, then stay on the web API."""
    from playwright.sync_api import sync_playwright

    browser_profile = config_path.parent / ".orbit-agent" / "edge-profile"
    browser_profile.mkdir(parents=True, exist_ok=True)
    session_id = ""
    print("Si apre Microsoft Edge: completa l'accesso Instagram nel browser.")
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_profile),
            channel="msedge",
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        deadline = time.time() + 600
        while time.time() < deadline:
            cookies = context.cookies(["https://www.instagram.com"])
            cookie = next((item for item in cookies if item.get("name") == "sessionid"), None)
            if cookie and cookie.get("value"):
                session_id = str(cookie["value"])
                break
            page.wait_for_timeout(1000)
        context.close()
    if not session_id:
        raise RuntimeError("Accesso browser non completato entro 10 minuti")

    client = web_client_from_session_id(session_id, username)
    keyring.set_password(KEYRING_SERVICE, f"{username}:sessionid", session_id)
    return client


def login_with_session_id(username: str, config_path: Path) -> InstagramWebSession:
    session_id = getpass.getpass("Session ID Instagram (input nascosto, resta sul PC): ").strip()
    if not session_id:
        raise RuntimeError("Session ID non inserito")
    client = web_client_from_session_id(session_id, username)
    keyring.set_password(KEYRING_SERVICE, f"{username}:sessionid", session_id)
    return client


def login_saved(config: dict[str, str], config_path: Path) -> Any:
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    saved_session_id = keyring.get_password(KEYRING_SERVICE, f"{username}:sessionid")
    password = keyring.get_password(KEYRING_SERVICE, username)
    if not saved_session_id and not password:
        raise RuntimeError("Credenziale locale assente. Esegui di nuovo agent/setup.ps1.")
    if saved_session_id:
        return web_client_from_session_id(saved_session_id, username)

    settings_file = session_path(config_path)
    client = Client()
    if settings_file.exists():
        settings = client.load_settings(settings_file)
        if settings:
            client.set_settings(settings)
    try:
        client.login(username, password or "")
        client.get_timeline_feed()
    except (LoginRequired, TwoFactorRequired) as exc:
        raise RuntimeError(
            "Instagram richiede una nuova verifica. Esegui agent/setup.ps1 per rinnovare la sessione."
        ) from exc
    client.dump_settings(settings_file)
    client._orbit_auth_mode = "mobile"  # type: ignore[attr-defined]
    client._orbit_user_id = str(client.user_id)  # type: ignore[attr-defined]
    return client


def username_of(user: Any) -> str:
    value = user.get("username", "") if isinstance(user, dict) else getattr(user, "username", "")
    return str(value or "").strip().lower()


def field_of(user: Any, name: str, default: Any = None) -> Any:
    return user.get(name, default) if isinstance(user, dict) else getattr(user, name, default)


def collect_users(stream: Iterable[Any]) -> tuple[list[str], dict[str, Any]]:
    usernames: list[str] = []
    users: dict[str, Any] = {}
    for user in stream:
        username = username_of(user)
        if not username or username in users:
            continue
        usernames.append(username)
        users[username] = user
    return usernames, users


def score_candidate(profile: Any) -> tuple[int, str]:
    edge_followers = field_of(profile, "edge_followed_by", {}) or {}
    edge_following = field_of(profile, "edge_follow", {}) or {}
    edge_media = field_of(profile, "edge_owner_to_timeline_media", {}) or {}
    followers = max(
        0,
        int(field_of(profile, "follower_count", 0) or field_of(edge_followers, "count", 0) or 0),
    )
    following = max(
        0,
        int(field_of(profile, "following_count", 0) or field_of(edge_following, "count", 0) or 0),
    )
    media_count = max(
        0,
        int(field_of(profile, "media_count", 0) or field_of(edge_media, "count", 0) or 0),
    )
    ratio = following / max(followers, 1)
    score = 42 + min(28, round(ratio * 14))
    if 80 <= followers <= 5_000:
        score += 12
    elif followers > 20_000:
        score -= 10
    if media_count >= 9:
        score += 7
    if not bool(field_of(profile, "is_private", False)):
        score += 5
    if bool(field_of(profile, "is_verified", False)):
        score -= 7
    score = max(35, min(92, score))
    reason = f"attivo, rapporto seguiti/follower {ratio:.2f}, {followers} follower"
    return score, reason


def discover_candidates(
    client: Any,
    seeds: list[str],
    own_followers: set[str],
    own_following: set[str],
    per_seed: int,
    max_candidates: int,
    automatic_seeds: list[Any],
) -> list[dict[str, Any]]:
    raw: dict[str, tuple[Any, str]] = {}
    web_session = getattr(client, "_orbit_auth_mode", "mobile") == "web"
    user_id = str(getattr(client, "_orbit_user_id", None) or client.user_id)
    if not web_session:
        try:
            suggested_payloads = [
                client.user_suggested_profiles(user_id),
                client.discover_recommended_accounts_for_category_v1(user_id),
            ]
            for payload in suggested_payloads:
                for item in payload.get("users", []) or payload.get("items", []):
                    user = item.get("user", item) if isinstance(item, dict) else item
                    username = username_of(user)
                    if (
                        username
                        and username not in own_followers
                        and username not in own_following
                    ):
                        raw.setdefault(username, (user, "suggerimenti Instagram"))
        except Exception as exc:
            print(f"Suggerimenti Instagram non disponibili: {type(exc).__name__}")

    effective_seeds: list[Any] = list(seeds)
    if not effective_seeds:
        # Rotate through accounts already followed and inspect their audiences:
        # this provides automatic, relevant second-degree discovery.
        effective_seeds = list(automatic_seeds)
        random.Random(time.strftime("%Y-%m-%d")).shuffle(effective_seeds)
        effective_seeds = effective_seeds[:3]

    for seed_record in effective_seeds:
        if len(raw) >= max_candidates * 3:
            break
        seed = (
            seed_record.strip().replace("@", "").lower()
            if isinstance(seed_record, str)
            else username_of(seed_record)
        )
        if not seed:
            continue
        try:
            if web_session:
                seed_id = str(
                    field_of(seed_record, "pk", "")
                    or field_of(seed_record, "id", "")
                )
                if not seed_id:
                    seed_profile = client.profile_by_username(seed)
                    seed_id = str(seed_profile.get("id") or seed_profile.get("pk") or "")
                if not seed_id:
                    raise RuntimeError("ID seed non disponibile")
                stream = client.relation_users(seed_id, "followers", amount=per_seed)
            else:
                seed_id = client.user_id_from_username(seed)
                stream = client.iter_user_followers_v1(
                    str(seed_id),
                    amount=per_seed,
                    page_size=min(100, per_seed),
                    order="date_followed_latest",
                )
            for user in stream:
                username = username_of(user)
                if (
                    username
                    and username not in own_followers
                    and username not in own_following
                    and username not in raw
                ):
                    raw[username] = (user, seed)
        except InstagramRateLimited:
            raise
        except Exception as exc:  # one inaccessible seed must not stop the daily snapshot
            print(f"Seed @{seed} saltato: {type(exc).__name__}")
        time.sleep(random.uniform(2.0, 4.0))

    candidates: list[dict[str, Any]] = []
    for username, (short_user, seed) in list(raw.items()):
        if len(candidates) >= max_candidates:
            break
        try:
            user_id = str(
                field_of(short_user, "pk", "")
                or field_of(short_user, "id", "")
                or client.user_id_from_username(username)
            )
            # Relationship payloads already contain the signals needed for the
            # first ranking. Avoid one extra profile request per candidate.
            profile = short_user if web_session else client.user_info(user_id)
            score, signal = score_candidate(profile)
            candidates.append({
                "externalId": f"ig:{user_id}",
                "username": username,
                "displayName": str(field_of(profile, "full_name", "") or username),
                "sourceDetail": f"origine {seed}; {signal}",
                "reason": signal,
                "score": score,
            })
        except InstagramRateLimited:
            raise
        except Exception as exc:
            print(f"Profilo @{username} saltato: {type(exc).__name__}")
        if not web_session:
            time.sleep(random.uniform(1.2, 2.5))
    return sorted(candidates, key=lambda item: int(item["score"]), reverse=True)


def setup(config_path: Path, auth_mode: str) -> None:
    config = load_config(config_path)
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    if auth_mode == "session":
        saved_session_id = keyring.get_password(KEYRING_SERVICE, f"{username}:sessionid")
        if saved_session_id:
            client = web_client_from_session_id(saved_session_id, username)
            print(f"Sessione locale gia presente per @{client.username}; sara riutilizzata.")
        else:
            client = login_with_session_id(username, config_path)
            print(f"Sessione locale salvata per @{client.username}; verifica durante la sincronizzazione.")
        return
    if auth_mode == "browser":
        client = login_with_browser(username, config_path)
        print(f"Sessione browser verificata per @{client.username}.")
        return
    password = getpass.getpass("Password Instagram (resta nel Gestore credenziali Windows): ")
    if not password:
        raise RuntimeError("Password non inserita")
    client = login_for_setup(username, password, session_path(config_path))
    keyring.set_password(KEYRING_SERVICE, username, password)
    print(f"Sessione locale verificata per @{client.username}.")


def sync(config_path: Path) -> None:
    config = load_config(config_path)
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    client = login_saved(config, config_path)
    max_relations = max(0, int(config.get("ORBIT_MAX_RELATIONS", "0") or 0))
    user_id = str(getattr(client, "_orbit_user_id", None) or client.user_id)
    try:
        if getattr(client, "_orbit_auth_mode", "mobile") == "web":
            followers_stream = client.relation_users(user_id, "followers", amount=max_relations)
            following_stream = client.relation_users(user_id, "following", amount=max_relations)
        else:
            followers_stream = client.iter_user_followers_v1(user_id, amount=max_relations, page_size=200)
            following_stream = client.iter_user_following_v1(user_id, amount=max_relations, page_size=200)
    except InstagramRateLimited as exc:
        retry_at = record_rate_limit(config_path, exc.retry_after)
        retry_time = time.strftime("%d/%m/%Y %H:%M", time.localtime(retry_at))
        print(
            "Sessione salvata. Instagram ha applicato un limite temporaneo; "
            f"Orbit riprovera automaticamente dopo le {retry_time}."
        )
        return
    followers_list, _ = collect_users(followers_stream)
    following_list, following_users = collect_users(following_stream)
    followers = set(followers_list)
    following = set(following_list)
    seeds = [item.strip() for item in config.get("ORBIT_DISCOVERY_SEEDS", "").split(",") if item.strip()]
    candidate_retry_pending = False
    try:
        candidates = discover_candidates(
            client,
            seeds,
            followers,
            following,
            per_seed=max(5, min(100, int(config.get("ORBIT_USERS_PER_SEED", "40") or 40))),
            max_candidates=max(1, min(100, int(config.get("ORBIT_MAX_CANDIDATES", "30") or 30))),
            automatic_seeds=list(following_users.values()),
        )
    except InstagramRateLimited as exc:
        record_rate_limit(config_path, exc.retry_after)
        print("Ricerca candidati rinviata per limite Instagram; follower e seguiti saranno comunque salvati.")
        candidates = []
        candidate_retry_pending = True
    endpoint = required(config, "ORBIT_DASHBOARD_URL").rstrip("/") + "/api/agent/instagram-sync"
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {required(config, 'ORBIT_AGENT_TOKEN')}"},
        json={
            "username": username,
            "followers": followers_list,
            "following": following_list,
            "candidates": candidates,
        },
        timeout=180,
    )
    response.raise_for_status()
    result = response.json()
    if not candidate_retry_pending:
        cooldown_path(config_path).unlink(missing_ok=True)
    print(
        f"Sincronizzazione completata: {result['followers']} follower, "
        f"{result['following']} seguiti, {result['candidates']} candidati."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente Instagram read-only per Orbit")
    parser.add_argument("command", choices=("setup", "sync"))
    parser.add_argument("--config", default=".env.agent")
    parser.add_argument("--auth-mode", choices=("session", "browser", "password"), default="session")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.command == "setup":
        setup(config_path, args.auth_mode)
    else:
        sync(config_path)


if __name__ == "__main__":
    main()
