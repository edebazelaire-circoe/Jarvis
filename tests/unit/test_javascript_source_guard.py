"""Comment hygiene cannot turn the browser-dialog source guard into an ignore."""
import pytest

from tests.fakes.javascript_source import browser_dialog_calls


def test_comments_method_declarations_and_urls_are_not_browser_calls():
    source="""// Never confirm() here.
    /* alert('bad'); prompt('bad'); */
    const url='https://example.test';
    const pending={confirm(id,token){return token}};
    pending.confirm('id','token');
    """
    assert browser_dialog_calls(source)==[]


@pytest.mark.parametrize('call',["alert('x')","window.confirm('x')","prompt ('x')","window . alert /* note */ ('x')","if(confirm('x')){run()}","globalThis.prompt('x')","self.alert('x')"])
def test_actual_forbidden_calls_are_still_detected(call):
    assert browser_dialog_calls('// comment\n'+call)


def test_html_guard_reads_scripts_and_inline_handlers_without_prose_or_html_comments():
    assert browser_dialog_calls("<p>Do not use confirm()</p><!-- alert('x') --><script>// confirm()\nrun()</script>",html=True)==[]
    assert browser_dialog_calls('<script>window.alert("x")</script>',html=True)==['window.alert(']
    assert browser_dialog_calls('<button onclick="confirm(\'x\')">Go</button>',html=True)==['confirm(']
