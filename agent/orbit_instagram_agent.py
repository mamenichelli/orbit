from __future__ import annotations

import argparse
import getpass
import json
import random
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

import keyring
import requests
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, TwoFactorRequired


KEYRING_SERVICE = "Orbit Social Growth - Instagram"
INSTAGRAM_WEB_APP_ID = "936619743392459"
WEB_IDENTITY_PATH = "/api/v1/accounts/edit/web_form_data/"


def authenticated_username(payload: dict[str, Any]) -> str:
    """Read the authenticated account, never the profile currently being viewed."""
    form = payload.get("form_data") or {}
    return str(form.get("username") or "").strip().lower()


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


def set_config_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    replaced = False
    output: list[str] = []
    for line in lines:
        if line.strip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        current_key = line.split("=", 1)[0].strip().lstrip("\ufeff")
        if current_key == key:
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def gateway_headers(config: dict[str, str]) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {required(config, 'ORBIT_AGENT_TOKEN')}"}
    sites_bypass = config.get("ORBIT_SIWC_BYPASS_TOKEN", "").strip()
    if sites_bypass:
        headers["OAI-Sites-Authorization"] = f"Bearer {sites_bypass}"
    return headers


def session_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-session.json"


def edge_profile_path(config_path: Path, username: str | None = None) -> Path:
    """Create a one-time Edge profile isolated from Meta/Accounts Center cookies."""
    selected = (username or required(load_config(config_path), "ORBIT_INSTAGRAM_USERNAME")).lower()
    safe_username = re.sub(r"[^a-z0-9_-]", "-", selected)
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"edge-login-{safe_username}-", dir=directory))


def cooldown_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-cooldown.json"


def relation_cache_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-relations-cache.json"


def discovery_state_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-discovery-state.json"


def discovery_result_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-discovery-last.json"


def candidate_history_path(config_path: Path) -> Path:
    directory = config_path.parent / ".orbit-agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "instagram-candidate-history.json"


def load_candidate_history(config_path: Path) -> set[str]:
    path = candidate_history_path(config_path)
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(item).strip().lstrip("@").lower()
            for item in payload.get("usernames", [])
            if str(item).strip()
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return set()


