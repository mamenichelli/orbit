import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

test('Completion of an older scan does not acknowledge a newer refresh',()=>{
  const db=new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../drizzle/0011_worthless_dreaming_celestial.sql',import.meta.url),'utf8'));
  db.exec("INSERT INTO instagram_collection (account_username,requested_at,started_request_at) VALUES ('ma.menichelli',200,100)");
  const source=readFileSync(new URL('../app/api/agent/instagram-collection/route.ts',import.meta.url),'utf8');
  const sql=source.match(/db.prepare\("(UPDATE instagram_collection SET completed_request_at[^\"]+)"\)/)[1];
  db.prepare(sql).run(100,300,'ma.menichelli',100);
  const row=db.prepare('SELECT * FROM instagram_collection').get();
  assert.equal(row.completed_request_at,100);
  assert.ok(row.requested_at>row.completed_request_at);
  db.close();
});
test('Page reload requests a real scan and waits for that refresh version',()=>{
  const source=readFileSync(new URL('../app/page.tsx',import.meta.url),'utf8');
  assert.ok(source.includes("fetch('/api/instagram/refresh-posts',{method:'POST'"));
  assert.ok(source.includes('status.completed_request_at>=version'));
  assert.ok(source.includes('Aggiornamento da Instagram in corso'));
});
