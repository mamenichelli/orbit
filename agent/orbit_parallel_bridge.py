"""Run Orbit's local Instagram collector against legacy Orbit and the agent relay.

The existing ChatGPT Site remains primary. Orbit Agent Relay is the secondary
machine endpoint used by Orbit Parallel without changing the Instagram session or agent token.
"""
from __future__ import annotations

import argparse
from pathlib import Path

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
_RELAY_BOOTSTRAPPED_NOW = False


def dashboard_urls(config: dict[str, str]) -> list[str]:
    primary = required(config, "ORBIT_DASHBOARD_URL").rstrip("/")
    secondary = config.get("ORBIT_SECONDARY_DASHBOARD_URL", "").strip().rstrip("/") or DEFAULT_SECONDARY_DASHBOARD
    # Old configs may still contain AppDeploy endpoints that reject machine clients.
    # Force those stale values onto the Render relay.
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
    global _RELAY_BOOTSTRAPPED_NOW
    if not base_url.endswith(".onrender.com"):
        return
    response = requests.post(
        base_url.rstrip("/") + "/bootstrap",
        json={
            "bootstrapSecret": required(config, "ORBIT_RENDER_BOOTSTRAP_SECRET"),
            "agentToken": required(config, "ORBIT_AGENT_TOKEN"),
            "accountUsername": required(config, "ORBIT_INSTAGRAM_USERNAME"),
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("ok") is not True:
        raise RuntimeError("Bootstrap relay non confermato")
    _RELAY_BOOTSTRAPPED_NOW = True


def _post_one(config: dict[str, str], base_url: str, path: str, payload: dict) -> dict:
    body = dict(payload)
    if not base_url.endswith(".chatgpt.site"):
        body["agentToken"] = required(config, "ORBIT_AGENT_TOKEN")
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
        if base_url.endswith(".onrender.com") and _RELAY_BOOTSTRAPPED_NOW:
            pending = list(events)
        else:
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

    global _RELAY_BOOTSTRAPPED_NOW
    if all_ok:
        _RELAY_BOOTSTRAPPED_NOW = False
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


def self_test(config: dict[str, str]) -> None:
    username = required(config, "ORBIT_INSTAGRAM_USERNAME")
    failures = 0
    print("Test collegamento Orbit legacy + Orbit Agent Relay Render", flush=True)
    for base_url in dashboard_urls(config):
        try:
            if base_url.endswith(".onrender.com"):
                _bootstrap_relay(config, base_url)
            collection = _post_one(config, base_url, "/api/agent/instagram-collection", {
                "action": "poll",
                "accountUsername": username,
            })
            if not isinstance(collection, dict):
                raise RuntimeError("Risposta raccolta Orbit non valida")
            if not base_url.endswith(".chatgpt.site"):
                auth = _post_one(config, base_url, "/api/agent/instagram-browser-auth", {
                    "action": "poll",
                    "accountUsername": username,
                })
                if not isinstance(auth, dict):
                    raise RuntimeError("Risposta rinnovo Orbit non valida")
            print(f"OK   {base_url}", flush=True)
        except Exception as exc:
            failures += 1
            detail = str(exc).replace("\n", " ").strip()
            print(f"ERRORE {base_url}: {type(exc).__name__}: {detail}", flush=True)
    if failures:
        raise RuntimeError(f"Test fallito su {failures} endpoint")
    print("TEST COMPLETATO: legacy e relay raggiungibili e autorizzati.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Orbit legacy + agent relay bridge")
    parser.add_argument("command", choices=["watch", "worker", "test"])
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / ".env.agent")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = load_config(config_path)
    print("Orbit endpoint: " + " + ".join(dashboard_urls(config)), flush=True)
    if args.command == "test":
        self_test(config)
        return
    install_bridge()
    if args.command == "worker":
        directs.worker(config_path)
    else:
        directs.watch(config_path, max(60, args.interval))


if __name__ == "__main__":
    main()