def record_candidate_history(config_path: Path, candidates: list[dict[str, Any]]) -> None:
    usernames = load_candidate_history(config_path)
    usernames.update(
        str(candidate.get("username") or "").strip().lstrip("@").lower()
        for candidate in candidates
        if str(candidate.get("username") or "").strip()
    )
    candidate_history_path(config_path).write_text(
        json.dumps(
            {"updatedAt": int(time.time()), "usernames": sorted(usernames)[-2_000:]},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def save_discovery_result(config_path: Path, status: str, **details: Any) -> None:
    discovery_result_path(config_path).write_text(
        json.dumps(
            {"status": status, "recordedAt": int(time.time()), **details},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def record_rate_limit(config_path: Path, retry_after: int) -> int:
    retry_at = int(time.time()) + max(60, int(retry_after))
    cooldown_path(config_path).write_text(
        json.dumps({"retry_at": retry_at}, separators=(",", ":")),
        encoding="utf-8",
    )
    return retry_at


def cooldown_retry_at(config_path: Path) -> int:
    path = cooldown_path(config_path)
    if not path.exists():
        return 0
    try:
        return max(0, int(json.loads(path.read_text(encoding="utf-8")).get("retry_at", 0)))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0


class InstagramWebSession:
    """Small cookie-based client for Instagram's web JSON endpoints."""

    _orbit_auth_mode = "web"

    def __init__(self, session_id: str, expected_username: str, user_id: str, user_agent: str = ""):
        self.username = expected_username.strip().lstrip("@").lower()
        self.user_id = str(user_id)
        self._orbit_user_id = self.user_id
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Accept": "*/*",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
                "User-Agent": user_agent or (
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

    def search_users(self, query: str, amount: int = 20) -> list[dict[str, Any]]:
        payload = self._json_get(
            "/web/search/topsearch/",
            {
                "context": "blended",
                "query": query.strip(),
                "include_reel": "true",
            },
            f"https://www.instagram.com/explore/search/keyword/?q={query.strip()}",
        )
        users: list[dict[str, Any]] = []
        for item in payload.get("users") or []:
            user = item.get("user", item) if isinstance(item, dict) else None
            if isinstance(user, dict) and username_of(user):
                users.append(user)
            if len(users) >= amount:
                break
        return users

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


def web_client_from_session_id(session_id: str, expected_username: str, user_agent: str = "") -> InstagramWebSession:
    """Create a read-only web session; validation happens during sync."""
    user_match = re.match(r"^\d+", session_id)
    if not user_match or len(session_id) <= 30:
        raise RuntimeError("Session ID non valido")

    user_id = user_match.group(0)
    client = InstagramWebSession(session_id, expected_username, user_id, user_agent)
    return client


def login_with_browser(username: str, config_path: Path) -> InstagramWebSession:
    """Use Edge only to obtain a normal web cookie, then stay on the web API."""
    from playwright.sync_api import sync_playwright

    saved_cookie = keyring.get_password(KEYRING_SERVICE, f"{username}:sessionid")
    if saved_cookie and not keyring.get_password(KEYRING_SERVICE, f"{username}:useragent"):
        # Upgrade old local sessions using the actual installed, regular Edge UA.
        # Save metadata only after Instagram confirms the expected account.
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=False)
            try:
                actual_ua = browser.new_page().evaluate("navigator.userAgent")
            finally:
                browser.close()
        candidate = web_client_from_session_id(saved_cookie, username, actual_ua)
        try:
            identity = candidate._json_get(
                WEB_IDENTITY_PATH, {},
                "https://www.instagram.com/accounts/edit/",
            )
            actual = authenticated_username(identity)
            if actual == username.lower():
                keyring.set_password(KEYRING_SERVICE, f"{username}:useragent", actual_ua)
                print(f"Sessione esistente verificata per @{actual}; nessun nuovo login necessario.")
                return candidate
        except (RuntimeError, requests.RequestException):
            print("Sessione precedente non riutilizzabile; serve la verifica nel browser dedicato.")

    browser_profile = edge_profile_path(config_path, username)
    session_id = ""
    user_agent = ""
    last_mismatch = ""
    last_checked_cookie = ""
    last_verify_at = 0.0
    print(f"Si apre Edge con un NUOVO profilo dedicato a @{username}.")
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(browser_profile),
            channel="msedge",
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        login_url = f"https://www.instagram.com/accounts/login/?next=%2F{username}%2F"
        page.goto(login_url, wait_until="domcontentloaded")
        login_name = page.locator('input[name="username"]')
        try:
            login_name.wait_for(state="visible", timeout=8_000)
        except Exception:
            try:
                switch = page.get_by_text(
                    re.compile(
                        r"Accedi a un altro account|Cambia account|Switch accounts|Log into another account",
                        re.I,
                    )
                ).first
                if switch.count():
                    switch.click(timeout=5_000)
                    login_name.wait_for(state="visible", timeout=8_000)
            except Exception:
                pass
        try:
            if login_name.count():
                login_name.fill(username)
        except Exception:
            pass
        page.bring_to_front()
        print(
            f"Account richiesto: @{username}. Questa finestra Edge è isolata da Primezone e "
            "dagli altri account Meta. Completa il login solo dell'account scelto."
        )
        deadline = time.time() + 600
        while time.time() < deadline:
            cookies = context.cookies(["https://www.instagram.com"])
            cookie = next((item for item in cookies if item.get("name") == "sessionid"), None)
            cookie_value = str(cookie.get("value") or "") if cookie else ""
            if cookie_value and (cookie_value != last_checked_cookie or time.time() - last_verify_at >= 8):
                last_checked_cookie = cookie_value
                last_verify_at = time.time()
                try:
                    response = context.request.get(
                        "https://www.instagram.com" + WEB_IDENTITY_PATH,
                        headers={"X-IG-App-ID": INSTAGRAM_WEB_APP_ID, "Accept": "application/json"},
                        timeout=10_000,
                    )
                    identity = response.json() if response.ok else {}
                    actual = authenticated_username(identity)
                except (ValueError, TypeError):
                    actual = ""
                if actual == username.lower():
                    session_id = cookie_value
                    user_agent = page.evaluate("navigator.userAgent")
                    break
                if actual and actual != last_mismatch:
                    print(
                        f"Profilo attivo @{actual}, ma Orbit attende @{username}. "
                        "La sessione errata non viene salvata: riapro il login pulito."
                    )
                    last_mismatch = actual
                    try:
                        context.clear_cookies()
                        page.goto(login_url, wait_until="domcontentloaded")
                        retry_name = page.locator('input[name="username"]')
                        if retry_name.count():
                            retry_name.fill(username)
                    except Exception:
                        pass
            page.wait_for_timeout(1000)
        context.close()
    shutil.rmtree(browser_profile, ignore_errors=True)
    if not session_id:
        raise RuntimeError("Accesso browser non completato entro 10 minuti")

    client = web_client_from_session_id(session_id, username, user_agent)
    keyring.set_password(KEYRING_SERVICE, f"{username}:useragent", user_agent)
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
        user_agent = keyring.get_password(KEYRING_SERVICE, f"{username}:useragent") or ""
        client = web_client_from_session_id(saved_session_id, username, user_agent)
        identity = client._json_get(
            WEB_IDENTITY_PATH, {},
            "https://www.instagram.com/accounts/edit/",
        )
        actual = authenticated_username(identity)
        if actual != username.lower():
            raise RuntimeError(
                f"Sessione Instagram attiva per @{actual or 'sconosciuto'}, atteso @{username}. "
                "Nessun dato o azione sincronizzati."
            )
        return client

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


def save_relation_cache(
    config_path: Path,
    followers: list[str],
    following: list[str],
    following_users: dict[str, Any],
) -> None:
    automatic_seeds = []
    for username, user in following_users.items():
        user_id = str(field_of(user, "pk", "") or field_of(user, "id", "") or "")
        if user_id:
            automatic_seeds.append({"pk": user_id, "username": username})
    relation_cache_path(config_path).write_text(
        json.dumps(
            {
                "cachedAt": int(time.time()),
                "followers": followers,
                "following": following,
                "automaticSeeds": automatic_seeds,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def load_relation_cache(config_path: Path) -> dict[str, Any]:
    path = relation_cache_path(config_path)
    if not path.exists():
        raise RuntimeError("Cache relazioni assente. Esegui prima il comando sync.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("followers"), list) or not isinstance(payload.get("following"), list):
        raise RuntimeError("Cache relazioni non valida. Esegui nuovamente il comando sync.")
    return payload


def next_discovery_seed(config_path: Path, seeds: list[Any]) -> Any:
    if not seeds:
        raise RuntimeError("Nessun profilo affine disponibile per la ricerca candidati.")
    path = discovery_state_path(config_path)
    index = 0
    if path.exists():
        try:
            index = max(0, int(json.loads(path.read_text(encoding="utf-8")).get("seedIndex", 0)))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            index = 0
    selected = seeds[index % len(seeds)]
    path.write_text(
        json.dumps({"seedIndex": (index + 1) % len(seeds)}, separators=(",", ":")),
        encoding="utf-8",
    )
    return selected


def score_candidate(profile: Any) -> tuple[int, str, dict[str, Any]] | None:
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
    is_private = bool(field_of(profile, "is_private", False))
    is_verified = bool(field_of(profile, "is_verified", False))
    anonymous = bool(field_of(profile, "has_anonymous_profile_picture", False))
    pronouns = field_of(profile, "pronouns", []) or []
    if not isinstance(pronouns, list):
        pronouns = [str(pronouns)]
    public_text = " ".join(
        str(value or "")
        for value in (
            field_of(profile, "biography", ""),
            field_of(profile, "category_name", ""),
            field_of(profile, "city_name", ""),
            field_of(profile, "address_street", ""),
            field_of(profile, "public_email", ""),
            field_of(profile, "external_url", ""),
            " ".join(str(item) for item in pronouns),
        )
    ).lower()
    italian_strong = bool(re.search(
        r"\b(italia|italiana|italiano|roma|milano|napoli|torino|bologna|firenze|palermo|"
        r"genova|venezia|verona|bari|catania|sardegna|sicilia|toscana|lombardia|lazio)\b|\.it\b",
        public_text,
    ))
    # Italian language alone is not enough: require a public declaration of
    # Italy/Italian identity, an Italian location, or an Italian web domain.
    italian_signal = italian_strong
    female_self_declared = bool(re.search(
        r"\b(she\s*/\s*her|lei|donna|ragazza|mamma|moglie|imprenditrice|"
        r"fondatrice|fotografa|autrice|italiana)\b",
        public_text,
    ))
    male_self_declared = bool(re.search(
        r"\b(he\s*/\s*him|uomo|ragazzo|marito|imprenditore|fondatore|"
        r"fotografo|autore|italiano)\b",
        public_text,
    ))
    edges = field_of(edge_media, "edges", []) or []
    timestamps = [
        int(field_of(field_of(edge, "node", {}) or {}, "taken_at_timestamp", 0) or 0)
        for edge in edges
    ]
    latest_timestamp = max(timestamps, default=0)
    days_since_post = (
        max(0, int((time.time() - latest_timestamp) / 86_400))
        if latest_timestamp
        else None
    )

    # Hard filters: these profiles consume follow slots but show little evidence
    # that they reciprocate or are maintained by a real, active person.
    if not italian_signal or male_self_declared or anonymous or media_count < 3 or followers <= 0 or following < 50:
        return None
    if followers > 10_000 and ratio < 0.50:
        return None
    if followers > 500 and ratio < 0.20:
        return None
    if not is_private and days_since_post is not None and days_since_post > 120:
        return None

    score = 32
    if ratio >= 1.0:
        score += 30
    elif ratio >= 0.65:
        score += 25
    elif ratio >= 0.40:
        score += 18
    elif ratio >= 0.25:
        score += 10
    else:
        score += 4
    if 50 <= followers <= 3_000:
        score += 12
    elif followers <= 8_000:
        score += 7
    if media_count >= 12:
        score += 8
    elif media_count >= 6:
        score += 4
    if days_since_post is not None:
        if days_since_post <= 30:
            score += 10
        elif days_since_post <= 90:
            score += 5
    if is_verified:
        score -= 6
    if female_self_declared:
        score += 12
    score = max(35, min(92, score))
    activity_score = min(
        100,
        (40 if media_count >= 12 else 25 if media_count >= 6 else 15)
        + (45 if days_since_post is not None and days_since_post <= 30 else 25 if days_since_post is not None and days_since_post <= 90 else 15 if is_private else 0)
        + (15 if not anonymous else 0),
    )
    recency = (
        f"ultimo post {days_since_post}g fa"
        if days_since_post is not None
        else "attivita privata non visibile"
    )
    reason = (
        f"profilo italiano{' con identita femminile dichiarata' if female_self_declared else ' con genere non dichiarato'}, "
        f"{media_count} post, {recency}, segue {following} profili su {followers} follower "
        f"(rapporto {ratio:.2f})"
    )
    return score, reason, {
        "followerCount": followers,
        "followingCount": following,
        "mediaCount": media_count,
        "isPrivate": is_private,
        "lastPostAt": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(latest_timestamp))
            if latest_timestamp
            else None
        ),
        "activityScore": activity_score,
        "italianSignal": True,
        "femaleSelfDeclared": female_self_declared,
    }


