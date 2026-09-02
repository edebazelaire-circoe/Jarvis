from jarvis.security.v2_policy import ActionDisposition, V2ActionBroker


def test_v2_policy_matrix_is_code_owned_and_conservative():
    broker = V2ActionBroker()
    assert broker.evaluate("calendar_list", explicit_request=True, ambiguous=False) is ActionDisposition.EXECUTE
    assert broker.evaluate("reminder_create", explicit_request=True, ambiguous=False) is ActionDisposition.EXECUTE
    assert broker.evaluate("reminder_create", explicit_request=True, ambiguous=True) is ActionDisposition.CLARIFY
    assert broker.evaluate("calendar_delete", explicit_request=True, ambiguous=False) is ActionDisposition.CONFIRM
    assert broker.evaluate("calendar_invite", explicit_request=True, ambiguous=False) is ActionDisposition.CONFIRM
    assert broker.evaluate("not_a_tool", explicit_request=True, ambiguous=False) is ActionDisposition.DENY
    assert broker.evaluate("calendar_create", explicit_request=False, ambiguous=False) is ActionDisposition.CLARIFY
