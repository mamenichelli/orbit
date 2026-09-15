import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

test('General feed excludes Primary and uncertain origins, including mixed histories', () => {
  const source = readFileSync(new URL('../app/instagram-manual.ts', import.meta.url), 'utf8');
  const predicate = source.match(/generalPostPredicate = "([^"]+)"/)[1];
  const db = new DatabaseSync(':memory:');
  db.exec('CREATE TABLE browser_like_events (account_username TEXT, shortcode TEXT, groups_json TEXT)');
  const insert = db.prepare('INSERT INTO browser_like_events VALUES (?, ?, ?)');
  for (const [code, groups] of [
    ['general', [{folder:'general', verification:'general-roster-v2', threadPath:'/direct/t/1/'}]],
    ['primary', [{folder:'primary', threadPath:'/direct/t/2/'}]],
    ['unknown', [{threadPath:'/direct/t/3/'}]],
    ['legacy', []],
    ['stale-general', [{folder:'general', threadPath:'/direct/t/6/'}]],
    ['mixed', [{folder:'general', verification:'general-roster-v2', threadPath:'/direct/t/4/'}, {threadPath:'/direct/t/5/'}]],
  ]) insert.run('ma.menichelli', code, JSON.stringify(groups));
  const rows = db.prepare(`SELECT shortcode, groups_json FROM browser_like_events WHERE account_username=? AND ${predicate} ORDER BY shortcode`).all('ma.menichelli');
  assert.deepEqual(rows.map(row=>row.shortcode), ['general','mixed']);
  const displayed = rows.flatMap(row=>JSON.parse(row.groups_json).filter(group=>group.folder==='general'));
  assert.equal(displayed.length, 2);
  assert.ok(displayed.every(group=>group.folder==='general'));
  db.close();
});

test('Confirmed likes and persistent Skips disappear from the General list and count', () => {
  const source = readFileSync(new URL('../app/instagram-manual.ts', import.meta.url), 'utf8');
  const general = source.match(/generalPostPredicate = "([^"]+)"/)[1];
  const suffix = source.match(/visibleGeneralPostPredicate = generalPostPredicate \+ "([^"]+)"/)[1];
  const db = new DatabaseSync(':memory:');
  db.exec('CREATE TABLE browser_like_events (shortcode TEXT, status TEXT, groups_json TEXT)');
  const insert = db.prepare('INSERT INTO browser_like_events VALUES (?, ?, ?)');
  for (const status of ['discovered', 'applied', 'already_liked', 'skipped']) {
    insert.run(status, status, JSON.stringify([{folder:'general',verification:'general-roster-v2'}]));
  }
  insert.run('primary', 'discovered', JSON.stringify([{folder:'primary'}]));
  const predicate = general + suffix;
  assert.deepEqual(db.prepare(`SELECT shortcode FROM browser_like_events WHERE ${predicate}`).all().map(row=>row.shortcode), ['discovered']);
  assert.equal(db.prepare(`SELECT COUNT(*) AS total FROM browser_like_events WHERE ${predicate}`).get().total, 1);
  db.close();
});

test('Collector re-import preserves a user Skip', () => {
  const source = readFileSync(new URL('../app/api/agent/instagram-likes/route.ts', import.meta.url), 'utf8');
  const upsert = source.match(/db.prepare\(`(INSERT INTO browser_like_events[\s\S]+?)`\)/)[1];
  const db = new DatabaseSync(':memory:');
  db.exec('CREATE TABLE browser_like_events (event_id TEXT, account_username TEXT, shortcode TEXT, status TEXT, liked_at TEXT, observed_at TEXT, groups_json TEXT, metadata_json TEXT, UNIQUE(account_username,shortcode))');
  const insert = db.prepare(upsert);
  const groups = JSON.stringify([{folder:'general',verification:'general-roster-v2'}]);
  insert.run('id','ma.menichelli','post','skipped',null,'2026-09-15',groups,'{}');
  insert.run('new','ma.menichelli','post','discovered',null,'2026-09-16',groups,'{}');
  assert.equal(db.prepare('SELECT status FROM browser_like_events').get().status,'skipped');
  db.close();
});
