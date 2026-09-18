"""Orbit Directs controller.

Keeps the General-DM collector alive when Instagram expires, accepts an explicit
reauth request from Orbit, scans all reachable General history without the old
fixed page limits, and extends manual likes to shared reels.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

import requests

import orbit_manual_instagram as manual
from orbit_instagram_agent import load_config, required, login_with_browser, set_config_value
from orbit_browser_actions import gateway_post

CONTENT_PATH = re.compile(r"^/(?:p|reel)/([A-Za-z0-9_-]+)/?$")
_ORIGINAL_RANGE = range
_ORIGINAL_READ_VISIBLE = manual.read_visible_posts
_ORIGINAL_LIKE_POST = manual.like_post


def _content_id(href: str) -> str | None:
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc not in {"instagram.com", "www.instagram.com"}:
        return None
    match = CONTENT_PATH.fullmatch(parsed.path)
    return match.group(1) if match else None


def _expanded_range(*args):
    # collect() used a hard 80-step cap when scrolling the General conversation list.
    # Its stable/empty checks still stop naturally; this removes the practical cap.
    if len(args) == 1 and args[0] == 80:
        return _ORIGINAL_RANGE(1_000_000)
    return _ORIGINAL_RANGE(*args)


def _read_visible_content(page, known_cards=None, known_events=None, on_found=None):
    # Existing collector already handles /p/ cards. Replacing post_id lets clicked
    # cards resolve /reel/ URLs too; this extra pass catches direct reel links.
    found, preserved = _ORIGINAL_READ_VISIBLE(page, known_cards, known_events, on_found)
    hrefs = page.locator('a[href*="/reel/"]').evaluate_all(
        "nodes=>nodes.map(n=>n.getAttribute('href')||'')")
    for href in hrefs:
        shortcode = _content_id(href)
        if not shortcode:
            continue
        metadata = found.setdefault(shortcode, {"contentKind": "reel"})
        if on_found:
            on_found(shortcode, metadata)
    return found, preserved


def _like_reel(page, shortcode: str) -> bool:
    manual.checked_collection_navigation(page, f"https://www.instagram.com/reel/{shortcode}/")
    main = page.locator("article").first
    if main.count() == 0:
        main = page.locator("main").first
    if main.count() == 0:
        raise RuntimeError(f"Reel {shortcode}: contenuto non riconosciuto")
    icons = main.locator(
        'svg[aria-label="Mi piace"],svg[aria-label="Like"],'
        'svg[aria-label="Non mi piace più"],svg[aria-label="Unlike"]')
    icons.first.wait_for(state="visible", timeout=25_000)
    selected = icons.evaluate_all('''nodes => {
      const icon=nodes.find(n=>{const r=n.getBoundingClientRect();return r.width>=20&&r.height>=20;});
      if(!icon)return null;icon.setAttribute('data-orbit-post-like-icon','true');return icon.getAttribute('aria-label');
    }''')
    if selected in {"Non mi piace più", "Unlike"}:
        return False
    button = main.locator('[data-orbit-post-like-icon="true"]')
    if button.count() != 1:
        raise RuntimeError(f"Reel {shortcode}: pulsante Mi piace non trovato")
    button.click()
    page.wait_for_function('''() => {
      const root=document.querySelector('article')||document.querySelector('main');
      return root && Array.from(root.querySelectorAll('svg[aria-label="Non mi piace più"],svg[aria-label="Unlike"]')).some(n=>{
        const r=n.getBoundingClientRect();return r.width>=20&&r.height>=20;
      });
    }''', timeout=15_000)
    return True


def _like_content(page, shortcode: str) -> bool:
    try:
        return _ORIGINAL_LIKE_POST(page, shortcode)
    except Exception as post_error:
        try:
            return _like_reel(page, shortcode)
        except Exception as reel_error:
            raise RuntimeError(f"Contenuto {shortcode}: post/reel non raggiungibile") from reel_error


def install_compatibility_overrides() -> None:
    manual.range = _expanded_range
    manual.post_id = _content_id
    manual.read_visible_posts = _read_visible_content
    manual.like_post = _like_content


def _collection_control(config, action, **fields):
    return gateway_post(config, "/api/agent/instagram-collection", {
        "action": action,
        "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
        **fields,
    })


def _auth_control(config, action, **fields):
    return gateway_post(config, "/api/agent/instagram-browser-auth", {
        "action": action,
        "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
        **fields,
    })


def _restart_manual_worker() -> None:
    """Restart only the worker child; the PowerShell wrapper brings it back."""
    command = (
        "$self=$PID; "
        "Get-CimInstance Win32_Process | "
        "Where-Object {$_.Name -match '^python(w)?\\.exe

def watch(config_path: Path, interval: int) -> None:
    install_compatibility_overrides()
    with manual.collector_lock(config_path):
        config = load_config(config_path)
        collection = {"requested_at": 0, "completed_request_at": 0}
        auth = {"requested_at": 0, "completed_request_at": 0}
        stop = threading.Event()

        def heartbeat():
            while not stop.is_set():
                try:
                    collection.update(_collection_control(config, "poll"))
                except requests.RequestException:
                    pass
                try:
                    auth.update(_auth_control(config, "poll"))
                except requests.RequestException:
                    pass
                stop.wait(3)

        threading.Thread(target=heartbeat, daemon=True).start()
        completed = attempted = auth_attempted = 0
        next_scan = 0.0
        try:
            while True:
                requested_auth = int(auth.get("requested_at", 0) or 0)
                completed_auth = int(auth.get("completed_request_at", 0) or 0)
                if requested_auth > max(completed_auth, auth_attempted):
                    auth_attempted = requested_auth
                    version = requested_auth
                    try:
                        selected_username = str(
                            auth.get("requested_username")
                            or required(config, "ORBIT_INSTAGRAM_USERNAME")
                        ).strip().lstrip("@").lower()
                        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", selected_username):
                            raise RuntimeError("Username Instagram richiesto non valido")
                        started = _auth_control(config, "started")
                        version = int(started.get("started_request_at", version) or version)
                        selected_username = str(
                            started.get("requested_username") or selected_username
                        ).strip().lstrip("@").lower()
                        print(
                            f"Rinnovo richiesto da Orbit per @{selected_username}: apro Edge pulito.",
                            flush=True,
                        )
                        login_with_browser(selected_username, config_path)
                        previous_username = required(config, "ORBIT_INSTAGRAM_USERNAME").lower()
                        if selected_username != previous_username:
                            set_config_value(
                                config_path,
                                "ORBIT_INSTAGRAM_USERNAME",
                                selected_username,
                            )
                            config["ORBIT_INSTAGRAM_USERNAME"] = selected_username
                            print(
                                f"Account operativo Orbit cambiato: @{previous_username} -> @{selected_username}.",
                                flush=True,
                            )
                        _auth_control(
                            config,
                            "finished",
                            version=version,
                            accountUsername=selected_username,
                        )
                        auth["completed_request_at"] = version
                        auth["requested_username"] = ""
                        _restart_manual_worker()
                        next_scan = 0
                        print(
                            f"Sessione Instagram verificata per @{selected_username}; Generali di nuovo attivo.",
                            flush=True,
                        )
                    except Exception as exc:
                        message = re.sub(r"\s+", " ", str(exc)).strip()[:300] or type(exc).__name__
                        try:
                            _auth_control(config, "failed", version=version, message=message)
                        except requests.RequestException:
                            pass
                    continue

                if time.monotonic() < next_scan and int(collection.get("requested_at", 0) or 0) <= max(completed, attempted):
                    time.sleep(1)
                    continue

                version = 0
                try:
                    scan = _collection_control(config, "started")
                    version = int(scan.get("started_request_at", 0) or 0)
                    attempted = max(attempted, version)
                    started_at = time.monotonic()
                    # A huge bound removes the old 1/40-history-page limit; collect()
                    # still stops naturally when the chat cannot scroll any farther.
                    result = manual.collect(
                        config_path,
                        publish_approved=True,
                        history_pages=1_000_000,
                        on_group=lambda: int(collection.get("requested_at", 0) or 0) <= version
                        or time.monotonic() - started_at < 30,
                    )
                    if result == "interrupted":
                        continue
                    _collection_control(config, "finished", version=version)
                    completed = max(completed, version)
                    next_scan = time.monotonic() + max(60, interval)
                except requests.RequestException:
                    next_scan = time.monotonic() + 30
                except RuntimeError as exc:
                    message = str(exc)
                    try:
                        _collection_control(config, "failed", version=version)
                    except requests.RequestException:
                        pass
                    if message.startswith(("Sessione Instagram scaduta", "Profilo attivo @")):
                        try:
                            _auth_control(config, "required", message=message)
                        except requests.RequestException:
                            pass
                        print("Sessione Instagram scaduta: premi 'Rigenera accesso Instagram' in Orbit.", flush=True)
                        next_scan = time.monotonic() + 60
                    else:
                        next_scan = time.monotonic() + 30
                except Exception:
                    try:
                        _collection_control(config, "failed", version=version)
                    except requests.RequestException:
                        pass
                    next_scan = time.monotonic() + 30
        finally:
            stop.set()


def worker(config_path: Path) -> None:
    install_compatibility_overrides()
    while True:
        try:
            manual.run_worker(config_path)
        except Exception:
            # Keep the task alive while the collector waits for a dashboard re-auth.
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Orbit Directs: Generali + rinnovo sessione")
    parser.add_argument("command", choices=["watch", "worker"])
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / ".env.agent")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.command == "worker":
        worker(args.config.resolve())
    else:
        watch(args.config.resolve(), max(60, args.interval))


if __name__ == "__main__":
    main()
 -and $_.CommandLine "
        "-like '*orbit_parallel_bridge.py* worker *'} | "
        "ForEach-Object {Invoke-CimMethod -InputObject $_ -MethodName Terminate "
        "-ErrorAction SilentlyContinue | Out-Null}"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def watch(config_path: Path, interval: int) -> None:
    install_compatibility_overrides()
    with manual.collector_lock(config_path):
        config = load_config(config_path)
        collection = {"requested_at": 0, "completed_request_at": 0}
        auth = {"requested_at": 0, "completed_request_at": 0}
        stop = threading.Event()

        def heartbeat():
            while not stop.is_set():
                try:
                    collection.update(_collection_control(config, "poll"))
                except requests.RequestException:
                    pass
                try:
                    auth.update(_auth_control(config, "poll"))
                except requests.RequestException:
                    pass
                stop.wait(3)

        threading.Thread(target=heartbeat, daemon=True).start()
        completed = attempted = auth_attempted = 0
        next_scan = 0.0
        try:
            while True:
                requested_auth = int(auth.get("requested_at", 0) or 0)
                completed_auth = int(auth.get("completed_request_at", 0) or 0)
                if requested_auth > max(completed_auth, auth_attempted):
                    auth_attempted = requested_auth
                    version = requested_auth
                    try:
                        started = _auth_control(config, "started")
                        version = int(started.get("started_request_at", version) or version)
                        print("Rinnovo richiesto da Orbit: apro Edge per Instagram.", flush=True)
                        login_with_browser(required(config, "ORBIT_INSTAGRAM_USERNAME"), config_path)
                        _auth_control(config, "finished", version=version)
                        auth["completed_request_at"] = version
                        _restart_manual_worker()
                        next_scan = 0
                        print("Sessione Instagram rinnovata; Generali di nuovo attivo.", flush=True)
                    except Exception as exc:
                        message = re.sub(r"\s+", " ", str(exc)).strip()[:300] or type(exc).__name__
                        try:
                            _auth_control(config, "failed", version=version, message=message)
                        except requests.RequestException:
                            pass
                    continue

                if time.monotonic() < next_scan and int(collection.get("requested_at", 0) or 0) <= max(completed, attempted):
                    time.sleep(1)
                    continue

                version = 0
                try:
                    scan = _collection_control(config, "started")
                    version = int(scan.get("started_request_at", 0) or 0)
                    attempted = max(attempted, version)
                    started_at = time.monotonic()
                    # A huge bound removes the old 1/40-history-page limit; collect()
                    # still stops naturally when the chat cannot scroll any farther.
                    result = manual.collect(
                        config_path,
                        publish_approved=True,
                        history_pages=1_000_000,
                        on_group=lambda: int(collection.get("requested_at", 0) or 0) <= version
                        or time.monotonic() - started_at < 30,
                    )
                    if result == "interrupted":
                        continue
                    _collection_control(config, "finished", version=version)
                    completed = max(completed, version)
                    next_scan = time.monotonic() + max(60, interval)
                except requests.RequestException:
                    next_scan = time.monotonic() + 30
                except RuntimeError as exc:
                    message = str(exc)
                    try:
                        _collection_control(config, "failed", version=version)
                    except requests.RequestException:
                        pass
                    if message.startswith(("Sessione Instagram scaduta", "Profilo attivo @")):
                        try:
                            _auth_control(config, "required", message=message)
                        except requests.RequestException:
                            pass
                        print("Sessione Instagram scaduta: premi 'Rigenera accesso Instagram' in Orbit.", flush=True)
                        next_scan = time.monotonic() + 60
                    else:
                        next_scan = time.monotonic() + 30
                except Exception:
                    try:
                        _collection_control(config, "failed", version=version)
                    except requests.RequestException:
                        pass
                    next_scan = time.monotonic() + 30
        finally:
            stop.set()


def worker(config_path: Path) -> None:
    install_compatibility_overrides()
    while True:
        try:
            manual.run_worker(config_path)
        except Exception:
            # Keep the task alive while the collector waits for a dashboard re-auth.
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Orbit Directs: Generali + rinnovo sessione")
    parser.add_argument("command", choices=["watch", "worker"])
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / ".env.agent")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.command == "worker":
        worker(args.config.resolve())
    else:
        watch(args.config.resolve(), max(60, args.interval))


if __name__ == "__main__":
    main()
