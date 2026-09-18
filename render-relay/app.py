from __future__ import annotations

import os
import time
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title='Orbit Agent Relay', version='1.0.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['https://orbit-parallel-thwhpj.v2.appdeploy.ai'],
    allow_credentials=False,
    allow_methods=['GET', 'POST'],
    allow_headers=['Content-Type'],
)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
AGENT_TOKEN = os.environ.get('ORBIT_AGENT_TOKEN', '')
ACCOUNT = os.environ.get('ORBIT_INSTAGRAM_USERNAME', 'ma.menichelli')


def conn():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL missing')
    return psycopg.connect(DATABASE_URL)


def authorized(body: dict[str, Any]) -> None:
    if not AGENT_TOKEN or str(body.get('agentToken', '')) != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail='Non autorizzato')


def init_db() -> None:
    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS orbit_state (
                  name TEXT PRIMARY KEY,
                  requested_at BIGINT NOT NULL DEFAULT 0,
                  started_request_at BIGINT NOT NULL DEFAULT 0,
                  completed_request_at BIGINT NOT NULL DEFAULT 0,
                  last_seen BIGINT NOT NULL DEFAULT 0,
                  error TEXT NOT NULL DEFAULT ''
                )
                '''
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS orbit_likes (
                  shortcode TEXT PRIMARY KEY,
                  account_username TEXT NOT NULL,
                  event_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  liked_at TEXT,
                  observed_at TEXT NOT NULL,
                  groups_json JSONB NOT NULL DEFAULT '[]',
                  metadata_json JSONB NOT NULL DEFAULT '{}'
                )
                '''
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS orbit_manual_jobs (
                  job_id TEXT PRIMARY KEY,
                  shortcode TEXT NOT NULL,
                  status TEXT NOT NULL,
                  requested_at BIGINT NOT NULL,
                  message TEXT NOT NULL DEFAULT '',
                  finished_at BIGINT
                )
                '''
            )
        db.commit()


@app.on_event('startup')
def startup() -> None:
    init_db()


def get_state(name: str) -> dict[str, Any]:
    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO orbit_state(name) VALUES (%s)
                ON CONFLICT(name) DO NOTHING
                ''',
                (name,),
            )
            cur.execute(
                '''
                SELECT requested_at, started_request_at, completed_request_at, last_seen, error
                FROM orbit_state WHERE name=%s
                ''',
                (name,),
            )
            row = cur.fetchone()
        db.commit()
    return {
        'requested_at': int(row[0] or 0),
        'started_request_at': int(row[1] or 0),
        'completed_request_at': int(row[2] or 0),
        'last_seen': int(row[3] or 0),
        'error': row[4] or '',
    }


def control(name: str, body: dict[str, Any]) -> dict[str, Any]:
    action = str(body.get('action') or 'poll')
    if action not in {'poll', 'request', 'started', 'finished', 'failed', 'required'}:
        raise HTTPException(status_code=400, detail='Azione non valida')
    state = get_state(name)
    now = int(time.time() * 1000)
    state['last_seen'] = now
    if action == 'request':
        state['requested_at'] = now
        state['error'] = ''
    elif action == 'started':
        state['started_request_at'] = state['requested_at']
        state['error'] = ''
    elif action == 'finished':
        state['completed_request_at'] = max(state['completed_request_at'], int(body.get('version') or 0))
        state['error'] = ''
    elif action == 'failed':
        state['completed_request_at'] = max(state['completed_request_at'], int(body.get('version') or 0))
        state['error'] = str(body.get('message') or 'Operazione non completata')[:300]
    elif action == 'required':
        state['error'] = str(body.get('message') or 'Sessione Instagram scaduta')[:300]

    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                '''
                UPDATE orbit_state
                SET requested_at=%s, started_request_at=%s, completed_request_at=%s,
                    last_seen=%s, error=%s
                WHERE name=%s
                ''',
                (
                    state['requested_at'],
                    state['started_request_at'],
                    state['completed_request_at'],
                    state['last_seen'],
                    state['error'],
                    name,
                ),
            )
        db.commit()
    return state


@app.get('/health')
def health():
    return {'ok': True, 'tokenConfigured': bool(AGENT_TOKEN), 'databaseConfigured': bool(DATABASE_URL)}


@app.post('/api/agent/instagram-browser-auth')
def browser_auth(body: dict[str, Any]):
    authorized(body)
    return control('browser_auth', body)


@app.post('/api/agent/instagram-collection')
def collection(body: dict[str, Any]):
    authorized(body)
    return control('collection', body)