def parse_compact_count(value: str) -> int:
    """Parse Instagram counters such as 1.693, 1,2 mila, 3.4K or 2M."""
    cleaned = re.sub(r"\s+", "", str(value or "").strip().lower())
    multiplier = 1
    for suffix, factor in (("mila", 1_000), ("mio", 1_000_000), ("mln", 1_000_000), ("k", 1_000), ("m", 1_000_000)):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            multiplier = factor
            break
    if multiplier > 1:
        normalized = cleaned.replace(".", "").replace(",", ".") if cleaned.count(",") == 1 else cleaned.replace(",", "")
        try:
            return max(0, int(float(normalized) * multiplier))
        except ValueError:
            return 0
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", "")
    else:
        cleaned = cleaned.replace(",", "").replace(".", "")
    try:
        return max(0, int(cleaned))
    except ValueError:
        return 0


def browser_profile_payload(description: str, header_text: str, title: str = "") -> dict[str, Any]:
    """Convert public profile text into the same shape used by score_candidate."""
    combined = " ".join(part.strip() for part in (description, header_text) if part and part.strip())

    def metric(labels: str) -> int:
        match = re.search(
            rf"([\d.,]+\s*(?:mila|mio|mln|[km])?)\s+(?:{labels})\b",
            combined,
            re.I,
        )
        return parse_compact_count(match.group(1)) if match else 0

    private_text = combined.lower()
    display_name = re.sub(r"\s*\(@[^)]+\).*$", "", title).strip() or "Instagram"
    return {
        "full_name": display_name,
        "biography": combined,
        "follower_count": metric(r"followers?|follower"),
        "following_count": metric(r"following|seguiti|profili\s+seguiti"),
        "media_count": metric(r"posts?|post"),
        "is_private": "account is private" in private_text or "account è privato" in private_text,
        "has_anonymous_profile_picture": False,
    }


