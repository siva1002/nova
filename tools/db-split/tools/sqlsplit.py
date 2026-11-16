"""Split the single-database SQL design into statements and classify them.

Used by split.py. Handles -- comments, /* */ comments, 'strings', "idents" and $tag$ dollar quotes.
"""
import re

LOAD_ORDER = ['core-schema.sql', 'support-schema.sql', 'sprints-templates.sql', 'frd-delta.sql',
              'frd-roles-permissions.sql', 'enterprise-delta.sql', 'rls.sql']


def statements(text):
    """Yield (leading_comment, statement_sql) pairs. Statement excludes the trailing ';'."""
    i, n = 0, len(text)
    buf = []
    lead = []
    in_stmt = False
    while i < n:
        c = text[i]
        if c == '-' and text.startswith('--', i):
            j = text.find('\n', i)
            j = n if j < 0 else j + 1
            (buf if in_stmt else lead).append(text[i:j])
            i = j
            continue
        if c == '/' and text.startswith('/*', i):
            j = text.find('*/', i) + 2
            (buf if in_stmt else lead).append(text[i:j])
            i = j
            continue
        if c in "'\"":
            j = i + 1
            while True:
                j = text.find(c, j)
                if j + 1 < n and text[j + 1] == c:
                    j += 2
                    continue
                break
            buf.append(text[i:j + 1])
            in_stmt = True
            i = j + 1
            continue
        if c == '$':
            m = re.match(r'\$[A-Za-z_]*\$', text[i:])
            if m:
                tag = m.group(0)
                j = text.find(tag, i + len(tag)) + len(tag)
                buf.append(text[i:j])
                in_stmt = True
                i = j
                continue
        if c == ';':
            yield ''.join(lead).strip('\n'), ''.join(buf).strip()
            buf, lead, in_stmt = [], [], False
            i += 1
            continue
        if not in_stmt and c.isspace():
            if lead or c == '\n':
                lead.append(c) if lead else None
            i += 1
            continue
        buf.append(c)
        in_stmt = True
        i += 1
    rest = ''.join(buf).strip()
    if rest:
        yield ''.join(lead).strip('\n'), rest


def strip_comments(sql):
    sql = re.sub(r'--[^\n]*', '', sql)
    return re.sub(r'/\*.*?\*/', '', sql, flags=re.S)


ID = r'"?([A-Za-z_][A-Za-z0-9_]*)"?'


def classify(sql):
    """Return (kind, name) where name is the table or function the statement belongs to."""
    s = strip_comments(sql).strip()
    u = s.upper()
    m = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?' + ID + r'\s+PARTITION\s+OF\s+' + ID, s, re.I)
    if m:
        return 'partition', m.group(2)
    m = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?' + ID, s, re.I)
    if m:
        return 'table', m.group(1)
    m = re.match(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:' + ID + r'\s+)?ON\s+(?:ONLY\s+)?' + ID, s, re.I)
    if m:
        return 'index', m.group(2)
    m = re.match(r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?' + ID, s, re.I)
    if m:
        return 'alter', m.group(1)
    m = re.match(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:CONSTRAINT\s+)?TRIGGER\s+' + ID + r'.*?\sON\s+' + ID, s, re.I | re.S)
    if m:
        return 'trigger', m.group(2)
    m = re.match(r'(?:DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?' + ID + r'\s+ON\s+' + ID + ')', s, re.I)
    if m:
        return 'trigger', m.group(2)
    m = re.match(r'INSERT\s+INTO\s+' + ID, s, re.I)
    if m:
        return 'insert', m.group(1)
    m = re.match(r'UPDATE\s+' + ID, s, re.I)
    if m:
        return 'update', m.group(1)
    m = re.match(r'COMMENT\s+ON\s+(?:TABLE|COLUMN)\s+' + ID, s, re.I)
    if m:
        return 'comment', m.group(1)
    m = re.match(r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+' + ID, s, re.I)
    if m:
        return 'function', m.group(1)
    m = re.match(r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+' + ID, s, re.I)
    if m:
        return 'view', m.group(1)
    if u.startswith('CREATE EXTENSION') or u.startswith('SET ') or u.startswith('CREATE TYPE') or u.startswith('CREATE SCHEMA'):
        return 'prelude', None
    if u.startswith('DO '):
        return 'do', None
    if u.startswith('GRANT') or u.startswith('REVOKE') or u.startswith('CREATE POLICY') or u.startswith('DROP POLICY'):
        return 'grant', None
    if u.startswith('SELECT'):
        return 'select', None
    return 'other', None
