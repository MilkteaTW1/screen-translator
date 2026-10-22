import http.server
import json
import threading

import pytest

from screen_translator import llm_setup


@pytest.fixture
def fake_ollama():
    """A tiny stand-in for the Ollama API: /api/tags lists models, /api/pull streams progress."""
    state = {"models": [], "pulls": 0, "fail": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"models": [{"name": m} for m in state["models"]]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            model = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["model"]
            state["pulls"] += 1
            self.send_response(200)
            self.end_headers()
            if state["fail"]:
                self.wfile.write(b'{"error": "no space left on device"}\n')
                return
            for done in (0, 50, 100):
                self.wfile.write(json.dumps({"status": "pulling", "total": 100, "completed": done}).encode() + b"\n")
            state["models"].append(model + ":latest")
            self.wfile.write(b'{"status": "success"}\n')

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1", state
    server.shutdown()


def test_setup_pulls_a_missing_model_and_reports_progress(fake_ollama):
    url, state = fake_ollama
    seen = []
    llm_setup.setup(url, "qwen2.5:7b", seen.append)
    assert state["pulls"] == 1 and llm_setup.has_model(url, "qwen2.5:7b")
    assert any("50%" in s for s in seen)


def test_setup_does_nothing_when_the_model_is_there(fake_ollama):
    url, state = fake_ollama
    state["models"].append("qwen2.5:7b")
    llm_setup.setup(url, "qwen2.5:7b", lambda s: None)
    assert state["pulls"] == 0


def test_a_pull_error_is_raised(fake_ollama):
    url, state = fake_ollama
    state["fail"] = True
    with pytest.raises(RuntimeError, match="no space"):
        llm_setup.setup(url, "qwen2.5:7b", lambda s: None)


def test_only_local_servers_are_set_up_automatically():
    assert llm_setup.is_local("http://localhost:11434/v1")
    assert not llm_setup.is_local("http://192.168.1.5:11434/v1")