def fetch_interaction_signals(
    config: dict[str, str],
    own_followers: set[str],
    own_following: set[str],
) -> dict[str, dict[str, Any]]:
    """Read recurring commenters from the official connected-account gateway."""
    try:
        dashboard = required(config, "ORBIT_DASHBOARD_URL").rstrip("/")
        session_response = requests.get(
            f"{dashboard}/api/meta/snapshot",
            headers=gateway_headers(config),
            timeout=30,
        )
        session_response.raise_for_status()
        session = session_response.json()
        gateway_response = requests.get(
            str(session["gatewayUrl"]),
            headers={"Authorization": f"Bearer {session['accessToken']}"},
            timeout=90,
        )
        gateway_response.raise_for_status()
        opportunities = gateway_response.json().get("opportunities", [])
    except (KeyError, TypeError, ValueError, RuntimeError, requests.RequestException):
        return {}

    signals: dict[str, dict[str, Any]] = {}
    for item in opportunities:
        if not isinstance(item, dict) or str(item.get("platform") or "").lower() != "instagram":
            continue
        username = str(item.get("username") or "").strip().lstrip("@").lower()
        interactions = max(0, int(item.get("interactions") or 0))
        if (
            not username
            or interactions < 2
            or username in own_followers
            or username in own_following
        ):
            continue
        current = signals.get(username)
        if current is None or interactions > int(current.get("interactions") or 0):
            signals[username] = {
                "interactions": interactions,
                "gatewayScore": max(0, min(99, int(item.get("score") or 0))),
            }
    return signals


