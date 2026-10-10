"""Origine, archive et licence d'un modèle Remotion amont, et le téléchargeur HTTPS (Slice 18).

Pur et sans réseau : le téléchargeur réel est exercé contre un faux `HTTPSConnection` qui rejoue des réponses scriptées.
Contrat : `docs/remotion-import.md` §2-4 ; code : `jarvis/domain/remotion_upstream.py`, `jarvis/adapters/https_upstream_fetcher.py`.
"""

from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from jarvis.adapters import https_upstream_fetcher as fetcher_module
from jarvis.adapters.fake_upstream_fetcher import FakeUpstreamFetcher
from jarvis.adapters.https_upstream_fetcher import HttpsUpstreamFetcher
from jarvis.domain import remotion_upstream as up
from jarvis.domain.remotion_upstream import (
    UpstreamErrorCode as E, UpstreamOrigin, UpstreamRefusal, classify_licence, normalise_owners, parse_origin, read_tar_source,
    redirect_refusal,
)
from tests.fakes.upstream_archive import GPL, MIT, REMOTION_LICENCE, SHA, good_project, link, make_tarball

OWNERS = ("remotion-dev", "someone")
ORIGIN = UpstreamOrigin("remotion-dev", "demo", SHA)


def refusal(call, *args, **kwargs) -> UpstreamRefusal:
    with pytest.raises(UpstreamRefusal) as caught:
        call(*args, **kwargs)
    return caught.value


# ------------------------------------------------------------------ origine

def test_a_pinned_commit_of_an_allowlisted_owner_is_accepted_and_the_download_url_is_built_not_copied():
    origin = parse_origin("https://github.com/Remotion-Dev/demo.git", SHA, OWNERS)
    assert origin == UpstreamOrigin("Remotion-Dev", "demo", SHA)
    assert origin.archive_url == f"https://codeload.github.com/Remotion-Dev/demo/tar.gz/{SHA}"
    assert origin.repository_url == "https://github.com/Remotion-Dev/demo"


@pytest.mark.parametrize("url, code", [
    ("http://github.com/remotion-dev/demo", E.ORIGIN_INVALID),
    ("ftp://github.com/remotion-dev/demo", E.ORIGIN_INVALID),
    ("https://gitlab.com/remotion-dev/demo", E.ORIGIN_NOT_ALLOWED),
    ("https://raw.githubusercontent.com/remotion-dev/demo/main/x.zip", E.ORIGIN_NOT_ALLOWED),
    ("https://github.com.evil.example/remotion-dev/demo", E.ORIGIN_NOT_ALLOWED),
    ("https://www.github.com/remotion-dev/demo", E.ORIGIN_NOT_ALLOWED),
    ("https://user:pw@github.com/remotion-dev/demo", E.ORIGIN_INVALID),
    ("https://github.com:8443/remotion-dev/demo", E.ORIGIN_INVALID),
    ("https://github.com/remotion-dev/demo?x=1", E.ORIGIN_INVALID),
    ("https://github.com/remotion-dev/demo#frag", E.ORIGIN_INVALID),
    ("https://github.com/remotion-dev", E.ORIGIN_INVALID),
    ("https://github.com/remotion-dev/demo/tree/main", E.ORIGIN_INVALID),
    ("https://github.com/evil-org/demo", E.ORIGIN_NOT_ALLOWED),
    ("https://github.com/remotion-dev/../demo", E.ORIGIN_INVALID),
    ("https://github.com/remotion-dev/demo extra", E.ORIGIN_INVALID),
    ("", E.ORIGIN_INVALID), (None, E.ORIGIN_INVALID), (5, E.ORIGIN_INVALID),
])
def test_every_unlisted_or_malformed_origin_is_refused_with_a_typed_code(url, code):
    assert refusal(parse_origin, url, SHA, OWNERS).code == code


@pytest.mark.parametrize("commit", ["main", "v4.0.0", "a1b2c3", SHA.upper(), SHA[:-1], SHA + "0", "", None, 123])
def test_only_a_full_lowercase_sha_pins_a_commit(commit):
    assert refusal(parse_origin, "https://github.com/remotion-dev/demo", commit, OWNERS).code == E.COMMIT_NOT_PINNED