@app.post('/api/agent/instagram-likes')
def likes(body: dict[str, Any]):
    authorized(body)
    action = str(body.get('action') or 'push')

    if action == 'list':
        with conn() as db:
            with db.cursor() as cur:
                cur.execute(
                    '''
                    SELECT shortcode, event_id, status, liked_at, observed_at, groups_json, metadata_json
                    FROM orbit_likes
                    WHERE status NOT IN ('applied','already_liked','skipped')
                    ORDER BY observed_at DESC
                    LIMIT 100
                    '''
                )
                rows = cur.fetchall()
        manual = get_state('manual')
        return {
            'accountUsername': ACCOUNT,
            'manualOnline': int(time.time() * 1000) - manual['last_seen'] < 120000,
            'events': [
                {
                    'id': r[0],
                    'shortcode': r[0],
                    'eventId': r[1],
                    'status': r[2],
                    'likedAt': r[3],
                    'observedAt': r[4],
                    'groups': r[5] or [],
                    'metadata': r[6] or {},
                }
                for r in rows
            ],
        }

    if action == 'skip':
        shortcode = str(body.get('shortcode') or '')
        with conn() as db:
            with db.cursor() as cur:
                cur.execute('UPDATE orbit_likes SET status=%s WHERE shortcode=%s', ('skipped', shortcode))
            db.commit()
        return {'ok': True}

    events = body.get('events') if isinstance(body.get('events'), list) else []
    if len(events) > 100:
        raise HTTPException(status_code=400, detail='Troppi eventi')
    with conn() as db:
        with db.cursor() as cur:
            for event in events:
                shortcode = str(event.get('shortcode') or '')
                if not shortcode:
                    continue
                cur.execute(
                    '''
                    INSERT INTO orbit_likes
                      (shortcode, account_username, event_id, status, liked_at, observed_at, groups_json, metadata_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(shortcode) DO UPDATE SET
                      event_id=EXCLUDED.event_id,
                      status=EXCLUDED.status,
                      liked_at=EXCLUDED.liked_at,
                      observed_at=EXCLUDED.observed_at,
                      groups_json=EXCLUDED.groups_json,
                      metadata_json=EXCLUDED.metadata_json
                    ''',
                    (
                        shortcode,
                        str(body.get('accountUsername') or ACCOUNT),
                        str(event.get('eventId') or ''),
                        str(event.get('status') or 'discovered'),
                        event.get('likedAt'),
                        str(event.get('observedAt') or ''),
                        psycopg.types.json.Jsonb(event.get('groups') or []),
                        psycopg.types.json.Jsonb(event.get('metadata') or {}),
                    ),
                )
        db.commit()
    return {'ok': True, 'accepted': len(events)}


@app.post('/api/agent/instagram-manual')
def manual(body: dict[str, Any]):
    authorized(body)
    control('manual', {'action': 'poll'})
    action = str(body.get('action') or 'claim')

    if action == 'queue':
        job_id = str(body.get('id') or '')
        shortcode = str(body.get('shortcode') or '')
        if not job_id or not shortcode:
            raise HTTPException(status_code=400, detail='Richiesta non valida')
        with conn() as db:
            with db.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO orbit_manual_jobs(job_id, shortcode, status, requested_at)
                    VALUES (%s,%s,'queued',%s)
                    ON CONFLICT(job_id) DO NOTHING
                    ''',
                    (job_id, shortcode, int(time.time() * 1000)),
                )
            db.commit()
        return {'ok': True}

    if action == 'status':
        job_id = str(body.get('id') or '')
        with conn() as db:
            with db.cursor() as cur:
                cur.execute('SELECT status, message FROM orbit_manual_jobs WHERE job_id=%s', (job_id,))
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Richiesta non trovata')
        return {'status': row[0], 'message': row[1] or ''}

    if action == 'claim':
        cutoff = int(time.time() * 1000) - 120000
        with conn() as db:
            with db.cursor() as cur:
                cur.execute(
                    '''
                    SELECT job_id, shortcode, requested_at
                    FROM orbit_manual_jobs
                    WHERE status='queued' AND requested_at >= %s
                    ORDER BY requested_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    ''',
                    (cutoff,),
                )
                row = cur.fetchone()
                if not row:
                    db.commit()
                    return {'job': None}
                cur.execute('UPDATE orbit_manual_jobs SET status=%s WHERE job_id=%s', ('executing', row[0]))
            db.commit()
        return {'job': {'id': row[0], 'shortcode': row[1], 'requested_at': row[2]}}

    if action == 'complete':
        job_id = str(body.get('id') or '')
        status = str(body.get('status') or 'failed')
        message = str(body.get('message') or '')[:300]
        with conn() as db:
            with db.cursor() as cur:
                cur.execute('SELECT shortcode FROM orbit_manual_jobs WHERE job_id=%s', (job_id,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        '''
                        UPDATE orbit_manual_jobs
                        SET status=%s, message=%s, finished_at=%s
                        WHERE job_id=%s
                        ''',
                        (status, message, int(time.time() * 1000), job_id),
                    )
                    if status in {'applied', 'already_liked'}:
                        cur.execute(
                            'UPDATE orbit_likes SET status=%s, liked_at=COALESCE(liked_at,%s) WHERE shortcode=%s',
                            (status, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), row[0]),
                        )
            db.commit()
        return {'ok': True}

    raise HTTPException(status_code=400, detail='Azione non valida')
