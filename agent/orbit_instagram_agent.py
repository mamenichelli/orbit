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


def load_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise RuntimeError(f"Configurazione mancante: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
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


def web_client_from_session_id(session_id: str, expected_username: str) -> Client:
    """Create a read-only Instagram Web session without using the mobile API."""
    user_match = re.match(r"^\d+", session_id)
    if not user_match or len(session_id) <= 30:
        raise RuntimeError("Session ID non valido")

    user_id = user_match.group(0)
    client = Client()
    client.settings["cookies"] = {
        "sessionid": session_id,
        "ds_user_id": user_id,
    }
    client.init()
    # Keep browser sessions cookie-based. A mobile Authorization header is what
    # makes Instagram reject this otherwise valid web session with HTTP 403.
    client.authorization_data = {}
    client.private.headers.pop("Authorization", None)
    client.public.cookies.set("sessionid", session_id)
    client.public.cookies.set("ds_user_id", user_id)

    try:
        profile = client.user_short_gql(user_id, use_cache=False)
    except Exception as exc:
        raise RuntimeError(
            "Instagram non accetta piu questa sessione web. Esci e rientra su "
            "instagram.com nel browser, poi copia il nuovo cookie sessionid."
        ) from exc

    logged_username = str(profile.username or "").lower()
    if logged_username != expected_username.lower():
        raise RuntimeError(
            f"La sessione appartiene a @{logged_username}, Orbit attende @{expected_username}"
        )
    client.username = logged_username
    client._orbit_auth_mode = "web"  # type: ignore[attr-defined]
    client._orbit_user_id = user_id  # type: ignore[attr-defined]
    return client


def login_with_browser(username: str, config_path: Path) -> Client:
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


def login_with_session_id(username: str, config_path: Path) -> Client:
    session_id = getpass.getpass("Session ID Instagram (input nascosto, resta sul PC): ").strip()
    if not session_id:
        raise RuntimeError("Session ID non inserito")
    client = web_client_from_session_id(session_id, username)
    keyring.set_password(KEYRING_SERVICE, f"{username}:sessionid", session_id)
    return client


def login_saved(config: dict[str, str], config_path: Path) -> Client:
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
    followers = max(0, int(getattr(profile, "follower_count", 0) or 0))
    following = max(0, int(getattr(profile, "following_count", 0) or 0))
    media_count = max(0, int(getattr(profile, "media_count", 0) or 0))
    ratio = following / max(followers, 1)
    score = 42 + min(28, round(ratio * 14))
    if 80 <= followers <= 5_000:
        score += 12
    elif followers > 20_000:
        score -= 10
    if media_count >= 9:
        score += 7
    if not bool(getattr(profile, "is_private", False)):
        score += 5
    if bool(getattr(profile, "is_verified", False)):
        score -= 7
    score = max(35, min(92, score))
    reason = f"attivo, rapporto seguiti/follower {ratio:.2f}, {followers} follower"
    return score, reason


def discover_candidates(
    client: Client,
    seeds: list[str],
    own_followers: set[str],
    own_following: set[str],
    per_seed: int,
    max_candidates: int,
    automatic_seeds: list[str],
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

    effective_seeds = list(seeds)
    if not effective_seeds:
        # Rotate through accounts already followed and inspect their audiences:
        # this provides automatic, relevant second-degree discovery.
        effective_seeds = list(automatic_seeds)
        random.Random(time.strftime("%Y-%m-%d")).shuffle(effective_seeds)
        effective_seeds = effective_seeds[:3]

    for seed in effective_seeds:
        if len(raw) >= max_candidates * 3:
            break
        seed = seed.strip().replace("@", "").lower()
        if not seed:
            continue
        try:
            if web_session:
                seed_profile = client.user_info_by_username_v2_gql(seed)
                seed_id = str(seed_profile.pk)
                stream = client.user_followers_gql(seed_id, amount=per_seed)
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
            profile = client.user_info_v2_gql(user_id) if web_session else client.user_info(user_id)
            score, signal = score_candidate(profile)
            candidates.append({
                "externalId": f"ig:{user_id}",
                "username": username,
                "displayName": str(getattr(profile, "full_name", "") or username),
                "sourceDetail": f"origine {seed}; {signal}",
                "reason": signal,
                "score": score,
            })
        except Exception as exc:
            print(f"Profilo @{username} saltato: {type(exc).__name__}")
        time.sleep(random.uniform(1.2, 2.5))
    return sorted(candidates, key=lambda item: int(item["score"]), reverse=True)


def setup(config_path: Path, auth_mode: str) -> None:
    config = load_config(config_path)
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    if auth_mode == "session":
        client = login_with_session_id(username, config_path)
        print(f"Sessione locale verificata per @{client.username}.")
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
    if getattr(client, "_orbit_auth_mode", "mobile") == "web":
        followers_stream = client.user_followers_gql(user_id, amount=max_relations)
        following_stream = client.user_following_gql(user_id, amount=max_relations)
    else:
        followers_stream = client.iter_user_followers_v1(user_id, amount=max_relations, page_size=200)
        following_stream = client.iter_user_following_v1(user_id, amount=max_relations, page_size=200)
    followers_list, _ = collect_users(followers_stream)
    following_list, _ = collect_users(following_stream)
    followers = set(followers_list)
    following = set(following_list)
    seeds = [item.strip() for item in config.get("ORBIT_DISCOVERY_SEEDS", "").split(",") if item.strip()]
    candidates = discover_candidates(
        client,
        seeds,
        followers,
        following,
        per_seed=max(5, min(100, int(config.get("ORBIT_USERS_PER_SEED", "40") or 40))),
        max_candidates=max(1, min(100, int(config.get("ORBIT_MAX_CANDIDATES", "30") or 30))),
        automatic_seeds=following_list,
    )
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