def test_the_allowlist_is_settings_data_and_tolerant():
    assert normalise_owners(None) == ("remotion-dev",) and normalise_owners("x") == ("remotion-dev",) and normalise_owners([]) == ("remotion-dev",)
    assert normalise_owners(["Someone", "someone", "bad owner!", 5, "a--b"]) == ("someone", "a--b")
    assert len(normalise_owners([f"o{i}" for i in range(100)])) == up.MAX_ALLOWED_OWNERS
    # les hôtes ne se règlent pas : un propriétaire accepté ne rend pas un autre hôte acceptable
    assert refusal(parse_origin, "https://gitlab.com/someone/demo", SHA, ("someone",)).code == E.ORIGIN_NOT_ALLOWED


@pytest.mark.parametrize("location, ok", [
    (f"https://codeload.github.com/remotion-dev/demo/tar.gz/{SHA}", True),
    ("https://github.com/remotion-dev/demo/archive/x.tar.gz", True),
    ("https://CODELOAD.github.com/Remotion-Dev/Demo/tar.gz/x", True),
    ("http://codeload.github.com/remotion-dev/demo/tar.gz/x", False),
    ("https://evil.example/remotion-dev/demo/tar.gz/x", False),
    ("https://codeload.github.com.evil.example/remotion-dev/demo/x", False),
    ("https://codeload.github.com/remotion-dev/other/tar.gz/x", False),
    ("https://codeload.github.com/other/demo/tar.gz/x", False),
    ("https://user@codeload.github.com/remotion-dev/demo/x", False),
    ("https://codeload.github.com:444/remotion-dev/demo/x", False),
    ("https://raw.githubusercontent.com/remotion-dev/demo/main/x", False),
    ("file:///etc/passwd", False),
])
def test_a_redirect_must_stay_on_github_https_and_on_the_same_repository(location, ok):
    assert (redirect_refusal(ORIGIN, location) is None) is ok


# ------------------------------------------------------------------ archive

def reader(select=None):
    return lambda data, **kw: read_tar_source(data, expected_commit=kw.pop("commit", SHA), select=select or (lambda p, s: 1 << 20))


def test_a_codeload_archive_is_read_in_memory_with_the_attested_commit():
    read = read_tar_source(make_tarball(good_project()), expected_commit=SHA, select=lambda p, s: 1 << 20 if p.startswith("src/") else None)
    assert read.commit == SHA and "src/Root.tsx" in read.files and "public/logo.png" in read.paths and "public/logo.png" not in read.files
    assert "LICENSE" in read.paths and read.entries > 10


def test_unselected_and_oversize_files_are_not_read():
    read = read_tar_source(make_tarball(good_project()), expected_commit=SHA, select=lambda p, s: 10 if p == "src/Root.tsx" else None)
    assert read.files == {} and read.oversize == {"src/Root.tsx"}


@pytest.mark.parametrize("name", ["../evil.tsx", "demo/../../evil.tsx", "/abs/evil", "C:/evil", "a\\b.tsx", "a//b.tsx", "a/./b"])
def test_a_path_that_escapes_the_root_refuses_the_whole_archive(name):
    data = make_tarball({"src/ok.ts": "x"}, extra_data={name if name.startswith(("/", "C:", "..")) else f"demo-{SHA}/{name}": b"x"})
    assert refusal(read_tar_source, data, expected_commit=SHA, select=lambda p, s: 1024).code == E.ARCHIVE_PATH


@pytest.mark.parametrize("hard", [False, True])
def test_a_symlink_or_hardlink_refuses_the_archive_even_outside_the_selection(hard):
    data = make_tarball({"src/a.ts": "x"}, extra=[link(f"demo-{SHA}/src/evil.ts", "/etc/passwd", hard=hard)])
    assert refusal(read_tar_source, data, expected_commit=SHA, select=lambda p, s: None).code == E.ARCHIVE_LINK


