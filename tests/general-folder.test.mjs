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
    ['general', [{folder:'general', threadPath:'/direct/t/1/'}]],
    ['primary', [{folder:'primary', threadPath:'/direct/t/2/'}]],
    ['unknown', [{threadPath:'/direct/t/3/'}]],
    ['legacy', []],
    ['mixed', [{folder:'general', threadPath:'/direct/t/4/'}, {threadPath:'/direct/t/5/'}]],
  ]) insert.run('ma.menichelli', code, JSON.stringify(groups));
  const rows = db.prepare(`SELECT shortcode, groups_json FROM browser_like_events WHERE account_username=? AND ${predicate} ORDER BY shortcode`).all('ma.menichelli');
  assert.deepEqual(rows.map(row=>row.shortcode), ['general','mixed']);
  const displayed = rows.flatMap(row=>JSON.parse(row.groups_json).filter(group=>group.folder==='general'));
  assert.equal(displayed.length, 2);
  assert.ok(displayed.every(group=>group.folder==='general'));
  db.close();
});

test('Confirmed likes disappear from both the General list and its count', () => {
  const source = readFileSync(new URL('../app/instagram-manual.ts', import.meta.url), 'utf8');
  const general = source.match(/generalPostPredicate = "([^"]+)"/)[1];
  const suffix = source.match(/visibleGeneralPostPredicate = generalPostPredicate \+ "([^"]+)"/)[1];
  const db = new DatabaseSync(':memory:');
  db.exec('CREATE TABLE browser_like_events (shortcode TEXT, status TEXT, groups_json TEXT)');
  const insert = db.prepare('INSERT INTO browser_like_events VALUES (?, ?, ?)');
  for (const status of ['discovered', 'applied', 'already_liked']) {
    insert.run(status, status, JSON.stringify([{folder:'general'}]));
  }
  insert.run('primary', 'discovered', JSON.stringify([{folder:'primary'}]));
  const predicate = general + suffix;
  assert.deepEqual(db.prepare(`SELECT shortcode FROM browser_like_events WHERE ${predicate}`).all().map(row=>row.shortcode), ['discovered']);
  assert.equal(db.prepare(`SELECT COUNT(*) AS total FROM browser_like_events WHERE ${predicate}`).get().total, 1);
  db.close();
});
