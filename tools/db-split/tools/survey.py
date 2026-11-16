import sys, collections
sys.path.insert(0, '.')
from sqlsplit import statements, classify, LOAD_ORDER
cnt = collections.Counter()
for f in LOAD_ORDER:
    t = open('../../' + f, encoding='utf-8').read()
    for lead, s in statements(t):
        k, name = classify(s)
        cnt[k] += 1
        if k in ('function', 'do', 'other', 'select', 'view', 'prelude', 'update', 'grant'):
            print(f, k, name, '|', ' '.join(s.split())[:150])
print(cnt)