def test_a_device_member_refuses_the_archive():
    info = tarfile.TarInfo(f"demo-{SHA}/dev")
    info.type = tarfile.CHRTYPE
    assert refusal(read_tar_source, make_tarball({"src/a.ts": "x"}, extra=[info]), expected_commit=SHA, select=lambda p, s: None).code == E.ARCHIVE_LINK


def test_duplicates_including_by_case_and_second_roots_are_refused():
    data = make_tarball({"src/A.ts": "1"}, extra_data={f"demo-{SHA}/src/a.ts": b"2"})
    assert refusal(read_tar_source, data, expected_commit=SHA, select=lambda p, s: 1024).code == E.ARCHIVE_DUPLICATE
    data = make_tarball({"src/A.ts": "1"}, extra_data={"other-root/src/b.ts": b"2"})
    assert refusal(read_tar_source, data, expected_commit=SHA, select=lambda p, s: 1024).code == E.ARCHIVE_PATH


def test_the_pinned_commit_must_be_attested_by_the_archive_itself():
    other = "b" * 40
    assert refusal(read_tar_source, make_tarball({"src/a.ts": "x"}, comment=other), expected_commit=SHA, select=lambda p, s: 1).code == E.ARCHIVE_COMMIT_MISMATCH
    missing = refusal(read_tar_source, make_tarball({"src/a.ts": "x"}, comment=""), expected_commit=SHA, select=lambda p, s: 1)
    assert missing.code == E.ARCHIVE_COMMIT_MISMATCH and "does not attest" in missing.message


def test_a_decompression_bomb_is_cut_at_the_unpacked_limit(monkeypatch):
    monkeypatch.setattr(up, "MAX_UNPACKED_BYTES", 64 * 1024)
    data = make_tarball({"src/big.ts": "a" * (512 * 1024)})
    assert len(data) < 5000  # la bombe est minuscule compressée
    assert refusal(read_tar_source, data, expected_commit=SHA, select=lambda p, s: None).code == E.ARCHIVE_TOO_LARGE


def test_entry_count_download_size_and_garbage_are_bounded(monkeypatch):
    monkeypatch.setattr(up, "MAX_ENTRIES", 5)
    many = make_tarball({f"src/f{i}.ts": "x" for i in range(10)})
    assert refusal(read_tar_source, many, expected_commit=SHA, select=lambda p, s: None).code == E.ARCHIVE_TOO_LARGE
    monkeypatch.setattr(up, "MAX_DOWNLOAD_BYTES", 100)
    assert refusal(read_tar_source, make_tarball(good_project()), expected_commit=SHA, select=lambda p, s: None).code == E.FETCH_TOO_LARGE
    monkeypatch.undo()
    assert refusal(read_tar_source, b"not an archive at all", expected_commit=SHA, select=lambda p, s: None).code == E.ARCHIVE_INVALID
    truncated = make_tarball(good_project())[:-40]
    assert refusal(read_tar_source, truncated, expected_commit=SHA, select=lambda p, s: 1 << 20).code in (E.ARCHIVE_INVALID,)
    plain_tar = io.BytesIO()
    with tarfile.open(fileobj=plain_tar, mode="w") as archive:
        archive.addfile(tarfile.TarInfo("x"), io.BytesIO())
    assert refusal(read_tar_source, gzip.compress(b"x" * 100), expected_commit=SHA, select=lambda p, s: None).code == E.ARCHIVE_INVALID


# ------------------------------------------------------------------ licence

def file_licence(text: str, package: dict | None = None):
    return classify_licence({"LICENSE": text.encode()}, package)


@pytest.mark.parametrize("text, spdx", [
    (MIT, "MIT"),
    ("Apache License\nVersion 2.0, January 2004\n http://www.apache.org/licenses/\n", "Apache-2.0"),
    ("Redistribution and use in source and binary forms, with or without modification, are permitted provided that: "
     "Neither the name of the copyright holder nor the names of its contributors may be used", "BSD-3-Clause"),
    ("Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following", "BSD-2-Clause"),
    ("Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, "
     "provided that the above copyright notice and this permission notice appear in all copies.", "ISC"),
    ("This is free and unencumbered software released into the public domain.", "Unlicense"),
])
def test_a_reviewed_licence_text_is_identified_as_its_spdx_id(text, spdx):
    assert file_licence(text).spdx == spdx and spdx in up.PERMITTED_LICENCES


