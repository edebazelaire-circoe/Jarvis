import json,sys,collections
path=sys.argv[1]
uses={}; out=[]
for l in open(path,encoding='utf-8',errors='replace'):
    try: e=json.loads(l)
    except: continue
    if e.get('kind')!='agent.event': continue
    d=e['data']; m=d.get('message') or {}
    if d.get('type')=='assistant':
        for c in m.get('content') or []:
            if c.get('type')=='tool_use' and c['name'].startswith('mcp__jarvis'):
                uses[c['id']]=(e['ts'],c['name'],c.get('input'),d.get('session_id'),d.get('parent_tool_use_id'))
    elif d.get('type')=='user':
        for c in (m.get('content') or []) if isinstance(m.get('content'),list) else []:
            if c.get('type')=='tool_result' and c.get('tool_use_id') in uses:
                u=uses[c['tool_use_id']]
                content=c.get('content')
                if isinstance(content,list):
                    txt=''.join(x.get('text','') for x in content if x.get('type')=='text')
                else: txt=content or ''
                out.append(dict(ts=u[0],tool=u[1],input=u[2],sess=u[3],sub=u[4],is_error=c.get('is_error',False),bytes=len(txt.encode()),head=txt[:160],tur=d.get('tool_use_result')))
json.dump(out,open('pairs.json','w',encoding='utf-8'),ensure_ascii=False,default=str)
print(len(uses),'uses',len(out),'paired')
c=collections.Counter(o['tool'] for o in out); 
for k,v in c.most_common(): 
    bs=[o['bytes'] for o in out if o['tool']==k]; er=sum(o['is_error'] for o in out if o['tool']==k)
    wr=sum(o['head'].startswith('{"result":') for o in out if o['tool']==k)
    print(f'{v:4} {k:50} err={er} wrapped={wr} bytes min/med/max={min(bs)}/{sorted(bs)[len(bs)//2]}/{max(bs)}')
