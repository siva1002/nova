// Tenant isolation test on the tasks service database (the largest).
// Writes rows for two workspaces as the owner, then reads and writes as app_user with app.workspace_id set.
// Run from a folder with @electric-sql/pglite:  node isolation.mjs <path to plan/db/services>
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';
const dir = process.argv[2];
const db = new PGlite();
for (const f of ['_prelude.sql', 'tasks.sql', 'tasks.later.sql', '_epilogue.sql']) await db.exec(fs.readFileSync(`${dir}/${f}`, 'utf8'));
const A = '00000000-0000-0000-0000-00000000000a', B = '00000000-0000-0000-0000-00000000000b';
await db.exec(`insert into task_number_blocks values ('${A}', 1), ('${B}', 1);
  insert into member_copies values ('${A}','00000000-0000-0000-0000-000000000001','member','active',1),
                                   ('${B}','00000000-0000-0000-0000-000000000002','member','active',1);`);
let pass = 0, fail = 0;
const ok = (name, cond) => { console.log((cond ? 'pass ' : 'FAIL ') + name); cond ? pass++ : fail++; };
async function asTenant(ws, fn) {
  await db.exec('BEGIN; SET LOCAL ROLE app_user;');
  if (ws) await db.query(`select set_config('app.workspace_id', $1, true)`, [ws]);
  try { return await fn(); } finally { await db.exec('ROLLBACK;'); }
}
ok('A sees only its own counter', (await asTenant(A, () => db.query('select workspace_id from task_number_blocks'))).rows.every(r => r.workspace_id === A));
ok('A sees exactly one member row', (await asTenant(A, () => db.query('select * from member_copies'))).rows.length === 1);
ok('no workspace set = no rows', (await asTenant(null, () => db.query('select * from member_copies'))).rows.length === 0);
let blocked = false;
try { await asTenant(A, () => db.query(`insert into task_number_blocks values ('00000000-0000-0000-0000-00000000000c', 1)`)); } catch { blocked = true; }
ok('A cannot write a row for another workspace', blocked);
const upd = await asTenant(A, () => db.query(`update member_copies set status='deactivated' where workspace_id='${B}'`));
ok('A cannot update B rows (0 rows touched)', (upd.affectedRows ?? 0) === 0);
const n = (await db.query(`select count(*)::int n from pg_class where relrowsecurity and relforcerowsecurity`)).rows[0].n;
ok(`row security forced on ${n} tables`, n > 30);
console.log(`${pass} passed, ${fail} failed`);
await db.close();
process.exit(fail ? 1 : 0);
