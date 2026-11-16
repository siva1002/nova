// Load every service into its OWN empty PGlite database: proves no service needs another's tables.
// Run from a folder that has @electric-sql/pglite installed:  node check.mjs <path to plan/db/services>
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';
const dir = process.argv[2];
const files = fs.readdirSync(dir).filter(f => f.endsWith('.sql') && !f.startsWith('_'));
const services = [...new Set(files.map(f => f.split('.')[0]))].sort();
let bad = 0;
for (const s of services) {
  const db = new PGlite();
  const order = ['_prelude.sql', `${s}.sql`, `${s}.later.sql`, '_epilogue.sql'].filter(f => fs.existsSync(`${dir}/${f}`));
  let ok = true;
  for (const f of order) {
    try { await db.exec(fs.readFileSync(`${dir}/${f}`, 'utf8')); }
    catch (e) { console.log(`FAIL ${s}: ${f}: ${e.message}`); ok = false; bad++; break; }
  }
  if (ok) {
    const t = (await db.query(`select count(*)::int n from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relkind in ('r','p') and not c.relispartition`)).rows[0].n;
    const fk = (await db.query(`select count(*)::int n from pg_constraint where contype='f'`)).rows[0].n;
    const rls = (await db.query(`select count(*)::int n from pg_class where relrowsecurity`)).rows[0].n;
    console.log(`OK   ${s.padEnd(14)} files=${order.length} tables=${t} fks=${fk} rls_tables=${rls}`);
  }
  await db.close();
}
process.exit(bad ? 1 : 0);
