from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

app = FastAPI(title='Orbit Agent Relay', version='1.1.0')

AGENT_TOKEN = os.environ.get('ORBIT_AGENT_TOKEN', '')
ACCOUNT = os.environ.get('ORBIT_INSTAGRAM_USERNAME', 'ma.menichelli')
DB_PATH = Path(os.environ.get('ORBIT_RELAY_DB', '/tmp/orbit-relay.db'))
LOCK = threading.RLock()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, db() as conn:
        conn.executescript(
            """
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


def authorized(body: dict[str, Any]) -> None:
    actual = str(body.get('agentToken') or '')
    if not AGENT_TOKEN or not actual or not hmac.compare_digest(actual, AGENT_TOKEN):
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
        'tokenConfigured': bool(AGENT_TOKEN),
        'accountUsername': ACCOUNT,
        'storage': 'sqlite',
    }


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
        manual = state('manual')
        return {
            'accountUsername': ACCOUNT,
            'manualOnline': int(time.time() * 1000) - manual['last_seen'] < 120000,
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
            conn.execute('UPDATE orbit_likes SET status=? WHERE shortcode=?', ('skipped', shortcode))
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
    control('manual', {'action': 'poll'})
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
