"""Independent label and evaluator checks that matter to the experiment."""
import itertools, hashlib, json
from lab import load, ROOT, execute_spec, grade
solutions=[]
for a,b,c in itertools.product([False,True],repeat=3):
    if a==(not b) and b==(a==c) and c==b:solutions.append((a,b,c))
assert solutions==[(True,False,False)]
x=[[]]*3;x[0].append(1);assert x==[[1],[1],[1]]
y=[[] for _ in range(3)];y[0].append(1);assert y==[[1],[],[]]
try:{} in set()
except TypeError:pass
else:raise AssertionError('dict must be unhashable')
options=[]
for a,b,c in itertools.product(range(8),repeat=3):
    capacity=120*a+200*b+350*c
    if capacity>=500:options.append((80*a+150*b+300*c,a+b+c,a,b,c,capacity))
assert min(options)==(380,3,1,2,0,520)
assert 347*29-186*17+245==7146
for domain in ['table']:
    for split in ['dev','heldout']:
        for c in load(domain+'-'+split):assert execute_spec(c['rows'],c['spec'])==c['expected']
manifest=json.loads((ROOT/'data/manifest.json').read_text())
for name,expected in manifest.items():assert hashlib.sha256((ROOT/'data'/f'{name}.jsonl').read_bytes()).hexdigest()==expected['sha256']
dummy={'id':'audit','domain':'diff','expected':{'changed':False},'schema':{'fields':[{'name':'changed','type':'bool'}]}}
assert not grade(dummy,{'status':'ok','text':'{"changed":true}'},'guided')['pass']
assert not grade(dummy,{'status':'ok','text':'{"changed":false,"changed":false}'},'guided')['format']
assert not grade(dummy,{'status':'incomplete','text':'{"changed":false}'},'guided')['pass']
assert not grade(dummy,{'status':'ok','text':'{"changed":"false"}'},'guided')['schema']
print('PASS: independent regression labels, safe executor, frozen fixtures, duplicate/type/incomplete rejection')
