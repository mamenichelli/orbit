from __future__ import annotations

import argparse
import getpass
import json
import random
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


def login_saved(config: dict[str, str], config_path: Path) -> Client:
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    password = keyring.get_password(KEYRING_SERVICE, username)
    if not password:
        raise RuntimeError("Credenziale locale assente. Esegui di nuovo agent/setup.ps1.")
    settings_file = session_path(config_path)
    client = Client()
    if settings_file.exists():
        settings = client.load_settings(settings_file)
        if settings:
            client.set_settings(settings)
    try:
        client.login(username, password)
        client.get_timeline_feed()
    except (LoginRequired, TwoFactorRequired) as exc:
        raise RuntimeError(
            "Instagram richiede una nuova verifica. Esegui agent/setup.ps1 per rinnovare la sessione."
        ) from exc
    client.dump_settings(settings_file)
    return client


def username_of(user: Any) -> str:
    return str(getattr(user, "username", "") or "").strip().lower()


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
) -> list[dict[str, Any]]:
    raw: dict[str, tuple[Any, str]] = {}
    for seed in seeds:
        if len(raw) >= max_candidates * 3:
            break
        seed = seed.strip().replace("@", "").lower()
        if not seed:
            continue
        try:
            seed_id = client.user_id_from_username(seed)
            stream = client.iter_user_followers_v1(
                str(seed_id), amount=per_seed, page_size=min(100, per_seed), order="date_followed_latest"
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
            user_id = str(getattr(short_user, "pk", "") or client.user_id_from_username(username))
            profile = client.user_info(user_id)
            score, signal = score_candidate(profile)
            candidates.append({
                "externalId": f"ig:{user_id}",
                "username": username,
                "displayName": str(getattr(profile, "full_name", "") or username),
                "sourceDetail": f"follower recente di @{seed}; {signal}",
                "reason": signal,
                "score": score,
            })
        except Exception as exc:
            print(f"Profilo @{username} saltato: {type(exc).__name__}")
        time.sleep(random.uniform(1.2, 2.5))
    return sorted(candidates, key=lambda item: int(item["score"]), reverse=True)


def setup(config_path: Path) -> None:
    config = load_config(config_path)
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
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
    followers_list, _ = collect_users(
        client.iter_user_followers_v1(str(client.user_id), amount=max_relations, page_size=200)
    )
    following_list, _ = collect_users(
        client.iter_user_following_v1(str(client.user_id), amount=max_relations, page_size=200)
    )
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
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.command == "setup":
        setup(config_path)
    else:
        sync(config_path)


if __name__ == "__main__":
    main()
