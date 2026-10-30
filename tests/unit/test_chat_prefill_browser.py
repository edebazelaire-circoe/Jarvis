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
