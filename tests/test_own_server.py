import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from screen_translator.translator import Translator, server_translate_group


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers["Authorization"] == "Bearer secret"
        if self.mode == "denied":
            data, code = json.dumps({"error": {"message": "API key not valid. Please pass a valid API key."}}).encode(), 400
        else:
            lines = json.loads(body["messages"][0]["content"].split("\n", 1)[1])
            reply = json.dumps(["譯:" + s for s in lines] if self.mode == "ok" else ["only one"], ensure_ascii=False)
            data, code = json.dumps({"choices": [{"message": {"content": "```json\n" + reply + "\n```"}}]}).encode(), 200
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"kind": "openai", "url": f"http://127.0.0.1:{httpd.server_port}/v1", "key": "secret", "model": "m", "first": True}
    httpd.shutdown()


def test_an_openai_style_server_translates_lines_one_for_one(server):
    _Handler.mode = "ok"
    assert server_translate_group(server, ["Hello there", "Good bye"], "en", "zh-TW") == ["譯:Hello there", "譯:Good bye"]


def test_the_translator_uses_the_server_first_and_says_nothing_is_wrong(server):
    _Handler.mode = "ok"
    tr = Translator()
    tr.server = server
    tr.google = True  # must not be asked: the server answers everything
    tr._google_many = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Google was asked"))
    assert tr.translate("Hello there my friend", "en", "zh-TW", "en", [], False, False) == "譯:Hello there my friend"
    assert tr.engine == "server" and tr.server_error is None


def test_a_refusal_from_the_server_is_kept_so_the_user_can_read_it(server):
    _Handler.mode = "denied"
    tr = Translator()
    tr.server = server
    tr._argos_many = lambda texts, s, d: [None] * len(texts)
    tr.translate("Hello there my friend", "en", "zh-TW", "en", [], False, False)
    assert "HTTP 400" in tr.server_error and "valid API key" in tr.server_error


def test_an_answer_with_the_wrong_number_of_lines_is_reported(server):
    _Handler.mode = "short"
    tr = Translator()
    tr.server = server
    tr._argos_many = lambda texts, s, d: [None] * len(texts)
    tr.translate_many(["Hello there my friend", "Another longer line here"], "en", "zh-TW", "en", [], False, False)
    assert "one line for each" in tr.server_error
