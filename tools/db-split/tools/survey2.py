import sys
sys.path.insert(0, '.')
from sqlsplit import statements, classify, LOAD_ORDER
for f in LOAD_ORDER[:6]:
    t = open('../../' + f, encoding='utf-8').read()
    for lead, s in statements(t):
        k, name = classify(s)
        if k in ('do','view') or (k=='function' and name in ('timesheet_week','hourly_cost_cents')):
            print('=====', f, k, name); print(s[:1500])
