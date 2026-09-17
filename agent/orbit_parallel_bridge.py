"""Run Orbit's local Instagram collector against both Orbit dashboards.

The existing ChatGPT Site remains primary. Orbit Parallel on AppDeploy is mirrored
as a secondary endpoint without changing the Instagram session or agent token.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time

import requests

import orbit_browser_actions as actions
import orbit_instagram_directs as directs
import orbit_manual_instagram as manual
from orbit_instagram_agent import gateway_headers, load_config, required

DEFAULT_SECONDARY_DASHBOARD = "https://orbit-parallel-thwhpj.v2.appdeploy.ai"
_JOB_ORIGINS: dict[str, str] = {}


def dashboard_urls(config: dict[str, str]) -> list[str]:
    primary = required(config, "ORBIT_DASHBOARD_URL").rstrip("/")
    secondary = config.get("ORBIT_SECONDARY_DASHBOARD_URL", "").strip().rstrip("/") or DEFAULT_SECONDARY_DASHBOARD
    result: list[str] = []
    for value in (primary, secondary):
        if value and value not in result:
            result.append(value)
    return result


def _headers(config: dict[str, str], base_url: str) -> dict[str, str]:
    headers = dict(gateway_headers(config))
    if not base_url.endswith(".chatgpt.site"):
        headers.pop("OAI-Sites-Authorization", None)
    return headers


def _post_one(config: dict[str, str], base_url: str, path: str, payload: dict) -> dict:
    response = requests.post(
        base_url.rstrip("/") + path,
        headers=_headers(config, base_url),
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _merge_control_states(responses: list[dict]) -> dict:
    if not responses:
        return {}
    merged = dict(responses[0])
    for key in ("requested_at", "started_request_at", "completed_request_at", "last_seen"):
        values = [int(item.get(key, 0) or 0) for item in responses]
        merged[key] = max(values, default=0)
    errors = [str(item.get("error") or "") for item in responses if item.get("error")]
    merged["error"] = errors[0] if errors else ""
    return merged


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
                except (requests.RequestException, ValueError) as exc:
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
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
            if last_error and not last:
                raise last_error
            return last

    if path in {"/api/agent/instagram-collection", "/api/agent/instagram-browser-auth"}:
        responses: list[dict] = []
        errors: list[Exception] = []
        for base_url in urls:
            try:
                responses.append(_post_one(config, base_url, path, payload))
            except (requests.RequestException, ValueError) as exc:
                errors.append(exc)
        if not responses and errors:
            raise errors[0]
        return _merge_control_states(responses)

    return _post_one(config, urls[0], path, payload)


def dual_sync_like_events(config_path: Path, config: dict, state: dict) -> bool:
    urls = dashboard_urls(config)
    events = list(state.get("likeEvents", {}).values())
    all_ok = True

    for base_url in urls:
        pending = [event for event in events if base_url not in event.get("syncedDashboards", [])]
        for offset in range(0, len(pending), 40):
            batch = pending[offset:offset + 40]
            payload = [{key: event[key] for key in
                        ("eventId", "shortcode", "status", "likedAt", "observedAt", "groups")}
                       for event in batch]
            for entry, event in zip(payload, batch):
                if event.get("metadata"):
                    entry["metadata"] = event["metadata"]
            try:
                response = _post_one(config, base_url, "/api/agent/instagram-likes", {
                    "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
                    "events": payload,
                })
                if response.get("ok") is not True or response.get("accepted") != len(batch):
                    raise RuntimeError("Conferma registro assente")
                for event in batch:
                    synced = event.setdefault("syncedDashboards", [])
                    if base_url not in synced:
                        synced.append(base_url)
                actions.save_state(config_path, state)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                print(f"Mirror {base_url} rinviato ({type(exc).__name__}); registro conservato sul PC.", flush=True)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Orbit dual dashboard bridge")
    parser.add_argument("command", choices=["watch", "worker"])
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / ".env.agent")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = load_config(config_path)
    print("Orbit dashboard: " + " + ".join(dashboard_urls(config)), flush=True)
    install_bridge()
    if args.command == "worker":
        directs.worker(config_path)
    else:
        directs.watch(config_path, max(60, args.interval))


if __name__ == "__main__":
    main()
