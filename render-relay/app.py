from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

app = FastAPI(title='Orbit Agent Relay', version='1.2.0')

ENV_AGENT_TOKEN = os.environ.get('ORBIT_AGENT_TOKEN', '')
BOOTSTRAP_SECRET = os.environ.get('ORBIT_RENDER_BOOTSTRAP_SECRET', '')
ACCOUNT = os.environ.get('ORBIT_INSTAGRAM_USERNAME', 'ma.menichelli')
DB_PATH = Path(os.environ.get('ORBIT_RELAY_DB', '/tmp/orbit-relay.db'))
LOCK = threading.RLock()
USERNAME_RE = re.compile(r'[A-Za-z0-9._]{1,30}')

def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orbit_config (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orbit_state (
              name TEXT PRIMARY KEY,
              requested_at INTEGER NOT NULL DEFAULT 0,
              started_request_at INTEGER NOT NULL DEFAULT 0,
              completed_request_at INTEGER NOT NULL DEFAULT 0,
              last_seen INTEGER NOT NULL DEFAULT 0,
              error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS orbit_likes (
              shortcode TEXT PRIMARY KEY,
              account_username TEXT NOT NULL,
              event_id TEXT NOT NULL,
              status TEXT NOT NULL,
              liked_at TEXT,
              observed_at TEXT NOT NULL,
              groups_json TEXT NOT NULL DEFAULT '[]',
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS orbit_manual_jobs (
              job_id TEXT PRIMARY KEY,
              shortcode TEXT NOT NULL,
              status TEXT NOT NULL,
              requested_at INTEGER NOT NULL,
              message TEXT NOT NULL DEFAULT '',
              finished_at INTEGER
            );
            """
        )
        conn.commit()


@app.on_event('startup')
def startup() -> None:
    init_db()


def config_get(key: str, default: str = '') -> str:
    with LOCK, db() as conn:
        row = conn.execute('SELECT value FROM orbit_config WHERE key=?', (key,)).fetchone()
    return str(row['value']) if row else default


def config_set(key: str, value: str) -> None:
    with LOCK, db() as conn:
        conn.execute(
            """
            INSERT INTO orbit_config(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        conn.commit()


def active_username() -> str:
    return config_get('active_username', ACCOUNT) or ACCOUNT


def stored_token_hash() -> str:
    if ENV_AGENT_TOKEN:
        return digest(ENV_AGENT_TOKEN)
    with LOCK, db() as conn:
        row = conn.execute(
            "SELECT value FROM orbit_config WHERE key='agent_token_sha256'"
        ).fetchone()
    return str(row['value']) if row else ''


def authorized(body: dict[str, Any]) -> None:
    actual = str(body.get('agentToken') or '')
    expected_hash = stored_token_hash()
    if not actual or not expected_hash:
        raise HTTPException(status_code=401, detail='Relay non inizializzato')
    if not hmac.compare_digest(digest(actual), expected_hash):
        raise HTTPException(status_code=401, detail='Non autorizzato')


def state(name: str) -> dict[str, Any]:
    with LOCK, db() as conn:
        conn.execute('INSERT OR IGNORE INTO orbit_state(name) VALUES (?)', (name,))
        row = conn.execute(
            'SELECT requested_at, started_request_at, completed_request_at, last_seen, error FROM orbit_state WHERE name=?',
            (name,),
        ).fetchone()
        conn.commit()
    return {
        'requested_at': int(row['requested_at'] or 0),
        'started_request_at': int(row['started_request_at'] or 0),
        'completed_request_at': int(row['completed_request_at'] or 0),
        'last_seen': int(row['last_seen'] or 0),
        'error': row['error'] or '',
        'requested_username': config_get('requested_username', ''),
        'active_username': active_username(),
    }


def control(name: str, body: dict[str, Any]) -> dict[str, Any]:
    action = str(body.get('action') or 'poll')
    if action not in {'poll', 'request', 'started', 'finished', 'failed', 'required'}:
        raise HTTPException(status_code=400, detail='Azione non valida')

    current = state(name)
    now = int(time.time() * 1000)
    if body.get('agentHeartbeat') is True:
        current['last_seen'] = now

    if action == 'request':
        requested_username = str(body.get('username') or body.get('accountUsername') or active_username()).strip().lstrip('@').lower()
        if not USERNAME_RE.fullmatch(requested_username):
            raise HTTPException(status_code=400, detail='Username Instagram non valido')
        config_set('requested_username', requested_username)
        current['requested_username'] = requested_username
        current['requested_at'] = now
        current['error'] = ''
    elif action == 'started':
        current['started_request_at'] = current['requested_at']
        current['error'] = ''
    elif action == 'finished':
        current['completed_request_at'] = max(
            current['completed_request_at'], int(body.get('version') or 0)
        )
        verified_username = str(body.get('accountUsername') or current.get('requested_username') or active_username()).strip().lstrip('@').lower()
        if USERNAME_RE.fullmatch(verified_username):
            config_set('active_username', verified_username)
            config_set('requested_username', '')
            current['active_username'] = verified_username
            current['requested_username'] = ''
        current['error'] = ''
    elif action == 'failed':
        current['completed_request_at'] = max(
            current['completed_request_at'], int(body.get('version') or 0)
        )
        current['error'] = str(body.get('message') or 'Operazione non completata')[:300]
    elif action == 'required':
        current['error'] = str(body.get('message') or 'Sessione Instagram scaduta')[:300]

    with LOCK, db() as conn:
        conn.execute(
            """
            UPDATE orbit_state
            SET requested_at=?, started_request_at=?, completed_request_at=?, last_seen=?, error=?
            WHERE name=?
            """,
            (
                current['requested_at'],
                current['started_request_at'],
                current['completed_request_at'],
                current['last_seen'],
                current['error'],
                name,
            ),
        )
        conn.commit()
    return current


@app.get('/health')
def health() -> dict[str, Any]:
    init_db()
    return {
        'ok': True,
        'tokenConfigured': bool(stored_token_hash()),
        'bootstrapConfigured': bool(BOOTSTRAP_SECRET),
        'accountUsername': active_username(),
        'storage': 'sqlite',
    }


@app.post('/bootstrap')
def bootstrap(body: dict[str, Any]) -> dict[str, Any]:
    supplied_bootstrap = str(body.get('bootstrapSecret') or '')
    agent_token = str(body.get('agentToken') or '')
    account = str(body.get('accountUsername') or '')

    if not BOOTSTRAP_SECRET or not supplied_bootstrap:
        raise HTTPException(status_code=401, detail='Bootstrap non disponibile')
    if not hmac.compare_digest(supplied_bootstrap, BOOTSTRAP_SECRET):
        raise HTTPException(status_code=401, detail='Bootstrap non autorizzato')
    if not USERNAME_RE.fullmatch(account) or len(agent_token) < 16:
        raise HTTPException(status_code=400, detail='Configurazione agente non valida')

    candidate = digest(agent_token)
    with LOCK, db() as conn:
        existing = conn.execute(
            "SELECT value FROM orbit_config WHERE key='agent_token_sha256'"
        ).fetchone()
        if existing and not hmac.compare_digest(str(existing['value']), candidate):
            raise HTTPException(status_code=409, detail='Relay già associato a un altro token')
        conn.execute(
            """
            INSERT INTO orbit_config(key, value) VALUES ('agent_token_sha256', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (candidate,),
        )
        conn.commit()
    if not config_get('active_username'):
        config_set('active_username', account.lower())
    return {'ok': True, 'tokenConfigured': True, 'accountUsername': active_username()}


@app.post('/api/agent/instagram-browser-auth')
def browser_auth(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    return control('browser_auth', body)


@app.post('/api/agent/instagram-collection')
def collection(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    return control('collection', body)


@app.post('/api/agent/instagram-likes')
def likes(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    action = str(body.get('action') or 'push')

    if action == 'list':
        with LOCK, db() as conn:
            rows = conn.execute(
                """
                SELECT shortcode, event_id, status, liked_at, observed_at, groups_json, metadata_json
                FROM orbit_likes
                WHERE status NOT IN ('applied','already_liked','skipped')
                ORDER BY observed_at DESC
                LIMIT 100
                """
            ).fetchall()
        manual_state = state('manual')
        return {
            'accountUsername': active_username(),
            'manualOnline': int(time.time() * 1000) - manual_state['last_seen'] < 120000,
            'events': [
                {
                    'id': row['shortcode'],
                    'shortcode': row['shortcode'],
                    'eventId': row['event_id'],
                    'status': row['status'],
                    'likedAt': row['liked_at'],
                    'observedAt': row['observed_at'],
                    'groups': json.loads(row['groups_json'] or '[]'),
                    'metadata': json.loads(row['metadata_json'] or '{}'),
                }
                for row in rows
            ],
        }

    if action == 'skip':
        shortcode = str(body.get('shortcode') or '')
        with LOCK, db() as conn:
            conn.execute(
                'UPDATE orbit_likes SET status=? WHERE shortcode=?',
                ('skipped', shortcode),
            )
            conn.commit()
        return {'ok': True}

    events = body.get('events') if isinstance(body.get('events'), list) else []
    if len(events) > 100:
        raise HTTPException(status_code=400, detail='Troppi eventi')

    with LOCK, db() as conn:
        for event in events:
            shortcode = str(event.get('shortcode') or '')
            if not shortcode:
                continue
            conn.execute(
                """
                INSERT INTO orbit_likes
                  (shortcode, account_username, event_id, status, liked_at, observed_at, groups_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shortcode) DO UPDATE SET
                  event_id=excluded.event_id,
                  status=excluded.status,
                  liked_at=excluded.liked_at,
                  observed_at=excluded.observed_at,
                  groups_json=excluded.groups_json,
                  metadata_json=excluded.metadata_json
                """,
                (
                    shortcode,
                    str(body.get('accountUsername') or active_username()),
                    str(event.get('eventId') or ''),
                    str(event.get('status') or 'discovered'),
                    event.get('likedAt'),
                    str(event.get('observedAt') or ''),
                    json.dumps(event.get('groups') or [], separators=(',', ':')),
                    json.dumps(event.get('metadata') or {}, separators=(',', ':')),
                ),
            )
        conn.commit()
    return {'ok': True, 'accepted': len(events)}


@app.post('/api/agent/instagram-manual')
def manual(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    control('manual', {'action': 'poll', 'agentHeartbeat': True})
    action = str(body.get('action') or 'claim')

    if action == 'queue':
        job_id = str(body.get('id') or '')
        shortcode = str(body.get('shortcode') or '')
        if not job_id or not shortcode:
            raise HTTPException(status_code=400, detail='Richiesta non valida')
        with LOCK, db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO orbit_manual_jobs(job_id, shortcode, status, requested_at)
                VALUES (?, ?, 'queued', ?)
                """,
                (job_id, shortcode, int(time.time() * 1000)),
            )
            conn.commit()
        return {'ok': True}

    if action == 'status':
        job_id = str(body.get('id') or '')
        with LOCK, db() as conn:
            row = conn.execute(
                'SELECT status, message FROM orbit_manual_jobs WHERE job_id=?',
                (job_id,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Richiesta non trovata')
        return {'status': row['status'], 'message': row['message'] or ''}

    if action == 'claim':
        cutoff = int(time.time() * 1000) - 120000
        with LOCK, db() as conn:
            row = conn.execute(
                """
                SELECT job_id, shortcode, requested_at
                FROM orbit_manual_jobs
                WHERE status='queued' AND requested_at >= ?
                ORDER BY requested_at
                LIMIT 1
                """,
                (cutoff,),
            ).fetchone()
            if not row:
                return {'job': None}
            conn.execute(
                "UPDATE orbit_manual_jobs SET status='executing' WHERE job_id=? AND status='queued'",
                (row['job_id'],),
            )
            conn.commit()
        return {
            'job': {
                'id': row['job_id'],
                'shortcode': row['shortcode'],
                'requested_at': row['requested_at'],
            }
        }

    if action == 'complete':
        job_id = str(body.get('id') or '')
        status = str(body.get('status') or 'failed')
        message = str(body.get('message') or '')[:300]
        now = int(time.time() * 1000)
        with LOCK, db() as conn:
            row = conn.execute(
                'SELECT shortcode FROM orbit_manual_jobs WHERE job_id=?',
                (job_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE orbit_manual_jobs
                    SET status=?, message=?, finished_at=?
                    WHERE job_id=?
                    """,
                    (status, message, now, job_id),
                )
                if status in {'applied', 'already_liked'}:
                    conn.execute(
                        'UPDATE orbit_likes SET status=?, liked_at=COALESCE(liked_at, ?) WHERE shortcode=?',
                        (
                            status,
                            time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            row['shortcode'],
                        ),
                    )
            conn.commit()
        return {'ok': True}

    raise HTTPException(status_code=400, detail='Azione non valida')
)


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orbit_config (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orbit_state (
              name TEXT PRIMARY KEY,
              requested_at INTEGER NOT NULL DEFAULT 0,
              started_request_at INTEGER NOT NULL DEFAULT 0,
              completed_request_at INTEGER NOT NULL DEFAULT 0,
              last_seen INTEGER NOT NULL DEFAULT 0,
              error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS orbit_likes (
              shortcode TEXT PRIMARY KEY,
              account_username TEXT NOT NULL,
              event_id TEXT NOT NULL,
              status TEXT NOT NULL,
              liked_at TEXT,
              observed_at TEXT NOT NULL,
              groups_json TEXT NOT NULL DEFAULT '[]',
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS orbit_manual_jobs (
              job_id TEXT PRIMARY KEY,
              shortcode TEXT NOT NULL,
              status TEXT NOT NULL,
              requested_at INTEGER NOT NULL,
              message TEXT NOT NULL DEFAULT '',
              finished_at INTEGER
            );
            """
        )
        conn.commit()


@app.on_event('startup')
def startup() -> None:
    init_db()


def stored_token_hash() -> str:
    if ENV_AGENT_TOKEN:
        return digest(ENV_AGENT_TOKEN)
    with LOCK, db() as conn:
        row = conn.execute(
            "SELECT value FROM orbit_config WHERE key='agent_token_sha256'"
        ).fetchone()
    return str(row['value']) if row else ''


def authorized(body: dict[str, Any]) -> None:
    actual = str(body.get('agentToken') or '')
    expected_hash = stored_token_hash()
    if not actual or not expected_hash:
        raise HTTPException(status_code=401, detail='Relay non inizializzato')
    if not hmac.compare_digest(digest(actual), expected_hash):
        raise HTTPException(status_code=401, detail='Non autorizzato')


def state(name: str) -> dict[str, Any]:
    with LOCK, db() as conn:
        conn.execute('INSERT OR IGNORE INTO orbit_state(name) VALUES (?)', (name,))
        row = conn.execute(
            'SELECT requested_at, started_request_at, completed_request_at, last_seen, error FROM orbit_state WHERE name=?',
            (name,),
        ).fetchone()
        conn.commit()
    return {
        'requested_at': int(row['requested_at'] or 0),
        'started_request_at': int(row['started_request_at'] or 0),
        'completed_request_at': int(row['completed_request_at'] or 0),
        'last_seen': int(row['last_seen'] or 0),
        'error': row['error'] or '',
    }


def control(name: str, body: dict[str, Any]) -> dict[str, Any]:
    action = str(body.get('action') or 'poll')
    if action not in {'poll', 'request', 'started', 'finished', 'failed', 'required'}:
        raise HTTPException(status_code=400, detail='Azione non valida')

    current = state(name)
    now = int(time.time() * 1000)
    if body.get('agentHeartbeat') is True:
        current['last_seen'] = now

    if action == 'request':
        current['requested_at'] = now
        current['error'] = ''
    elif action == 'started':
        current['started_request_at'] = current['requested_at']
        current['error'] = ''
    elif action == 'finished':
        current['completed_request_at'] = max(
            current['completed_request_at'], int(body.get('version') or 0)
        )
        current['error'] = ''
    elif action == 'failed':
        current['completed_request_at'] = max(
            current['completed_request_at'], int(body.get('version') or 0)
        )
        current['error'] = str(body.get('message') or 'Operazione non completata')[:300]
    elif action == 'required':
        current['error'] = str(body.get('message') or 'Sessione Instagram scaduta')[:300]

    with LOCK, db() as conn:
        conn.execute(
            """
            UPDATE orbit_state
            SET requested_at=?, started_request_at=?, completed_request_at=?, last_seen=?, error=?
            WHERE name=?
            """,
            (
                current['requested_at'],
                current['started_request_at'],
                current['completed_request_at'],
                current['last_seen'],
                current['error'],
                name,
            ),
        )
        conn.commit()
    return current


@app.get('/health')
def health() -> dict[str, Any]:
    init_db()
    return {
        'ok': True,
        'tokenConfigured': bool(stored_token_hash()),
        'bootstrapConfigured': bool(BOOTSTRAP_SECRET),
        'accountUsername': ACCOUNT,
        'storage': 'sqlite',
    }


@app.post('/bootstrap')
def bootstrap(body: dict[str, Any]) -> dict[str, Any]:
    supplied_bootstrap = str(body.get('bootstrapSecret') or '')
    agent_token = str(body.get('agentToken') or '')
    account = str(body.get('accountUsername') or '')

    if not BOOTSTRAP_SECRET or not supplied_bootstrap:
        raise HTTPException(status_code=401, detail='Bootstrap non disponibile')
    if not hmac.compare_digest(supplied_bootstrap, BOOTSTRAP_SECRET):
        raise HTTPException(status_code=401, detail='Bootstrap non autorizzato')
    if account != ACCOUNT or len(agent_token) < 16:
        raise HTTPException(status_code=400, detail='Configurazione agente non valida')

    candidate = digest(agent_token)
    with LOCK, db() as conn:
        existing = conn.execute(
            "SELECT value FROM orbit_config WHERE key='agent_token_sha256'"
        ).fetchone()
        if existing and not hmac.compare_digest(str(existing['value']), candidate):
            raise HTTPException(status_code=409, detail='Relay già associato a un altro token')
        conn.execute(
            """
            INSERT INTO orbit_config(key, value) VALUES ('agent_token_sha256', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (candidate,),
        )
        conn.commit()
    return {'ok': True, 'tokenConfigured': True}


@app.post('/api/agent/instagram-browser-auth')
def browser_auth(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    return control('browser_auth', body)


@app.post('/api/agent/instagram-collection')
def collection(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    return control('collection', body)


@app.post('/api/agent/instagram-likes')
def likes(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    action = str(body.get('action') or 'push')

    if action == 'list':
        with LOCK, db() as conn:
            rows = conn.execute(
                """
                SELECT shortcode, event_id, status, liked_at, observed_at, groups_json, metadata_json
                FROM orbit_likes
                WHERE status NOT IN ('applied','already_liked','skipped')
                ORDER BY observed_at DESC
                LIMIT 100
                """
            ).fetchall()
        manual_state = state('manual')
        return {
            'accountUsername': ACCOUNT,
            'manualOnline': int(time.time() * 1000) - manual_state['last_seen'] < 120000,
            'events': [
                {
                    'id': row['shortcode'],
                    'shortcode': row['shortcode'],
                    'eventId': row['event_id'],
                    'status': row['status'],
                    'likedAt': row['liked_at'],
                    'observedAt': row['observed_at'],
                    'groups': json.loads(row['groups_json'] or '[]'),
                    'metadata': json.loads(row['metadata_json'] or '{}'),
                }
                for row in rows
            ],
        }

    if action == 'skip':
        shortcode = str(body.get('shortcode') or '')
        with LOCK, db() as conn:
            conn.execute(
                'UPDATE orbit_likes SET status=? WHERE shortcode=?',
                ('skipped', shortcode),
            )
            conn.commit()
        return {'ok': True}

    events = body.get('events') if isinstance(body.get('events'), list) else []
    if len(events) > 100:
        raise HTTPException(status_code=400, detail='Troppi eventi')

    with LOCK, db() as conn:
        for event in events:
            shortcode = str(event.get('shortcode') or '')
            if not shortcode:
                continue
            conn.execute(
                """
                INSERT INTO orbit_likes
                  (shortcode, account_username, event_id, status, liked_at, observed_at, groups_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shortcode) DO UPDATE SET
                  event_id=excluded.event_id,
                  status=excluded.status,
                  liked_at=excluded.liked_at,
                  observed_at=excluded.observed_at,
                  groups_json=excluded.groups_json,
                  metadata_json=excluded.metadata_json
                """,
                (
                    shortcode,
                    str(body.get('accountUsername') or ACCOUNT),
                    str(event.get('eventId') or ''),
                    str(event.get('status') or 'discovered'),
                    event.get('likedAt'),
                    str(event.get('observedAt') or ''),
                    json.dumps(event.get('groups') or [], separators=(',', ':')),
                    json.dumps(event.get('metadata') or {}, separators=(',', ':')),
                ),
            )
        conn.commit()
    return {'ok': True, 'accepted': len(events)}


@app.post('/api/agent/instagram-manual')
def manual(body: dict[str, Any]) -> dict[str, Any]:
    authorized(body)
    control('manual', {'action': 'poll', 'agentHeartbeat': True})
    action = str(body.get('action') or 'claim')

    if action == 'queue':
        job_id = str(body.get('id') or '')
        shortcode = str(body.get('shortcode') or '')
        if not job_id or not shortcode:
            raise HTTPException(status_code=400, detail='Richiesta non valida')
        with LOCK, db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO orbit_manual_jobs(job_id, shortcode, status, requested_at)
                VALUES (?, ?, 'queued', ?)
                """,
                (job_id, shortcode, int(time.time() * 1000)),
            )
            conn.commit()
        return {'ok': True}

    if action == 'status':
        job_id = str(body.get('id') or '')
        with LOCK, db() as conn:
            row = conn.execute(
                'SELECT status, message FROM orbit_manual_jobs WHERE job_id=?',
                (job_id,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Richiesta non trovata')
        return {'status': row['status'], 'message': row['message'] or ''}

    if action == 'claim':
        cutoff = int(time.time() * 1000) - 120000
        with LOCK, db() as conn:
            row = conn.execute(
                """
                SELECT job_id, shortcode, requested_at
                FROM orbit_manual_jobs
                WHERE status='queued' AND requested_at >= ?
                ORDER BY requested_at
                LIMIT 1
                """,
                (cutoff,),
            ).fetchone()
            if not row:
                return {'job': None}
            conn.execute(
                "UPDATE orbit_manual_jobs SET status='executing' WHERE job_id=? AND status='queued'",
                (row['job_id'],),
            )
            conn.commit()
        return {
            'job': {
                'id': row['job_id'],
                'shortcode': row['shortcode'],
                'requested_at': row['requested_at'],
            }
        }

    if action == 'complete':
        job_id = str(body.get('id') or '')
        status = str(body.get('status') or 'failed')
        message = str(body.get('message') or '')[:300]
        now = int(time.time() * 1000)
        with LOCK, db() as conn:
            row = conn.execute(
                'SELECT shortcode FROM orbit_manual_jobs WHERE job_id=?',
                (job_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE orbit_manual_jobs
                    SET status=?, message=?, finished_at=?
                    WHERE job_id=?
                    """,
                    (status, message, now, job_id),
                )
                if status in {'applied', 'already_liked'}:
                    conn.execute(
                        'UPDATE orbit_likes SET status=?, liked_at=COALESCE(liked_at, ?) WHERE shortcode=?',
                        (
                            status,
                            time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            row['shortcode'],
                        ),
                    )
            conn.commit()
        return {'ok': True}

    raise HTTPException(status_code=400, detail='Azione non valida')
