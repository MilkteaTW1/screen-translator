"""The packaged app has no console: stdout/stderr are None, and the model download used to die with
"'NoneType' object has no attribute 'write'" from the library's progress bar."""
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_download_works_without_stdout_and_stderr(tmp_path):
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {SRC!r})
        sys.stdout = sys.stderr = None
        from screen_translator import speech
        calls = []
        import huggingface_hub
        def fake(repo, **kw):
            from tqdm.auto import tqdm  # what the real download does while it runs
            for _ in tqdm(range(3)):
                pass
            calls.append(repo)
        huggingface_hub.snapshot_download = fake
        speech.MODEL_DIR = __import__("pathlib").Path({str(tmp_path)!r})
        speech.download_model("tiny")
        print(calls, file=open({str(tmp_path / "out.txt")!r}, "w"))
    """)
    run = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-800:]
    assert "faster-whisper-tiny" in (tmp_path / "out.txt").read_text()