@pytest.mark.parametrize("text, code", [
    (GPL, E.LICENSE_RESTRICTED),
    ("GNU AFFERO GENERAL PUBLIC LICENSE Version 3", E.LICENSE_RESTRICTED),
    ("GNU Lesser General Public License", E.LICENSE_RESTRICTED),
    ("Mozilla Public License Version 2.0", E.LICENSE_RESTRICTED),
    ("Creative Commons Attribution-NonCommercial 4.0", E.LICENSE_RESTRICTED),
    ("Free for non-commercial use only.", E.LICENSE_RESTRICTED),
    (REMOTION_LICENCE, E.LICENSE_RESTRICTED),
    ("All rights reserved. Do whatever you want, probably.", E.LICENSE_UNKNOWN),
])
def test_copyleft_commercial_remotion_and_unknown_licences_are_refused(text, code):
    assert refusal(file_licence, text).code == code


def test_without_a_licence_file_only_a_permitted_package_json_declaration_counts():
    assert classify_licence({}, {"license": "MIT"}) == up.Licence("MIT", "package.json")
    assert refusal(classify_licence, {}, {}).code == E.LICENSE_MISSING
    assert refusal(classify_licence, {}, None).code == E.LICENSE_MISSING
    assert refusal(classify_licence, {}, {"license": "UNLICENSED"}).code == E.LICENSE_UNLICENSED
    assert refusal(classify_licence, {}, {"license": "GPL-3.0-only"}).code == E.LICENSE_RESTRICTED
    assert refusal(classify_licence, {}, {"license": "Proprietary-X"}).code == E.LICENSE_UNKNOWN
    assert refusal(classify_licence, {}, {"license": "SEE LICENSE IN LICENSE"}).code == E.LICENSE_UNLICENSED


def test_a_file_and_a_package_json_that_disagree_are_refused_and_the_remotion_licence_is_never_the_template_one():
    assert refusal(file_licence, MIT, {"license": "Apache-2.0"}).code == E.LICENSE_CONFLICT
    assert file_licence(MIT, {"license": "MIT"}).source == "file"
    # la licence de Remotion est une constante à part : jamais déduite du dépôt
    assert up.REMOTION_RUNTIME_LICENCE.startswith("Remotion License") and "Remotion" not in up.PERMITTED_LICENCES


def test_only_a_root_level_licence_file_name_is_a_licence_file():
    assert all(up.is_licence_file(name) for name in ("LICENSE", "LICENSE.md", "license.txt", "COPYING", "UNLICENSE"))
    assert not up.is_licence_file("node_modules/x/LICENSE") and not up.is_licence_file("src/LICENSE")


# ------------------------------------------------------------------ téléchargeur HTTPS (faux HTTPSConnection)

class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, chunks=None, error: Exception | None = None):
        self.status, self._headers, self._error = status, headers or {}, error
        self._chunks = list(chunks if chunks is not None else ([body] if body else []))

    def getheader(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, size=-1):
        if self._error:
            raise self._error
        return self._chunks.pop(0) if self._chunks else b""


