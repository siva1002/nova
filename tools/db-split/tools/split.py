"""Split plan/db/*.sql (one database) into one SQL file per service.

Run:  python split.py      (from this folder)
Out:  ../<service>.sql (phase 1), ../<service>.later.sql (later tables of that service), ../_dropped.sql,
      ../_moved-to-code.sql, ../SPLIT-REPORT.md
Foreign keys that point to a table owned by another service (or not loaded with it) are removed and
replaced by a comment  /* id -> service.table */  : the column stays, the database no longer checks it.
"""
import re
import sys
import collections
sys.path.insert(0, '.')
from sqlsplit import statements, classify, strip_comments, LOAD_ORDER

P1, LATER, DROP = 'p1', 'later', 'dropped'

# table -> (service, phase, note)
T = {}


def own(service, phase, names, note=''):
    for n in names.split():
        assert n not in T, n
        T[n] = (service, phase, note)


# ---------- global services (one per region, outside cells) ----------
own('identity', P1, 'users user_credentials user_sessions data_subject_requests')
own('identity', LATER, 'mfa_factors sso_connections scim_tokens verified_domains', 'sign-in options for later (no SSO in phase 1)')
own('routing', P1, 'tenants')
own('billing', LATER, 'plans subscriptions usage_counters invoices', 'billing is not in phase 1')
# ---------- cell services ----------
own('access', P1, 'capabilities workspaces roles role_capabilities workspace_members user_groups user_group_members invites '
    'container_grants invite_grants task_shares people_field_defs people_field_options people_field_values people_field_access')
own('access', LATER, 'share_links ip_allowlist support_access_grants')
own('hierarchy', P1, 'status_templates status_template_items spaces folders lists containers status_sets task_statuses '
    'status_transitions task_types container_settings status_required_fields')
own('tasks', P1, 'tasks task_list_memberships task_assignees task_group_assignees task_watchers tags task_tags '
    'task_dependencies task_links custom_fields custom_field_access custom_field_options custom_field_locations '
    'custom_field_values custom_field_value_items custom_field_computation custom_field_dependencies '
    'task_checklists task_checklist_items task_status_history task_time_estimates task_assignee_estimates '
    'task_assignee_points templates template_snapshots template_tags template_apply_jobs template_apply_id_map')
own('tasks', LATER, 'task_merges task_recurrences releases')
own('collab', P1, 'comments comment_mentions comment_reactions comment_read_state attachments')
own('collab', LATER, 'scheduled_comments approvals approval_reviewers')
own('files', P1, 'files file_previews')
own('views', P1, 'view_types views view_queries view_sorts view_columns view_board_config view_collapsed_groups '
    'view_shares export_jobs user_favorites user_recents')
own('time', P1, 'time_entries time_tags time_entry_tag_links timesheet_approvals user_capacity work_schedules '
    'holiday_calendars holidays')
own('time', LATER, 'time_off billable_rates')
own('sprints', P1, 'sprint_folder_settings sprints sprint_daily_stats space_sprint_points')
own('automation', P1, 'automation_resources automation_catalog_items automations automation_schedules automation_runs '
    'automation_usage')
own('notifications', P1, 'notification_types notifications notification_preferences notification_settings '
    'notification_deliveries watchers')
own('notifications', LATER, 'reminders')
own('import', P1, 'import_jobs import_row_errors external_id_map')
own('search', P1, 'search_index_state saved_searches')
own('audit', P1, 'audit_log audit_log_default security_events security_events_default data_access_log '
    'data_access_log_default change_log', 'change_log becomes the activity history, filled from Kafka')
own('audit', LATER, 'retention_policies legal_holds')
own('dashboards', LATER, 'dashboards dashboard_widgets dashboard_shares daily_container_snapshots scheduled_reports project_health')
own('ai', LATER, 'ai_settings ai_requests ai_requests_default')
own('goals', LATER, 'goal_folders goals goal_owners goal_targets goal_target_links goal_target_updates')
own('docs', LATER, 'docs doc_tags doc_pages doc_page_collab doc_page_versions doc_links')
own('forms', LATER, 'forms form_questions form_routing_rules form_submissions')
own('messaging', LATER, 'channels channel_members messages')
# ---------- dropped ----------
own('-', DROP, 'integrations api_tokens webhook_endpoints webhook_deliveries webhook_deliveries_default '
    'automation_webhooks inbound_email_addresses', 'no outside connections in phase 1 (decided 9 Nov 2026)')
own('-', DROP, 'cost_rates cost_settings budgets expenses budget_daily_actuals',
    'cost and budget are tenant custom fields (user correction, Nov 2026)')
own('-', DROP, 'bug_details', 'bug tracking not in scope')
own('-', DROP, 'event_consumers', 'replaced by Kafka consumer groups')
own('-', DROP, 'search_documents', 'replaced by OpenSearch')
own('-', DROP, 'idempotency_keys', 'replaced by the per-service idempotency_keys table in _prelude.sql')

