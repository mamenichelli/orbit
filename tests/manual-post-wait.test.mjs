import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

test('Different clicked posts can wait independently, but the same post cannot be duplicated', () => {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../drizzle/0008_pale_excalibur.sql', import.meta.url),'utf8'));
  db.exec(readFileSync(new URL('../drizzle/0010_magical_punisher.sql', import.meta.url),'utf8'));
  const insert = db.prepare("INSERT OR IGNORE INTO instagram_manual_likes (id,account_username,shortcode,requested_by,status,requested_at) VALUES (?,'ma.menichelli',?,'owner','pending',?)");
  insert.run('click-a','post-a',Date.now());
  insert.run('click-b','post-b',Date.now());
  assert.equal(insert.run('duplicate-a','post-a',Date.now()).changes,0);
  const source=readFileSync(new URL('../app/api/agent/instagram-manual/route.ts',import.meta.url),'utf8');
  const claim=source.match(/db.prepare\(`(UPDATE instagram_manual_likes SET status='executing'[\s\S]+?)`\)/)[1];
  const next=db.prepare(claim);
  assert.equal(next.get('ma.menichelli',Date.now()-120000,'ma.menichelli').shortcode,'post-a');
  assert.equal(next.get('ma.menichelli',Date.now()-120000,'ma.menichelli'),undefined);
  assert.equal(db.prepare("SELECT status FROM instagram_manual_likes WHERE shortcode='post-b'").get().status,'pending');
  db.exec("UPDATE instagram_manual_likes SET status='applied' WHERE shortcode='post-a'");
  assert.equal(next.get('ma.menichelli',Date.now()-120000,'ma.menichelli').shortcode,'post-b');
  db.close();
});

test('Like and Skip controls freeze by shortcode, not by another post’s request', () => {
  const source=readFileSync(new URL('../app/page.tsx',import.meta.url),'utf8');
  assert.ok(source.includes('disabled={Boolean(manualLikes[event.shortcode]) ||'));
  assert.ok(source.includes('disabled={Boolean(manualLikes[event.shortcode])} onClick={() => void skipPost'));
  assert.ok(source.includes('if (manualRequests.current[shortcode] || hiddenPosts.current.has(shortcode)) return;'));
  assert.ok(!source.includes('Boolean(manualLike)'));
});