class Script:
    """Rejoue des réponses dans l'ordre et note chaque connexion (hôte, chemin) : un refus ne doit rien ouvrir de plus."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def factory(self, host, port, timeout=None, context=None):
        script = self

        class Conn:
            def request(self, method, path, headers=None):
                script.requests.append((host, port, path, dict(headers or {})))

            def getresponse(self):
                item = script.responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            def close(self):
                pass

        return Conn()


def run_fetch(monkeypatch, *responses, clock=None, deadline=30.0):
    script = Script(*responses)
    monkeypatch.setattr(fetcher_module.http.client, "HTTPSConnection", script.factory)
    kwargs = {"clock": clock} if clock else {}
    return HttpsUpstreamFetcher(deadline_s=deadline, **kwargs).fetch(ORIGIN), script


def test_the_real_fetcher_asks_codeload_over_https_port_443_with_no_credentials(monkeypatch):
    fetched, script = run_fetch(monkeypatch, FakeResponse(200, b"ARCHIVE"))
    assert fetched.data == b"ARCHIVE" and fetched.redirects == 0
    host, port, path, headers = script.requests[0]
    assert (host, port, path) == ("codeload.github.com", 443, f"/remotion-dev/demo/tar.gz/{SHA}")
    assert "Authorization" not in headers and headers["Accept-Encoding"] == "identity"


def test_a_redirect_inside_github_and_the_same_repo_is_followed_at_most_three_times(monkeypatch):
    hop = {"Location": f"https://codeload.github.com/remotion-dev/demo/tar.gz/{SHA}"}
    fetched, script = run_fetch(monkeypatch, FakeResponse(302, headers=hop), FakeResponse(301, headers=hop), FakeResponse(200, b"OK"))
    assert fetched.redirects == 2 and len(script.requests) == 3
    error = refusal(lambda: run_fetch(monkeypatch, *[FakeResponse(302, headers=hop)] * 4))
    assert error.code == E.REDIRECT_REFUSED and "more than" in error.message


@pytest.mark.parametrize("location", [
    "https://evil.example/remotion-dev/demo/tar.gz/x", "http://codeload.github.com/remotion-dev/demo/tar.gz/x",
    "https://codeload.github.com/other/repo/tar.gz/x", "https://user@codeload.github.com/remotion-dev/demo/tar.gz/x", "",
])
def test_a_hostile_redirect_is_refused_before_any_second_connection(monkeypatch, location):
    script = Script(FakeResponse(302, headers={"Location": location}), FakeResponse(200, b"MUST NOT BE FETCHED"))
    monkeypatch.setattr(fetcher_module.http.client, "HTTPSConnection", script.factory)
    error = refusal(HttpsUpstreamFetcher().fetch, ORIGIN)
    assert error.code == E.REDIRECT_REFUSED and len(script.requests) == 1


def test_http_errors_timeouts_and_network_failures_are_typed(monkeypatch):
    assert refusal(lambda: run_fetch(monkeypatch, FakeResponse(404))).code == E.FETCH_FAILED
    assert "404" in refusal(lambda: run_fetch(monkeypatch, FakeResponse(404))).message
    assert refusal(lambda: run_fetch(monkeypatch, FakeResponse(500))).code == E.FETCH_FAILED
    assert refusal(lambda: run_fetch(monkeypatch, TimeoutError())).code == E.FETCH_TIMEOUT
    assert refusal(lambda: run_fetch(monkeypatch, ConnectionResetError())).code == E.FETCH_FAILED
    assert refusal(lambda: run_fetch(monkeypatch, FakeResponse(200, error=OSError("boom")))).code == E.FETCH_FAILED


def test_the_download_is_bounded_by_size_declared_or_streamed_and_by_a_global_deadline(monkeypatch):
    big = str(up.MAX_DOWNLOAD_BYTES + 1)
    assert refusal(lambda: run_fetch(monkeypatch, FakeResponse(200, headers={"Content-Length": big}))).code == E.FETCH_TOO_LARGE
    streamed = [b"x" * (1024 * 1024)] * 13
    assert refusal(lambda: run_fetch(monkeypatch, FakeResponse(200, chunks=streamed))).code == E.FETCH_TOO_LARGE
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    error = refusal(lambda: run_fetch(monkeypatch, FakeResponse(200, chunks=[b"a", b"b"]), clock=lambda: next(ticks), deadline=5.0))
    assert error.code == E.FETCH_TIMEOUT


def test_the_fake_fetcher_records_every_request():
    fake = FakeUpstreamFetcher({ORIGIN.archive_url: b"x"})
    assert fake.fetch(ORIGIN).data == b"x" and fake.requests == [ORIGIN.archive_url]
