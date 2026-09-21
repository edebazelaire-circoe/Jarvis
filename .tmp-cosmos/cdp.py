#!/usr/bin/env python3
"""Client Chrome DevTools Protocol minimal, sans dependance.

Handshake WebSocket a la main (socket + base64), trames texte masquees cote
client. Assez pour: naviguer, evaluer du JS, capturer un PNG.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class WS:
    def __init__(self, url: str, timeout: float = 30.0):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=10)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake ferme")
            buf += chunk
        head, _, tail = buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError("handshake refuse: %r" % head[:200])
        self.buf = tail
        self._id = 0

    # ---- trames
    def _send(self, payload: bytes, opcode: int = 0x1) -> None:
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket ferme")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv_frame(self) -> tuple[int, bytes]:
        b0, b1 = self._read(2)
        opcode = b0 & 0x0F
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        if b1 & 0x80:
            mask = self._read(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._read(length)))
        else:
            data = self._read(length)
        return opcode, data

    def recv_json(self) -> dict:
        while True:
            opcode, data = self._recv_frame()
            if opcode == 0x9:  # ping
                self._send(data, 0xA)
                continue
            if opcode in (0x1, 0x2):
                return json.loads(data.decode("utf-8"))
            if opcode == 0x8:
                raise RuntimeError("ferme par le pair")

    def call(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        self._id += 1
        mid = self._id
        self._send(json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.recv_json()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self) -> None:
        try:
            self._send(b"", 0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def launch(port: int, profile: Path, width: int = 1600, height: int = 1000):
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            CHROME, "--headless=new", "--disable-gpu",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--force-device-scale-factor=1",
            "--disable-features=Translate,MediaRouter",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
                return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("chrome n'a pas ouvert son port de debug")


def page_ws(port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        tabs = json.loads(r.read().decode())
    for tab in tabs:
        if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
            return tab["webSocketDebuggerUrl"]
    raise RuntimeError("aucune page")


def evaluate(ws: WS, expression: str, timeout: float = 60.0):
    result = ws.call(
        "Runtime.evaluate",
        {"expression": expression, "awaitPromise": True, "returnByValue": True},
        timeout=timeout,
    )
    if result.get("exceptionDetails"):
        raise RuntimeError(json.dumps(result["exceptionDetails"])[:800])
    return result.get("result", {}).get("value")


def screenshot(ws: WS, path: Path) -> None:
    data = ws.call("Page.captureScreenshot", {"format": "png"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data["data"]))
