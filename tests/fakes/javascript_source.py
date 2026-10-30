"""Shared static browser-call guard; production comment scanner, stdlib HTML reader."""
from html.parser import HTMLParser
import re

from jarvis.domain.remotion_import import strip_comments


_DIALOG_CALL = re.compile(r"(?<![\w.])(?:(?:window|globalThis|self)\s*\.\s*)?(?:alert|confirm|prompt)\s*\((?![^()]*\)\s*\{)")


class _InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.in_script = False
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.in_script = True
        self.sources.extend(value for name, value in attrs if name.startswith('on') and value)

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.sources.append(data)


def browser_dialog_calls(source: str, *, html: bool = False) -> list[str]:
    """Ignore explanatory comments, retain executable calls (including frame source strings).

    Method declarations such as pending.confirm(id, token) remain allowed. This
    is the existing source conformance guard, not a JavaScript security parser.
    """
    if html:
        parser = _InlineScripts()
        parser.feed(source)
        sources = parser.sources
    else:
        sources = [source]
    return [match.group() for text in sources for match in _DIALOG_CALL.finditer(strip_comments(text))]
