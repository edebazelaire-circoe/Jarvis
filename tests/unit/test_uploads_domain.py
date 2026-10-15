"""Règles pures des fichiers téléversés (`jarvis/domain/uploads.py`, chat Slice 07, `docs/chat.md` › *Attachments*)."""

from __future__ import annotations

import pytest

from jarvis.domain import uploads as u
from jarvis.domain.artifacts import ArtifactKind, check_artifact_id, check_payload_name
from jarvis.domain.brain_context import MAX_BRAIN_ATTACHMENTS
from jarvis.domain.v2 import MAX_TURN_ATTACHMENTS

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def test_upload_is_a_kind_and_hard_bounds_agree():
    assert ArtifactKind.UPLOAD.value == "upload"
    assert u.HARD_CHAT_MAX_ATTACHMENTS == MAX_TURN_ATTACHMENTS == MAX_BRAIN_ATTACHMENTS


@pytest.mark.parametrize("env,expected,problems", [
    ({}, (64 * 1024 * 1024, 10), ()),
    ({"JARVIS_UPLOAD_MAX_BYTES": "1024", "JARVIS_CHAT_MAX_ATTACHMENTS": "3"}, (1024, 3), ()),
    ({"JARVIS_UPLOAD_MAX_BYTES": "-5"}, (64 * 1024 * 1024, 10), ("JARVIS_UPLOAD_MAX_BYTES",)),
    ({"JARVIS_UPLOAD_MAX_BYTES": "0"}, (64 * 1024 * 1024, 10), ("JARVIS_UPLOAD_MAX_BYTES",)),
    ({"JARVIS_UPLOAD_MAX_BYTES": "1e9"}, (64 * 1024 * 1024, 10), ("JARVIS_UPLOAD_MAX_BYTES",)),
    ({"JARVIS_CHAT_MAX_ATTACHMENTS": "65"}, (64 * 1024 * 1024, 10), ("JARVIS_CHAT_MAX_ATTACHMENTS",)),
    ({"JARVIS_CHAT_MAX_ATTACHMENTS": "64"}, (64 * 1024 * 1024, 64), ()),
])
def test_bounds_are_read_from_the_environment_and_never_beyond_the_hard_cap(env, expected, problems):
    bounds = u.upload_bounds(env)
    assert (bounds.max_bytes, bounds.max_attachments) == expected and bounds.problems == problems


def test_identity_is_deterministic_and_a_valid_artifact_id():
    first = u.upload_artifact_id("6f1c2d3e-aaaa-4bbb-8ccc-123456789abc")
    assert first == u.upload_artifact_id("6f1c2d3e-aaaa-4bbb-8ccc-123456789abc")
    assert first != u.upload_artifact_id("6f1c2d3e-aaaa-4bbb-8ccc-123456789abd")
    assert first.startswith("jart_up_") and len(first) == len("jart_up_") + 40
    check_artifact_id(first)


@pytest.mark.parametrize("bad", ["short", "../../../etc/passwd", "a" * 129, "id with space", "ïd-unicode-12345", "",
                                 None, 12345678, "-leading-dash"])
def test_client_upload_id_is_closed(bad):
    with pytest.raises(ValueError):
        u.upload_artifact_id(bad)


@pytest.mark.parametrize("head,whole,mime", [
    (PNG, True, "image/png"), (JPEG, True, "image/jpeg"), (b"GIF89a" + b"\x00" * 10, True, "image/gif"),
    (b"GIF87a" + b"\x00" * 10, True, "image/gif"), (WEBP, True, "image/webp"), (PDF, True, "application/pdf"),
    ("Bonjour, ça va ? ✓\n".encode(), True, "text/plain"),
    (b"PK\x03\x04" + b"\x00" * 20, True, "application/octet-stream"),   # zip
    (b"PK\x03\x04" + b"\x01" * 20, True, "application/octet-stream"),   # control bytes, valid UTF-8, no NUL
    (b"col1\tcol2\r\nx\x0cy\x1b[0m", True, "text/plain"),                 # tab, CRLF, form feed, ESC
    (b"text with a NUL\x00 inside", True, "application/octet-stream"),
    (b"\xff\xfe broken utf-8", True, "application/octet-stream"),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", True, "application/octet-stream"),  # RIFF but not WebP
    (b"MZ\x90\x00", True, "application/octet-stream"),  # exe
])
def test_sniffing_by_leading_bytes(head, whole, mime):
    assert u.sniff_mime(head, whole=whole) == mime


