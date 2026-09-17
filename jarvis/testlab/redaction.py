"""Identifying-text redaction shared by Test Lab capturers (URLs, SSH remotes, email addresses).

Binding contract: `docs/testlab.md` ("Capture", "DiagnosticBundle"). Pure: no
I/O, no clock. Moved out of `capture.py` in Slice 03 so the pure DiagnosticBundle
builder can redact public conversation text with exactly the rule the
configuration snapshot uses (`capture.py` re-exports both functions).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

REDACTED = "<redacted>"
EMAIL_PLACEHOLDER = "<email>"

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+")
#: Prose punctuation that ends a sentence after a URL (`Tu connais http://site.fr?`), never part of it.
_URL_TRAILING_PROSE = ".,;:!?)]}"
#: scp-like SSH remote `user@host:path` (`git@github.com:org/repo.git`).
_SSH_REMOTE = re.compile(r"(?<![\w.%+/@-])[A-Za-z0-9._-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*):(?!//)(?=[A-Za-z0-9._~/-])")
_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")


def redact_urls(text: str) -> tuple[str, int]:
    """Strip userinfo, query and fragment from every URL in `text`: `scheme://host[:port]/path` stays.

    Credentials hide there under harmless keys (`https://u:p@host/x?token=abc`).
    Trailing prose punctuation stays prose. A secret embedded in the URL *path*
    (webhook tokens such as `/services/T000/B000/<token>`) is not detected: such
    settings must be caught by their name. Returns the text and how many URLs
    were changed.
    """
    changed = 0

    def clean(match: re.Match[str]) -> str:
        nonlocal changed
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _URL_TRAILING_PROSE and "://" in url[:-1] and not url[:-1].endswith("://"):
            trailing = url[-1] + trailing
            url = url[:-1]
        try:
            parts = urlsplit(url)
        except ValueError:
            changed += 1
            return url.split("://", 1)[0] + "://" + REDACTED + trailing
        if "@" not in parts.netloc and not parts.query and not parts.fragment and "?" not in url and "#" not in url:
            return url + trailing
        changed += 1
        return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}{parts.path}{trailing}"

    return _URL.sub(clean, text), changed


def redact_identifying_text(text: str) -> tuple[str, int]:
    """URLs through `redact_urls`, then scp-like SSH remotes lose their user part
    (`git@github.com:org/repo.git` -> `github.com:org/repo.git`, like URL userinfo),
    then every email address becomes `<email>`. Returns the text and the change count.
    """
    text, changed = redact_urls(text)
    text, remotes = _SSH_REMOTE.subn(lambda match: f"{match.group(1)}:", text)
    text, emails = _EMAIL.subn(EMAIL_PLACEHOLDER, text)
    return text, changed + remotes + emails
