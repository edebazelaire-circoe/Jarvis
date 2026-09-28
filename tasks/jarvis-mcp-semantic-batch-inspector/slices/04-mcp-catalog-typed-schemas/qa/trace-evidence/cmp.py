import json,re
r=json.load(open('results.json',encoding='utf-8'))
cut=lambda t:t.split('<system-reminder>')[0].rstrip('\n')
def keys(o,p=''):
    if isinstance(o,dict):
        out=[p+'.'+k for k in o]
        for k,v in o.items(): out+=keys(v,p+'.'+k)
        return out
    if isinstance(o,list) and o: return keys(o[0],p+'[]')
    return []
norm=lambda s: re.sub(r'brain-artifact-[0-9a-f]{12}|brain-explains-[0-9a-f]{16}|[0-9a-f-]{36}|\d{4}-\d\d-\d\dT[\d:.+Z-]+','X',s)
for (n,_,to),(_,_,tn) in zip(r['old'],r['new']):
    to,tn=cut(to),cut(tn)
    oo=json.loads(to); inner=None
    if n in('scene_inspect','scene_query','scene_get'): inner=oo['result']; oo=json.loads(inner)
    nn=json.loads(tn)
    ko,kn=keys(oo),keys(nn)
    print(f'{n:20} model-visible B old={len(to.encode())} new={len(tn.encode())} | key paths same+ordered={ko==kn}', '' if ko==kn else f'new-only={[k for k in kn if k not in ko]} old-only={[k for k in ko if k not in kn]}')
    if inner is not None:
        print(f'{"":20} old inner text == new text (ids/time normalized): {norm(inner)==norm(tn)}; new is compact JSON: {tn==json.dumps(nn,ensure_ascii=False,separators=(",",":"))}; wrapper overhead {len(to.encode())-len(inner.encode())} B ({100*(len(to.encode())-len(inner.encode()))/len(inner.encode()):.1f}%)')
    else:
        print(f'{"":20} identical (normalized): {norm(to)==norm(tn)}')
print('\nOLD update:',cut(r['old'][3][2]))
print('\nNEW inspect:',cut(r['new'][0][2])[:900])
