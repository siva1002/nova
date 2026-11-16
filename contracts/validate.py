"""Validate every contract: OpenAPI 3.1 documents (with cross-file $refs) and event JSON Schemas,
including sample events that must pass and must fail.
Run with a Python that has openapi-spec-validator, jsonschema, pyyaml:  python validate.py
"""
import json
import pathlib
import sys
import uuid
import yaml
from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename
from referencing import Registry, Resource

root = pathlib.Path(__file__).parent
bad = 0

for f in sorted((root / 'openapi').glob('*.yaml')):
    try:
        spec, base_uri = read_from_filename(str(f))
        validate(spec, base_uri=base_uri)
        n = sum(len([m for m in v if m in ('get', 'post', 'put', 'patch', 'delete')]) for v in spec['paths'].values())
        ids = [op.get('operationId') for v in spec['paths'].values() for m, op in v.items() if isinstance(op, dict) and m in ('get', 'post', 'put', 'patch', 'delete')]
        assert len(ids) == len(set(ids)), 'duplicate operationId'
        print(f'OK   openapi {f.name}: {n} operations')
    except Exception as e:
        bad += 1
        print(f'FAIL openapi {f.name}: {str(e)[:400]}')

schemas = {}
for f in sorted((root / 'events').glob('*.schema.json')):
    s = json.loads(f.read_text(encoding='utf-8'))
    validator_for(s).check_schema(s)
    schemas[s['$id']] = s
registry = Registry().with_resources([(k, Resource.from_contents(v)) for k, v in schemas.items()])
print(f'OK   events: {len(schemas)} schemas are valid JSON Schema 2020-12')


def ev(t, agg, after):
    return {'id': str(uuid.uuid4()), 'type': t, 'schema_version': 1, 'workspace_id': str(uuid.uuid4()),
            'aggregate_type': agg, 'aggregate_id': str(uuid.uuid4()), 'aggregate_version': 3,
            'occurred_at': '2026-11-10T09:30:00Z', 'actor': {'type': 'user', 'id': str(uuid.uuid4())}, 'depth': 0,
            'data': {'after': after, 'changes': [{'field': 'title', 'before': 'a', 'after': 'b'}]}}


u = lambda: str(uuid.uuid4())
task = {'id': u(), 'version': 3, 'number': 12, 'title': 'Module 1', 'home_list_id': u(), 'list_ids': [], 'status_id': u(),
        'status_category': 'open', 'created_by': u(), 'assignee_ids': []}
samples = [
    ('tasks.task.v1.schema.json', ev('tasks.task.updated', 'task', task), True),
    ('tasks.task.v1.schema.json', ev('tasks.task.updated', 'task', {**task, 'status_category': 'started'}), False),
    ('tasks.task.v1.schema.json', {**ev('tasks.task.updated', 'task', task), 'depth': 6}, False),
    ('time.entry.v1.schema.json', ev('time.entry.stopped', 'time_entry', {'id': u(), 'version': 2, 'user_id': u(), 'task_id': u(),
        'started_at': '2026-11-10T08:00:00Z', 'ended_at': '2026-11-10T09:00:00Z', 'duration_ms': 3600000, 'billable': False, 'deleted': False}), True),
    ('time.entry.v1.schema.json', ev('time.entry.stopped', 'time_entry', {'id': u(), 'version': 2, 'user_id': u(),
        'started_at': '2026-11-10T08:00:00Z', 'duration_ms': -5, 'billable': False, 'deleted': False}), False),
    ('access.member.v1.schema.json', ev('access.member.added', 'member', {'user_id': u(), 'version': 1, 'role_kind': 'member',
        'status': 'active', 'cell_id': 'aps1-c01', 'workspace_name': 'Acme'}), True),
    ('hierarchy.container.v1.schema.json', ev('hierarchy.container.moved', 'list', {'id': u(), 'version': 4, 'kind': 'list',
        'ancestor_ids': [u(), u()], 'is_restricted': False, 'status_set_id': u()}), True),
    ('tasks.field_value.v1.schema.json', ev('tasks.field_value.changed', 'task', {'task_id': u(), 'values': {u(): {'value': '53400', 'computed': True}}}), True),
]
for sid, doc, should in samples:
    v = Draft202012Validator(schemas[sid], registry=registry)
    errs = list(v.iter_errors(doc))
    good = (not errs) == should
    bad += 0 if good else 1
    print(('OK   ' if good else 'FAIL ') + f'sample {sid} {doc["type"]} expected {"valid" if should else "invalid"}'
          + ('' if good else f': {errs[:1]}'))
sys.exit(1 if bad else 0)
