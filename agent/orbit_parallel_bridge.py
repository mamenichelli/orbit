"""Orbit local bridge: legacy Orbit + Render relay for Orbit Parallel."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import threading
import time

import requests

import orbit_browser_actions as actions
import orbit_instagram_directs as directs
import orbit_manual_instagram as manual
from orbit_instagram_agent import gateway_headers, load_config, required

DEFAULT_SECONDARY_DASHBOARD = "https://orbit-agent-relay.onrender.com"
OLD_SECONDARY_DASHBOARDS = {
    "https://orbit-parallel-thwhpj.v2.appdeploy.ai",
    "https://orbit-agent-relay-tekjx2.v2.appdeploy.ai",
}
_JOB_ORIGINS: dict[str, str] = {}
_CONTROL_ORIGINS: dict[str, list[tuple[str, int]]] = {}


def dashboard_urls(config: dict[str, str]) -> list[str]:
    primary = required(config, "ORBIT_DASHBOARD_URL").rstrip("/")
    secondary = (
        config.get("ORBIT_SECONDARY_DASHBOARD_URL", "").strip().rstrip("/")
        or DEFAULT_SECONDARY_DASHBOARD
    )
    if secondary in OLD_SECONDARY_DASHBOARDS:
        secondary = DEFAULT_SECONDARY_DASHBOARD
    result: list[str] = []
    for value in (primary, secondary):
        if value and value not in result:
            result.append(value)
    return result


def _headers(config: dict[str, str], base_url: str) -> dict[str, str]:
    if base_url.endswith(".chatgpt.site"):
        return dict(gateway_headers(config))
    return {}


def _bootstrap_relay(config: dict[str, str], base_url: str) -> None:
    if not base_url.endswith(".onrender.com"):
        return
    bootstrap_secret = config.get("ORBIT_RENDER_BOOTSTRAP_SECRET", "").strip()
    if not bootstrap_secret:
        raise RuntimeError("ORBIT_RENDER_BOOTSTRAP_SECRET assente nella configurazione locale")
    response = requests.post(
        base_url.rstrip("/") + "/bootstrap",
        json={
            "bootstrapSecret": bootstrap_secret,
            "agentToken": required(config, "ORBIT_AGENT_TOKEN"),
            "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("ok") is not True:
        raise RuntimeError("Bootstrap relay non confermato")


def _post_one(
    config: dict[str, str],
    base_url: str,
    path: str,
    payload: dict,
    *,
    heartbeat: bool = True,
) -> dict:
    body = dict(payload)
    if not base_url.endswith(".chatgpt.site"):
        body["agentToken"] = required(config, "ORBIT_AGENT_TOKEN")
        if heartbeat:
            body["agentHeartbeat"] = True
    url = base_url.rstrip("/") + path
    response = requests.post(
        url,
        headers=_headers(config, base_url),
        json=body,
        timeout=60,
    )
    if response.status_code == 401 and base_url.endswith(".onrender.com"):
        _bootstrap_relay(config, base_url)
        response = requests.post(
            url,
            headers=_headers(config, base_url),
            json=body,
            timeout=60,
        )
    response.raise_for_status()
    return response.json()


def _merge_idle_states(responses: list[dict]) -> dict:
    if not responses:
        return {}
    merged = dict(max(responses, key=lambda item: int(item.get("last_seen", 0) or 0)))
    for key in ("requested_at", "started_request_at", "completed_request_at", "last_seen"):
        merged[key] = max(int(item.get(key, 0) or 0) for item in responses)
    errors = [str(item.get("error") or "") for item in responses if item.get("error")]
    merged["error"] = errors[0] if errors else ""
    return merged


def _poll_controls(config: dict[str, str], path: str) -> list[tuple[str, dict]]:
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    results: list[tuple[str, dict]] = []
    errors: list[Exception] = []
    for base_url in dashboard_urls(config):
        try:
            results.append(
                (
                    base_url,
                    _post_one(
                        config,
                        base_url,
                        path,
                        {"action": "poll", "accountUsername": username},
                    ),
                )
            )
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            errors.append(exc)
    if not results and errors:
        raise errors[0]
    return results


def _control_pending(item: dict) -> bool:
    return int(item.get("requested_at", 0) or 0) > int(
        item.get("completed_request_at", 0) or 0
    )


def _control_post(config: dict[str, str], path: str, payload: dict) -> dict:
    action = str(payload.get("action") or "")
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")

    if action == "poll":
        polled = _poll_controls(config, path)
        pending = [(url, item) for url, item in polled if _control_pending(item)]
        if pending:
            return dict(
                max(pending, key=lambda pair: int(pair[1].get("requested_at", 0) or 0))[1]
            )
        return _merge_idle_states([item for _, item in polled])

    if action == "started":
        polled = _poll_controls(config, path)
        pending = [(url, item) for url, item in polled if _control_pending(item)]
        selected = pending if pending else polled
        origins: list[tuple[str, int]] = []
        replies: list[dict] = []
        for base_url, item in selected:
            requested = int(item.get("requested_at", 0) or 0)
            reply = _post_one(
                config,
                base_url,
                path,
                {"action": "started", "accountUsername": username},
            )
            version = int(reply.get("started_request_at", requested) or requested)
            origins.append((base_url, version))
            replies.append(reply)
        _CONTROL_ORIGINS[path] = origins
        if not replies:
            return {}
        chosen_index = max(range(len(origins)), key=lambda i: origins[i][1])
        result = dict(replies[chosen_index])
        result["started_request_at"] = origins[chosen_index][1]
        return result

    if action in {"finished", "failed"}:
        origins = _CONTROL_ORIGINS.pop(path, [])
        if not origins:
            version = int(payload.get("version", 0) or 0)
            origins = [(url, version) for url in dashboard_urls(config)]
        replies: list[dict] = []
        first_error: Exception | None = None
        for base_url, version in origins:
            body = dict(payload)
            body["accountUsername"] = username
            body["version"] = version
            try:
                replies.append(_post_one(config, base_url, path, body))
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                if first_error is None:
                    first_error = exc
        if not replies and first_error:
            raise first_error
        return _merge_idle_states(replies)

    if action == "required":
        replies: list[dict] = []
        first_error: Exception | None = None
        for base_url in dashboard_urls(config):
            body = dict(payload)
            body["accountUsername"] = username
            try:
                replies.append(_post_one(config, base_url, path, body))
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                if first_error is None:
                    first_error = exc
        if not replies and first_error:
            raise first_error
        return _merge_idle_states(replies)

    return _post_one(config, dashboard_urls(config)[0], path, payload)


def dual_gateway_post(config: dict[str, str], path: str, payload: dict) -> dict:
    urls = dashboard_urls(config)

    if path == "/api/agent/instagram-manual":
        action = str(payload.get("action") or "")
        if action == "claim":
            fallback: dict = {"job": None}
            last_error: Exception | None = None
            for base_url in urls:
                try:
                    result = _post_one(config, base_url, path, payload)
                    fallback = result
                    job = result.get("job")
                    if isinstance(job, dict) and isinstance(job.get("id"), str):
                        _JOB_ORIGINS[job["id"]] = base_url
                        return result
                except (requests.RequestException, ValueError, RuntimeError) as exc:
                    last_error = exc
            if last_error and fallback == {"job": None}:
                raise last_error
            return fallback

        if action == "complete":
            job_id = str(payload.get("id") or "")
            origin = _JOB_ORIGINS.pop(job_id, "")
            if origin:
                return _post_one(config, origin, path, payload)
            last: dict = {}
            last_error: Exception | None = None
            for base_url in urls:
                try:
                    last = _post_one(config, base_url, path, payload)
                except (requests.RequestException, ValueError, RuntimeError) as exc:
                    last_error = exc
            if last_error and not last:
                raise last_error
            return last

    if path in {
        "/api/agent/instagram-collection",
        "/api/agent/instagram-browser-auth",
    }:
        return _control_post(config, path, payload)

    return _post_one(config, urls[0], path, payload)


def dual_sync_like_events(config_path: Path, config: dict, state: dict) -> bool:
    urls = dashboard_urls(config)
    events = list(state.get("likeEvents", {}).values())
    all_ok = True

    for base_url in urls:
        pending = [
            event
            for event in events
            if base_url not in event.get("syncedDashboards", [])
        ]
        for offset in range(0, len(pending), 40):
            batch = pending[offset : offset + 40]
            payload = [
                {
                    key: event[key]
                    for key in (
                        "eventId",
                        "shortcode",
                        "status",
                        "likedAt",
                        "observedAt",
                        "groups",
                    )
                }
                for event in batch
            ]
            for entry, event in zip(payload, batch):
                if event.get("metadata"):
                    entry["metadata"] = event["metadata"]
            try:
                response = _post_one(
                    config,
                    base_url,
                    "/api/agent/instagram-likes",
                    {
                        "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
                        "events": payload,
                    },
                )
                if response.get("ok") is not True or response.get("accepted") != len(batch):
                    raise RuntimeError("Conferma registro assente")
                for event in batch:
                    synced = event.setdefault("syncedDashboards", [])
                    if base_url not in synced:
                        synced.append(base_url)
                actions.save_state(config_path, state)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                print(
                    f"Mirror {base_url} rinviato ({type(exc).__name__}); "
                    "registro conservato sul PC.",
                    flush=True,
                )
                all_ok = False
                break

    for event in events:
        synced = set(event.get("syncedDashboards", []))
        event["pending"] = any(base_url not in synced for base_url in urls)
    actions.save_state(config_path, state)
    return all_ok


def install_bridge() -> None:
    actions.gateway_post = dual_gateway_post
    actions.sync_like_events = dual_sync_like_events
    manual.gateway_post = dual_gateway_post
    manual.sync_like_events = dual_sync_like_events
    directs.gateway_post = dual_gateway_post


def _local_heartbeat(config: dict[str, str], stop: threading.Event) -> None:
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    render_urls = [url for url in dashboard_urls(config) if url.endswith(".onrender.com")]
    while not stop.is_set():
        for base_url in render_urls:
            for path in (
                "/api/agent/instagram-collection",
                "/api/agent/instagram-browser-auth",
            ):
                try:
                    _post_one(
                        config,
                        base_url,
                        path,
                        {"action": "poll", "accountUsername": username},
                    )
                except Exception:
                    logging.exception("Heartbeat Render fallito")
        stop.wait(5)


def self_test(config: dict[str, str]) -> None:
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    failures = 0
    print("Test collegamento Orbit legacy + Orbit Agent Relay Render", flush=True)
    for base_url in dashboard_urls(config):
        try:
            if base_url.endswith(".onrender.com"):
                _bootstrap_relay(config, base_url)
            collection = _post_one(
                config,
                base_url,
                "/api/agent/instagram-collection",
                {"action": "poll", "accountUsername": username},
            )
            if not isinstance(collection, dict):
                raise RuntimeError("Risposta raccolta Orbit non valida")
            if not base_url.endswith(".chatgpt.site"):
                auth = _post_one(
                    config,
                    base_url,
                    "/api/agent/instagram-browser-auth",
                    {"action": "poll", "accountUsername": username},
                )
                if not isinstance(auth, dict):
                    raise RuntimeError("Risposta rinnovo Orbit non valida")
            print(f"OK   {base_url}", flush=True)
        except Exception as exc:
            failures += 1
            detail = str(exc).replace("\n", " ").strip()
            print(
                f"ERRORE {base_url}: {type(exc).__name__}: {detail}",
                flush=True,
            )
    if failures:
        raise RuntimeError(f"Test fallito su {failures} endpoint")
    print(
        "TEST COMPLETATO: legacy e relay raggiungibili e autorizzati.",
        flush=True,
    )


def _run_forever(config_path: Path, command: str, interval: int) -> None:
    config = load_config(config_path)
    install_bridge()
    stop = threading.Event()
    threading.Thread(
        target=_local_heartbeat,
        args=(config, stop),
        daemon=True,
        name="orbit-render-heartbeat",
    ).start()
    try:
        while True:
            try:
                if command == "worker":
                    directs.worker(config_path)
                else:
                    directs.watch(config_path, max(60, interval))
            except KeyboardInterrupt:
                raise
            except Exception:
                logging.exception("Processo Orbit %s interrotto; riavvio tra 10 secondi", command)
                time.sleep(10)
    finally:
        stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Orbit legacy + Render relay bridge")
    parser.add_argument("command", choices=["watch", "worker", "test", "collect"])
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / ".env.agent",
    )
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--history-pages", type=int, default=20)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = load_config(config_path)
    print("Orbit endpoint: " + " + ".join(dashboard_urls(config)), flush=True)
    if args.command == "test":
        self_test(config)
        return
    if args.command == "collect":
        install_bridge()
        manual.collect(
            config_path,
            publish_approved=True,
            history_pages=max(1, min(200, args.history_pages)),
        )
        return
    _run_forever(config_path, args.command, args.interval)


if __name__ == "__main__":
    main()
