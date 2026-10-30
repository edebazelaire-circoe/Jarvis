"""Targeted draft seam: native composer, retained draft, no send/channel switch."""
from tests.unit.test_control_center_chat_browser import OPEN, _drive, _until


def test_agent_prefill_keeps_draft_and_voice_and_never_sends(tmp_path):
    out=_drive(tmp_path,[OPEN,_until("document.querySelectorAll('#chatLog .chat-msg').length===4"),
        {'type':'Mon brouillon existant'},
        {'value':'prefill','expr':"JarvisChat.prefill({text:'Question sur job:analyse',target:{source:'job',external_id:'analyse'}})"},
        {'value':'after'},
        {'value':'overflow','expr':"JarvisChat.prefill({text:'x'.repeat(8192),target:{source:'job'}})"},
        {'value':'kept'},
        {'value':'abort','expr':"JarvisChat.prefill({text:'Annulée',signal:AbortSignal.abort()})"},
        {'value':'cancelled'},
    ])
    r=out['reads'];assert r['prefill']['ok']
    assert r['after']['composer']['value']=='Mon brouillon existant\n\nQuestion sur job:analyse'
    assert r['overflow']['code']=='chat_draft_full'
    assert r['abort']['code']=='cancelled'
    assert r['kept']['composer']['value']==r['after']['composer']['value']==r['cancelled']['composer']['value']
    assert not [c for c in r['cancelled']['fake']['calls'] if c.startswith('POST ') and ('/turns' in c or '/voice' in c)]


def test_closed_chat_prefill_refreshes_board_scope_and_preserves_both_drafts(tmp_path):
    setup="""
      const originalFetch=window.fetch;
      window.fetch=async(path,init)=>{const response=await originalFetch(path,init);
        if(path==='/api/chat/state'&&window.__chat.scopeDelay)await new Promise(r=>setTimeout(r,window.__chat.scopeDelay));
        return response};
    """
    saved="({a:JSON.parse(localStorage.getItem('jarvis.chat.draft.conv-a')),b:JSON.parse(localStorage.getItem('jarvis.chat.draft.conv-b'))})"
    out=_drive(tmp_path,[OPEN,_until("document.querySelectorAll('#chatLog .chat-msg').length===4"),
        {'type':'Brouillon Jarvis'}, {'value':'typedA'}, {'click':'#chatClose'},
        {'eval':"localStorage.setItem('jarvis.chat.draft.conv-b',JSON.stringify({id:'saved-b',text:'Brouillon Atlas',att:[]}));__chat.scopeDelay=350;__chat.board('board_b','conv-b');1"},
        _until("JarvisBoardsControl.activeId()==='board_b'",name='board_b_ready'),
        {'value':'stale','expr':'JarvisChat.instance.snapshot()'},
        {'value':'cancelledRead','expr':"(()=>{const c=new AbortController();setTimeout(()=>c.abort(),50);return JarvisChat.prefill({text:'Ne pas ajouter',signal:c.signal})})()"},
        {'value':'draftsCancelled','expr':saved},
        {'value':'toB','expr':"JarvisChat.prefill({text:'Question pour Atlas'})"}, {'value':'onB'}, {'value':'draftsB','expr':saved},
        {'click':'#chatClose'}, {'eval':"__chat.board('default','conv-a');1"},
        _until("JarvisBoardsControl.activeId()==='default'",name='board_a_ready'),
        {'value':'toA','expr':"JarvisChat.prefill({text:'Question pour Jarvis'})"}, {'value':'onA'}, {'value':'draftsA','expr':saved},
    ],setup=setup)
    r=out['reads']
    assert r['typedA']['composer']['value']=='Brouillon Jarvis'
    assert r['until:board_b_ready'] and r['until:board_a_ready']
    assert not r['stale']['open'] and r['stale']['conversation_id']=='conv-a'
    assert r['cancelledRead'].get('code')=='cancelled',(r['cancelledRead'],r['draftsCancelled'])
    assert r['draftsCancelled']['a']['text']=='Brouillon Jarvis' and r['draftsCancelled']['b']['text']=='Brouillon Atlas'
    assert r['toB']=={'ok':True,'conversation_id':'conv-b'},r['toB']
    assert r['onB']['composer']['value']=='Brouillon Atlas\n\nQuestion pour Atlas'
    assert r['draftsB']['a']['text']=='Brouillon Jarvis'
    assert r['toA']=={'ok':True,'conversation_id':'conv-a'},r['toA']
    assert r['onA']['composer']['value']=='Brouillon Jarvis\n\nQuestion pour Jarvis'
    assert r['draftsA']['b']['text']=='Brouillon Atlas\n\nQuestion pour Atlas'
    assert not r['onA']['fake']['turns'] and not r['onA']['fake']['disables']
