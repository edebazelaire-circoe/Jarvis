import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
for a in d['steps'][0]['actions']:
    i=a.get('id') or ''
    if a.get('error'): print('ERR',i,a['error'][:200])
    if i.startswith('info-'):
        v=a['value'];print(i,'mismatch',v['mismatch'],'trapLast',v['trapLast'],'realLast',v['realLast'],'unnamed',v['unnamed'],'live',[(l['id'],l['role'],l['live']) for l in v['live']])
    if i.startswith('tab-'):
        tr=[t for t in a['trail'] if t]
        print('  ',i,'ok',a['ok'],'presses',a['presses'],'noOutline',[(t['tag'],t['id'],t['text'][:20]) for t in tr if not t['outline']][:5],'out',[(t['tag'],t['id']) for t in tr if not t['inShell']][:3])
    if i.startswith('after-'):
        f=a.get('focused') or {};print('  ',i,f.get('tag'),f.get('id'),f.get('inShell'))
print('exc',d['exceptions'][:3]); print('console',[c for c in d['console'] if '424' not in c['text'] and 'favicon' not in c['text']][:5])