def test_a_multibyte_character_cut_by_the_head_is_text_only_when_the_file_goes_on():
    head = ("é" * (u.SNIFF_BYTES // 2)).encode()[: u.SNIFF_BYTES - 1]  # ends in the middle of "é"
    assert u.sniff_mime(head, whole=False) == "text/plain"
    assert u.sniff_mime(head, whole=True) == "application/octet-stream"


def test_the_declared_name_never_changes_the_sniffed_type_nor_the_payload_extension():
    # Une extension qui ment : un PDF nommé `.png`, un zip nommé `.pdf`, un texte nommé `.pdf`.
    assert u.payload_name_for("photo.png", u.sniff_mime(PDF, whole=True)) == "upload.pdf"
    assert u.payload_name_for("rapport.pdf", "application/octet-stream") == "upload.bin"
    assert u.payload_name_for("notes.pdf", "text/plain") == "upload.txt"
    assert u.payload_name_for("image.JPEG", "image/jpeg") == "upload.jpg"
    assert u.payload_name_for("notes.MD", "text/plain") == "upload.md"
    assert u.payload_name_for("archive.zip", "application/octet-stream") == "upload.zip"
    assert u.payload_name_for("sans_extension", "text/plain") == "upload.txt"
    assert u.payload_name_for("x.toolongext", "application/octet-stream") == "upload.bin"
    assert u.payload_name_for("x.t-x", "text/plain") == "upload.txt"
    for name in ("a.png", "..", "x.Exe", "CON.txt", "a." + "b" * 8):
        check_payload_name(u.payload_name_for(name, "application/octet-stream"))


@pytest.mark.parametrize("header,expected", [
    (None, "fichier"), ("", "fichier"),
    ("rapport%20final.pdf", "rapport final.pdf"),
    ("%C3%A9t%C3%A9%20%E2%9C%93.txt", "été ✓.txt"),                    # Unicode
    ("e%CC%81t%C3%A9.txt", "été.txt"),                                  # NFD → NFC
    ("..%2F..%2Fsecret.txt", "secret.txt"),                              # traversal
    ("C%3A%5CUsers%5Cx%5Cevil.txt", "evil.txt"),
    ("bad%00name%0A.txt", "badname.txt"),                                # NUL, newline
    ("invoice%E2%80%AEfdp.exe", "invoicefdp.exe"),                       # bidi override (RLO)
    ("CON.txt", "_CON.txt"), ("lpt1", "_lpt1"), ("nul.tar.gz", "_nul.tar.gz"),
    ("...", "fichier"), ("%20%20.", "fichier"),
])
def test_original_names_are_cleaned_for_display(header, expected):
    assert u.decode_upload_name(header) == expected


@pytest.mark.parametrize("header", ["%FF%FE.txt", "a" * 256, "%C3%A9" * 256, "é.txt", "x" * 4000])
def test_unreadable_or_too_long_names_are_refused(header):
    with pytest.raises(u.UploadNameError):
        u.decode_upload_name(header)


def test_a_name_of_exactly_255_characters_is_kept():
    assert u.decode_upload_name("%C3%A9" * 255) == "é" * 255


@pytest.mark.parametrize("agent,mime,readable", [
    ("claude", "application/pdf", True), ("claude", "image/png", True), ("claude", "image/webp", True),
    ("claude", "text/plain", True), ("claude", "application/octet-stream", False), ("claude", None, False),
    ("codex", "application/pdf", False), ("codex", "text/plain", False),
    ("unknown", "text/plain", False), (None, "text/plain", False),
])
def test_brain_readability_is_per_agent(agent, mime, readable):
    assert u.brain_readable(agent, mime) is readable