def fetch_planner_follow_usernames(config: dict[str, str]) -> set[str]:
    """Avoid rediscovering profiles already proposed, completed or skipped today."""
    try:
        dashboard = required(config, "ORBIT_DASHBOARD_URL").rstrip("/")
        response = requests.get(
            f"{dashboard}/api/planner",
            headers=gateway_headers(config),
            timeout=30,
        )
        response.raise_for_status()
        actions = response.json().get("actions", [])
    except (KeyError, TypeError, ValueError, RuntimeError, requests.RequestException):
        return set()
    return {
        str(action.get("username") or "").strip().lstrip("@").lower()
        for action in actions
        if isinstance(action, dict)
        and action.get("action_type") in {"follow", "follow_back"}
        and str(action.get("username") or "").strip()
    }


def discover_candidates_with_browser(
    config_path: Path,
    queries: list[str],
    seed_usernames: list[str],
    interaction_signals: dict[str, dict[str, Any]],
    own_followers: set[str],
    own_following: set[str],
    max_candidates: int,
    max_profile_checks: int = 80,
) -> list[dict[str, Any]]:
    """Use the authenticated Instagram UI when private JSON search is throttled."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    browser_profile = edge_profile_path(config_path)
    if not browser_profile.exists():
        raise RuntimeError("Profilo browser Instagram assente; esegui setup.ps1 -AuthMode browser")

    ignored_routes = {
        "accounts", "about", "api", "developer", "direct", "directory", "emails",
        "explore", "legal", "privacy", "reels", "stories", "terms", "web",
    }
    discovered: dict[str, str] = {
        username: f"interazioni ricevute ({int(signal.get('interactions') or 0)})"
        for username, signal in sorted(
            interaction_signals.items(),
            key=lambda item: int(item[1].get("interactions") or 0),
            reverse=True,
        )
        if username not in own_followers and username not in own_following
    }
    candidates: list[dict[str, Any]] = []
    checked_profiles = 0
    profiles_without_metrics = 0
    profiles_rejected = 0
    config = load_config(config_path)
    configured_username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    saved_session_id = keyring.get_password(KEYRING_SERVICE, f"{configured_username}:sessionid")
    with sync_playwright() as playwright:
        browser = None
        if saved_session_id:
            # An isolated context avoids failing when the scheduled task still owns
            # the persistent Edge profile. Authentication is restored from the
            # session cookie kept in Windows Credential Manager.
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                locale="it-IT",
                viewport={"width": 1440, "height": 1000},
                **({"user_agent": keyring.get_password(KEYRING_SERVICE, f"{configured_username}:useragent")}
                   if keyring.get_password(KEYRING_SERVICE, f"{configured_username}:useragent") else {}),
            )
        else:
            context = playwright.chromium.launch_persistent_context(
                str(browser_profile),
                channel="msedge",
                headless=True,
                locale="it-IT",
                viewport={"width": 1440, "height": 1000},
            )
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font"}
            else route.continue_(),
        )
        if saved_session_id:
            user_match = re.match(r"^\d+", saved_session_id)
            cookies = [{
                "name": "sessionid",
                "value": saved_session_id,
                "domain": ".instagram.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
            }]
            if user_match:
                cookies.append({
                    "name": "ds_user_id",
                    "value": user_match.group(0),
                    "domain": ".instagram.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                    "sameSite": "Lax",
                })
            context.add_cookies(cookies)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            sources = [
                (f"https://www.instagram.com/explore/search/keyword/?q={quote_plus(query)}", query)
                for query in queries
            ]
            sources.extend(
                (f"https://www.instagram.com/{seed}/", f"rete di @{seed}")
                for seed in seed_usernames[:12]
            )
            sources.append(("https://www.instagram.com/explore/people/suggested/", "suggeriti Instagram"))
            for source, source_label in sources:
                try:
                    page.goto(source, wait_until="domcontentloaded", timeout=15_000)
                    page.wait_for_timeout(1_500)
                    if "/accounts/login" in page.url:
                        raise RuntimeError("Sessione browser Instagram scaduta")
                    paths = page.locator('a[href^="/"]').evaluate_all(
                        "elements => elements.map(element => element.getAttribute('href') || '')",
                    )
                    for path in paths:
                        username = str(path).strip("/").split("/", 1)[0].lower()
                        if (
                            re.fullmatch(r"[a-z0-9._]{1,30}", username)
                            and username not in ignored_routes
                            and username not in own_followers
                            and username not in own_following
                            and username not in discovered
                        ):
                            discovered[username] = source_label
                except PlaywrightTimeoutError:
                    continue
                except Exception as exc:
                    if isinstance(exc, RuntimeError) and "scaduta" in str(exc).lower():
                        raise
                    continue
                if len(discovered) >= max_profile_checks:
                    break

            for username, source_label in list(discovered.items())[:max_profile_checks]:
                if len(candidates) >= max_candidates:
                    break
                try:
                    page.goto(
                        f"https://www.instagram.com/{username}/",
                        wait_until="domcontentloaded",
                        timeout=15_000,
                    )
                    page.wait_for_timeout(1_000)
                    if "/accounts/login" in page.url:
                        raise RuntimeError("Sessione browser Instagram scaduta")
                    description = page.locator('meta[property="og:description"]').get_attribute("content") or ""
                    title = page.locator('meta[property="og:title"]').get_attribute("content") or ""
                    header = page.locator("header").inner_text(timeout=3_000)
                    profile = browser_profile_payload(description, header, title)
                    profile["username"] = username
                    checked_profiles += 1
                    if not profile["follower_count"] or not profile["following_count"] or not profile["media_count"]:
                        profiles_without_metrics += 1
                    scored = score_candidate(profile)
                    if scored is None:
                        profiles_rejected += 1
                        continue
                    score, signal, metrics = scored
                    interaction_count = int((interaction_signals.get(username) or {}).get("interactions") or 0)
                    if interaction_count:
                        score = min(99, score + min(24, interaction_count * 3))
                        signal = f"ha gia interagito {interaction_count} volte; {signal}"
                    candidates.append({
                        "externalId": f"ig:browser:{username}",
                        "username": username,
                        "displayName": str(profile.get("full_name") or username),
                        "sourceDetail": f"Esplora Instagram: {source_label}; {signal}",
                        "reason": signal,
                        "score": score,
                        "interactions": interaction_count,
                        **metrics,
                    })
                except PlaywrightTimeoutError:
                    continue
                except Exception as exc:
                    if isinstance(exc, RuntimeError) and "scaduta" in str(exc).lower():
                        raise
                    continue
        finally:
            context.close()
            if browser is not None:
                browser.close()

    print(
        "Diagnostica browser: "
        f"{len(discovered)} profili scoperti, {checked_profiles} controllati, "
        f"{profiles_without_metrics} senza metriche leggibili, {profiles_rejected} esclusi dai filtri."
    )

    return sorted(
        candidates,
        key=lambda item: (
            int(item.get("interactions") or 0),
            bool(item.get("femaleSelfDeclared")),
            int(item["score"]),
        ),
        reverse=True,
    )


def discover_candidates(
    client: Any,
    seeds: list[Any],
    own_followers: set[str],
    own_following: set[str],
    per_seed: int,
    max_candidates: int,
    automatic_seeds: list[Any],
    search_queries: list[str] | None = None,
) -> list[dict[str, Any]]:
    raw: dict[str, tuple[Any, str]] = {}
    web_session = getattr(client, "_orbit_auth_mode", "mobile") == "web"
    user_id = str(getattr(client, "_orbit_user_id", None) or client.user_id)
    for query in search_queries or []:
        try:
            for user in client.search_users(query, amount=per_seed):
                username = username_of(user)
                if (
                    username
                    and username not in own_followers
                    and username not in own_following
                ):
                    raw.setdefault(username, (user, f"ricerca {query}"))
        except InstagramRateLimited:
            raise
        except Exception as exc:
            print(f"Ricerca '{query}' saltata: {type(exc).__name__}")

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
    if not effective_seeds and not search_queries:
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
    checked_profiles = 0
    for username, (short_user, seed) in list(raw.items()):
        if len(candidates) >= max_candidates:
            break
        if web_session and checked_profiles >= min(30, max(12, max_candidates * 3)):
            break
        try:
            user_id = str(
                field_of(short_user, "pk", "")
                or field_of(short_user, "id", "")
                or client.user_id_from_username(username)
            )
            profile = client.profile_by_username(username) if web_session else client.user_info(user_id)
            checked_profiles += 1
            scored = score_candidate(profile)
            if scored is not None:
                score, signal, metrics = scored
                candidates.append({
                    "externalId": f"ig:{user_id}",
                    "username": username,
                    "displayName": str(field_of(profile, "full_name", "") or username),
                    "sourceDetail": f"origine {seed}; {signal}",
                    "reason": signal,
                    "score": score,
                    **metrics,
                })
        except InstagramRateLimited:
            if candidates:
                print("Arricchimento candidati interrotto dal limite Instagram; invio i profili gia verificati.")
                break
            raise
        except Exception as exc:
            print(f"Profilo @{username} saltato: {type(exc).__name__}")
        time.sleep(random.uniform(1.5, 2.8))
    return sorted(
        candidates,
        key=lambda item: (bool(item.get("femaleSelfDeclared")), int(item["score"])),
        reverse=True,
    )


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


def send_snapshot(
    config: dict[str, str],
    followers: list[str],
    following: list[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint = required(config, "ORBIT_DASHBOARD_URL").rstrip("/") + "/api/agent/instagram-sync"
    response = requests.post(
        endpoint,
        headers=gateway_headers(config),
        json={
            "username": required(config, "ORBIT_INSTAGRAM_USERNAME"),
            "followers": followers,
            "following": following,
            "candidates": candidates,
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def sync(config_path: Path) -> None:
    """Refresh relations only; candidate discovery runs separately in small batches."""
    config = load_config(config_path)
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
    save_relation_cache(config_path, followers_list, following_list, following_users)
    result = send_snapshot(config, followers_list, following_list, [])
    print(
        f"Sincronizzazione completata: {result['followers']} follower, "
        f"{result['following']} seguiti. Cache locale pronta per la ricerca graduale."
    )


def discover(config_path: Path) -> None:
    """Inspect one audience and a few profiles, preserving verified server candidates."""
    config = load_config(config_path)
    cached = load_relation_cache(config_path)
    followers_list = [str(item).lower() for item in cached.get("followers", []) if str(item).strip()]
    following_list = [str(item).lower() for item in cached.get("following", []) if str(item).strip()]
    previously_proposed = load_candidate_history(config_path) | fetch_planner_follow_usernames(config)
    discovery_following = set(following_list) | previously_proposed
    search_queries = [
        item.strip() for item in config.get(
            "ORBIT_DISCOVERY_QUERIES",
            "mamma italiana roma,mamma italiana milano,imprenditrice italiana,"
            "psicologa roma,psicologa milano,benessere donna italia,fitness donna italiana,"
            "travel blogger italiana,creator italiana roma,fotografa italiana",
        ).split(",") if item.strip()
    ]
    selected_query = str(next_discovery_seed(config_path, search_queries))
    selected_index = search_queries.index(selected_query)
    ordered_queries = search_queries[selected_index:] + search_queries[:selected_index]
    browser_seed_usernames = [
        username_of(item)
        for item in cached.get("automaticSeeds", [])
        if username_of(item)
    ]
    random.Random(f"{time.strftime('%Y-%m-%d')}:{selected_query}").shuffle(browser_seed_usernames)
    browser_seed_usernames = browser_seed_usernames[:40]
    interaction_signals = fetch_interaction_signals(
        config,
        set(followers_list),
        discovery_following,
    )
    max_candidates = max(10, min(20, int(config.get("ORBIT_MAX_CANDIDATES", "20") or 20)))

    def browser_fallback(reason: str, existing_candidates: list[dict[str, Any]] | None = None) -> bool:
        try:
            browser_candidates = discover_candidates_with_browser(
                config_path,
                ordered_queries,
                browser_seed_usernames,
                interaction_signals,
                set(followers_list),
                discovery_following,
                max_candidates=max_candidates,
                max_profile_checks=max(
                    30,
                    min(120, int(config.get("ORBIT_BROWSER_PROFILE_CHECKS", "80") or 80)),
                ),
            )
        except Exception as exc:
            error_message = re.sub(r"\s+", " ", str(exc)).strip()[:300]
            save_discovery_result(
                config_path,
                "browser_fallback_failed",
                reason=reason,
                error=type(exc).__name__,
                errorMessage=error_message,
                seed=f"ricerca:{selected_query}",
            )
            print(f"Ricerca browser non disponibile: {type(exc).__name__}: {error_message}")
            return False
        combined_by_username: dict[str, dict[str, Any]] = {}
        for candidate in [*(existing_candidates or []), *browser_candidates]:
            username = str(candidate.get("username") or "").strip().lower()
            if username and username not in combined_by_username:
                combined_by_username[username] = candidate
        combined_candidates = list(combined_by_username.values())[:max_candidates]
        result = send_snapshot(config, followers_list, following_list, combined_candidates)
        record_candidate_history(config_path, combined_candidates)
        save_discovery_result(
            config_path,
            "completed_browser",
            reason=reason,
            candidatesFound=len(combined_candidates),
            candidatesAccepted=int(result.get("candidates", 0) or 0),
            seed=f"ricerca:{selected_query}",
        )
        print(
            f"Ricerca browser completata: {result['candidates']} nuove candidate verificate. "
            "I profili gia seguiti o non italiani sono stati esclusi."
        )
        return True

    retry_at = cooldown_retry_at(config_path)
    if retry_at > int(time.time()):
        if browser_fallback("api_cooldown"):
            return
        retry_time = time.strftime("%d/%m/%Y %H:%M", time.localtime(retry_at))
        save_discovery_result(config_path, "cooldown", retryAt=retry_at)
        print(f"Limite Instagram ancora attivo; prossimo tentativo automatico dopo le {retry_time}.")
        return

    client = login_saved(config, config_path)
    try:
        candidates = discover_candidates(
            client,
            [],
            set(followers_list),
            discovery_following,
            per_seed=max(5, min(20, int(config.get("ORBIT_USERS_PER_SEED", "12") or 12))),
            max_candidates=max_candidates,
            automatic_seeds=[],
            search_queries=[selected_query],
        )
    except InstagramRateLimited as exc:
        retry_at = record_rate_limit(config_path, exc.retry_after)
        if browser_fallback("api_rate_limited"):
            return
        retry_time = time.strftime("%d/%m/%Y %H:%M", time.localtime(retry_at))
        save_discovery_result(config_path, "rate_limited", retryAt=retry_at)
        print(f"Ricerca graduale rinviata; nuovo tentativo automatico dopo le {retry_time}.")
        return

    if len(candidates) < min(10, max_candidates) and browser_fallback(
        "api_insufficient_candidates",
        candidates,
    ):
        cooldown_path(config_path).unlink(missing_ok=True)
        return

    result = send_snapshot(config, followers_list, following_list, candidates)
    record_candidate_history(config_path, candidates)
    cooldown_path(config_path).unlink(missing_ok=True)
    save_discovery_result(
        config_path,
        "completed",
        candidatesFound=len(candidates),
        candidatesAccepted=int(result.get("candidates", 0) or 0),
        seed=f"ricerca:{selected_query}",
    )
    print(
        f"Ricerca graduale completata: {result['candidates']} nuove candidate verificate. "
        "Le candidate gia salvate restano disponibili."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente Instagram read-only per Orbit")
    parser.add_argument("command", choices=("setup", "sync", "discover"))
    parser.add_argument("--config", default=".env.agent")
    parser.add_argument("--auth-mode", choices=("session", "browser", "password"), default="session")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.command == "setup":
        setup(config_path, args.auth_mode)
    elif args.command == "sync":
        sync(config_path)
    else:
        discover(config_path)


if __name__ == "__main__":
    main()