GLOBAL = {'identity', 'routing', 'billing'}
SHARED_FUNCS = {'bump_version', 'support_hash_partitions', 'support_month_partitions', 'current_workspace',
                'audit_log_immutable', 'frd_append_only'}
FUNC_OWNER = {'timesheet_week': 'time', 'goal_recompute_progress': 'goals', 'folders_depth_check': 'hierarchy',
              'seed_default_roles': 'access'}
MOVED_TO_CODE = {'container_user_caps': 'access service, permission engine (plan/tech/04-permissions-spec.md)',
                 'task_user_caps': 'access service, permission engine (plan/tech/04-permissions-spec.md)',
                 'hourly_cost_cents': 'dropped: cost is a tenant formula field'}
SEQ_OWNER = {'change_log_seq': 'change_log'}
# statements dropped because they add cost columns that the user removed from scope
DROP_PATTERNS = [r'ALTER TABLE time_entries ADD COLUMN cost_', r'CREATE OR REPLACE VIEW v_time_by_user_billable']


def phase_of(table):
    return T[table][1]


def svc_of(table):
    return T[table][0]


def bucket(table):
    s, p, _ = T[table]
    if p == DROP:
        return '_dropped'
    return s if p == P1 else s + '.later'


def loadable_with(src_bucket, target):
    """Can a FK from a table in src_bucket point to target and still load?"""
    if target not in T:
        return False
    tb = bucket(target)
    if tb == src_bucket:
        return True
    # later file loads after the phase-1 file of the same service
    return src_bucket.endswith('.later') and tb == src_bucket[:-6]


removed = collections.defaultdict(list)   # bucket -> [(table, target)]

REF_RE = re.compile(r'REFERENCES\s+"?([a-z_][a-z0-9_]*)"?\s*(\([^)]*\))?((?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|RESTRICT|NO ACTION|SET NULL|SET DEFAULT))*)'
                    r'(\s+DEFERRABLE(?:\s+INITIALLY\s+(?:DEFERRED|IMMEDIATE))?)?', re.I)


def split_elements(body):
    """Split a CREATE TABLE body at top-level commas, keeping comments with their element."""
    out, depth, cur, i = [], 0, [], 0
    while i < len(body):
        c = body[i]
        if body.startswith('--', i):
            j = body.find('\n', i)
            j = len(body) if j < 0 else j
            cur.append(body[i:j]); i = j; continue
        if c == "'":
            j = body.find("'", i + 1)
            while j + 1 < len(body) and body[j + 1] == "'":
                j = body.find("'", j + 2)
            cur.append(body[i:j + 1]); i = j + 1; continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if c == ',' and depth == 0:
            out.append(''.join(cur)); cur = []; i += 1; continue
        cur.append(c); i += 1
    out.append(''.join(cur))
    return out


def fix_refs(sql, table, b):
    """Remove FKs that cannot load in bucket b. Returns new sql."""
    def inline(m):
        target = m.group(1)
        if loadable_with(b, target):
            return m.group(0)
        where = (svc_of(target) + '.' + target) if target in T else target
        if target in T and phase_of(target) == DROP:
            where = 'dropped ' + target
        removed[b].append((table, target))
        return f'/* id -> {where} */'

    s = sql
    m = re.match(r'(\s*CREATE\s+TABLE[^(]*\()(.*)(\)[^)]*)$', s, re.I | re.S)
    if m and 'PARTITION OF' not in s.upper().split('(')[0]:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        els = split_elements(body)
        keep = []
        for e in els:
            core = strip_comments(e).strip()
            if re.match(r'(CONSTRAINT\s+\S+\s+)?FOREIGN\s+KEY', core, re.I):
                rm = REF_RE.search(core)
                if rm and not loadable_with(b, rm.group(1)):
                    removed[b].append((table, rm.group(1)))
                    note = '\n  -- cross-service FK removed: ' + ' '.join(core.split()) + '\n'
                    if keep:
                        keep[-1] = keep[-1].rstrip() + note
                    continue
            keep.append(REF_RE.sub(inline, e))
        return head + ','.join(keep) + tail
    if re.match(r'\s*ALTER\s+TABLE', s, re.I):
        core = strip_comments(s)
        if re.search(r'ADD\s+(CONSTRAINT\s+\S+\s+)?FOREIGN\s+KEY', core, re.I):
            rm = REF_RE.search(core)
            if rm and not loadable_with(b, rm.group(1)):
                removed[b].append((table, rm.group(1)))
                return None
        return REF_RE.sub(inline, s)
    return s


