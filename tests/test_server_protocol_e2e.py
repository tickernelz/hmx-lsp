from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "corpus")
MODULE = os.path.join("hmx", "module", "basic", "demo")
TIMEOUT = 20.0


def _pump(stream, sink: queue.Queue) -> None:
    try:
        while True:
            length = None
            while True:
                line = stream.readline()
                if not line:
                    sink.put(None)
                    return
                line = line.strip()
                if not line:
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1])
            if length is None:
                sink.put(None)
                return
            sink.put(json.loads(stream.read(length)))
    except Exception:
        sink.put(None)


class Client:
    def __init__(self, root: str, index_delay: str = "0"):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "hmx_ls.cli", "serve"],
            cwd=REPO,
            env={**os.environ, "PYTHONPATH": REPO, "PYTHONUNBUFFERED": "1",
                 "HMX_LSP_INDEX_DELAY": index_delay},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.root = root
        self.next_id = 1
        self.inbox: queue.Queue = queue.Queue()
        self.reader = threading.Thread(
            target=_pump, args=(self.proc.stdout, self.inbox), daemon=True)
        self.reader.start()

    def send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
        self.proc.stdin.flush()

    def take(self) -> dict | None:
        try:
            return self.inbox.get(timeout=TIMEOUT)
        except queue.Empty:
            return None

    def request(self, method: str, params: dict) -> dict:
        message_id = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})
        while True:
            message = self.take()
            if message is None:
                raise AssertionError(f"no reply to {method}: {self.stderr()}")
            if message.get("id") == message_id:
                return message

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def await_notification(self, method: str) -> dict:
        while True:
            message = self.take()
            if message is None:
                raise AssertionError(f"never received {method}: {self.stderr()}")
            if message.get("method") == method:
                return message["params"]

    def stderr(self) -> str:
        self.proc.kill()
        try:
            return self.proc.stderr.read().decode(errors="replace")[-600:]
        except Exception:
            return "(no stderr)"

    def close(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass


def _session(tmp_path, index_delay="0"):
    root = tmp_path / "corpus"
    shutil.copytree(FIXTURE, root)
    session = Client(str(root), index_delay=index_delay)
    reply = session.request("initialize", {
        "processId": os.getpid(),
        "rootUri": root.as_uri(),
        "capabilities": {"textDocument": {"publishDiagnostics": {}}},
        "workspaceFolders": [{"uri": root.as_uri(), "name": "corpus"}],
    })
    assert reply["result"]["capabilities"]
    session.notify("initialized", {})
    return session


@pytest.fixture
def slow_client(tmp_path):
    session = _session(tmp_path, index_delay="3")
    yield session
    session.close()


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(FIXTURE, root)
    session = Client(str(root))
    reply = session.request("initialize", {
        "processId": os.getpid(),
        "rootUri": root.as_uri(),
        "capabilities": {"textDocument": {"publishDiagnostics": {}}},
        "workspaceFolders": [{"uri": root.as_uri(), "name": "corpus"}],
    })
    assert reply["result"]["capabilities"]
    session.notify("initialized", {})
    yield session
    session.close()


def _open(session, rel, language):
    path = os.path.join(session.root, rel)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    uri = "file://" + path
    session.notify("textDocument/didOpen", {
        "textDocument": {"uri": uri, "languageId": language, "version": 1, "text": text},
    })
    return uri


def test_opening_a_view_publishes_diagnostics(client):
    uri = _open(client, os.path.join(MODULE, "views", "order.xml"), "xml")
    params = client.await_notification("textDocument/publishDiagnostics")
    assert params["uri"] == uri
    messages = [d["message"] for d in params["diagnostics"]]
    assert [m for m in messages if "ghostfield" in m]


def test_opening_a_manifest_publishes_the_dead_asset(client):
    _open(client, os.path.join(MODULE, "__hmx__.py"), "python")
    params = client.await_notification("textDocument/publishDiagnostics")
    assert {d["code"] for d in params["diagnostics"]} == {"hmx-dead-asset"}


def test_a_clean_document_publishes_an_empty_list(client):
    uri = _open(client, os.path.join(MODULE, "models", "order.py"), "python")
    params = client.await_notification("textDocument/publishDiagnostics")
    assert params["uri"] == uri
    assert params["diagnostics"] == []


def test_hover_answers_over_the_wire(client):
    uri = _open(client, os.path.join(MODULE, "views", "order.xml"), "xml")
    client.await_notification("textDocument/publishDiagnostics")
    with open(os.path.join(client.root, MODULE, "views", "order.xml"), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    line = next(i for i, text in enumerate(lines) if 'name="partner"' in text)
    reply = client.request("textDocument/hover", {
        "textDocument": {"uri": uri},
        "position": {"line": line, "character": lines[line].index("partner") + 2},
    })
    assert "error" not in reply


def test_a_document_opened_before_the_index_is_ready_still_gets_diagnostics(slow_client):
    uri = _open(slow_client, os.path.join(MODULE, "views", "order.xml"), "xml")
    params = slow_client.await_notification("textDocument/publishDiagnostics")
    assert params["uri"] == uri
    messages = [d["message"] for d in params["diagnostics"]]
    assert [m for m in messages if "ghostfield" in m]


def test_the_late_publish_covers_every_open_document(slow_client):
    view = _open(slow_client, os.path.join(MODULE, "views", "order.xml"), "xml")
    manifest = _open(slow_client, os.path.join(MODULE, "__hmx__.py"), "python")
    seen: dict[str, list] = {}
    while set(seen) < {view, manifest}:
        params = slow_client.await_notification("textDocument/publishDiagnostics")
        seen[params["uri"]] = params["diagnostics"]
    assert [d for d in seen[view] if "ghostfield" in d["message"]]
    assert {d["code"] for d in seen[manifest]} == {"hmx-dead-asset"}