def main():
    out = collections.defaultdict(list)
    report_rows = []
    seen_tables = set()
    for f in LOAD_ORDER:
        if f == 'rls.sql':
            continue  # rebuilt per service in _epilogue.sql
        text = open('../../' + f, encoding='utf-8').read()
        for lead, s in statements(text):
            kind, name = classify(s)
            full = (lead + '\n' if lead else '') + s + ';\n'
            if any(re.search(p, s, re.I) for p in DROP_PATTERNS):
                out['_dropped'].append(f'-- from {f}\n' + full); continue
            if kind == 'function':
                if name in SHARED_FUNCS:
                    out['_prelude'].append(full); continue
                if name in MOVED_TO_CODE:
                    out['_moved-to-code'].append(f'-- from {f}; now: {MOVED_TO_CODE[name]}\n' + full); continue
                owner = FUNC_OWNER[name]
                b = owner if owner not in ('goals',) else owner + '.later'
                out[b].append(full); continue
            if kind == 'do':
                if 'bump_version()' in s:
                    continue  # generic trigger loop in _epilogue.sql
                tm = re.search(r"conrelid\s*=\s*'([a-z_]+)'::regclass", s)
                out[bucket(tm.group(1))].append(full); continue
            if kind == 'select':
                tm = re.search(r"\('([a-z_]+)'", s)
                out[bucket(tm.group(1))].append(full); continue
            if kind == 'other':
                sm = re.match(r'CREATE\s+SEQUENCE\s+([a-z_]+)', s, re.I)
                out[bucket(SEQ_OWNER[sm.group(1)])].append(full); continue
            if kind == 'trigger':
                out[bucket(name)].append(full); continue
            if kind in ('table', 'partition', 'index', 'alter', 'insert', 'update', 'comment', 'view'):
                if name not in T:
                    raise SystemExit(f'unmapped table {name} in {f}: {s[:80]}')
                b = bucket(name)
                if kind == 'table':
                    seen_tables.add(name)
                if b != '_dropped':
                    s2 = fix_refs(s, name, b)
                    if s2 is None:
                        out[b].append('-- cross-service FK removed: ' + ' '.join(strip_comments(s).split()) + '\n'); continue
                    full = (lead + '\n' if lead else '') + s2 + ';\n'
                out[b].append(full); continue
            raise SystemExit(f'unhandled {kind} in {f}: {s[:100]}')
    missing = set(T) - seen_tables - {'audit_log_default', 'security_events_default', 'data_access_log_default',
                                       'ai_requests_default', 'webhook_deliveries_default'}
    if missing:
        raise SystemExit('mapped but not found: ' + ' '.join(sorted(missing)))

    import os
    for f in sorted(os.listdir('extra')):
        out[f[:-4]].append(open('extra/' + f, encoding='utf-8').read())
    for b, parts in out.items():
        svc = b.split('.')[0]
        hdr = [f'-- Service: {svc}  ({"global, one per region" if svc in GLOBAL else "per cell"})',
               '-- GENERATED by tools/split.py from plan/db/*.sql. Edit the source files or split.py, then re-run.',
               '-- Load order: _prelude.sql, ' + (f'{svc}.sql, ' if b.endswith('.later') else '') + f'{b}.sql, _epilogue.sql',
               '']
        if b == '_prelude':
            hdr = ['-- Loaded FIRST into every service database. GENERATED by tools/split.py: shared functions copied',
                   '-- from plan/db, then tools/prelude-extra.sql (outbox, inbox, idempotency).', '']
            parts = parts + [open('prelude-extra.sql', encoding='utf-8').read()]
        if b in ('_dropped', '_moved-to-code'):
            hdr = ['-- NOT LOADED. Kept as a record of what left the design and why. GENERATED by tools/split.py.', '']
        open(f'../{b}.sql', 'w', encoding='utf-8', newline='\n').write('\n'.join(hdr) + '\n'.join(parts))

    # report
    lines = ['# Schema split report (generated by `tools/split.py`)', '',
             'Every table of `plan/db` and where it went. Phase: p1 = phase 1, later = parked, dropped = removed with reason.', '',
             '| Table | Service | Phase | Note |', '|---|---|---|---|']
    for t, (s, p, note) in sorted(T.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0])):
        lines.append(f'| {t} | {s} | {p} | {note} |')
    lines += ['', '## Foreign keys turned into plain ids', '',
              'The column stays and is still indexed; the owning service checks it by API or a local copy kept from events.', '',
              '| File | Table | Points to (owner) |', '|---|---|---|']
    for b in sorted(removed):
        for table, target in sorted(set(removed[b])):
            owner = svc_of(target) if target in T else '?'
            lines.append(f'| {b}.sql | {table} | {target} ({owner}) |')
    cnt = collections.Counter(p for _, p, _ in T.values())
    lines += ['', f'Totals: {len(T)} tables; phase 1 {cnt[P1]}, later {cnt[LATER]}, dropped {cnt[DROP]}; '
              f'{sum(len(set(v)) for v in removed.values())} cross-service foreign keys removed.']
    open('../SPLIT-REPORT.md', 'w', encoding='utf-8', newline='\n').write('\n'.join(lines) + '\n')
    print('buckets:', ' '.join(sorted(out)))
    print(lines[-1])


if __name__ == '__main__':
    main()
