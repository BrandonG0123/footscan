"""Text files are read and written as UTF-8 on every system.

Python's default text encoding is the system's: UTF-8 on macOS and Linux, but the ANSI code page (cp1252) on
Windows, where writing a character like the √ in a repeatability report crashes and a ± lands as a byte that
UTF-8 readers can't decode. So every text read or write in src/ and scripts/ names its encoding, the studio's
service runs in UTF-8 mode (tests/test_review.py), and so does each 3-D build it starts (tests/test_server.py).
"""

import ast
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from test_repeatability import simulate

ROOT = Path(__file__).resolve().parent.parent
MODE = re.compile(r"^[rwax+tb]+$")


def _text_io_without_encoding(tree):
    """Calls that read or write text with the system's default encoding.

    read_text / write_text; the builtin open() and io.open() in a text mode; ``os.fdopen(fd, "w")``;
    tempfile's NamedTemporaryFile / TemporaryFile / SpooledTemporaryFile in a text mode; ``something.open()``
    with no arguments or only keyword ones (``Path.open()``, ``p.open(newline="")``), or whose first argument is
    a file mode (``p.open("w")``), but not one whose first argument is something else (so zipfile's
    ``z.open(name)`` or ``Image.open(path)`` aren't mistaken for files); and subprocess calls with text=True or
    universal_newlines=True.
    """
    def text_mode(mode, default_text):
        if mode is None:
            return default_text
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" not in mode.value

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        if "encoding" in kw:
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        owner = getattr(f.value, "id", None) if isinstance(f, ast.Attribute) else None
        if name in ("read_text", "write_text"):
            yield node
        elif name == "open" and (isinstance(f, ast.Name) or owner == "io"):
            if text_mode(kw.get("mode", node.args[1] if len(node.args) > 1 else None), True):
                yield node
        elif name == "fdopen":
            if text_mode(kw.get("mode", node.args[1] if len(node.args) > 1 else None), True):
                yield node
        elif name in ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"):
            # binary ("w+b") unless told otherwise
            if text_mode(kw.get("mode", node.args[0] if node.args else None), False):
                yield node
        elif name == "open":
            if not node.args:  # p.open(), p.open(newline=""), p.open(mode="w"): a Path, in text unless "b"
                if text_mode(kw.get("mode"), True):
                    yield node
                continue
            mode = node.args[0]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and MODE.match(mode.value) \
                    and "b" not in mode.value:
                yield node
        elif name in ("run", "Popen", "check_output") and any(
                isinstance(kw.get(k), ast.Constant) and kw[k].value is True for k in ("text", "universal_newlines")):
            yield node


def test_every_text_read_and_write_names_utf8():
    missing = [f"{p.relative_to(ROOT)}:{n.lineno}"
               for folder in ("src/footscan", "scripts")
               for p in sorted((ROOT / folder).rglob("*.py"))
               for n in _text_io_without_encoding(ast.parse(p.read_text(encoding="utf-8")))]
    assert not missing, "text I/O with the system's default encoding: " + ", ".join(missing)


def test_the_check_tells_files_from_other_things_called_open():
    calls = lambda src: len(list(_text_io_without_encoding(ast.parse(src))))  # noqa: E731
    assert calls("open(p)") == calls("open(p, 'w')") == calls("p.open('w')") == calls("p.read_text()") == 1
    assert calls("subprocess.run(c, text=True)") == 1
    assert calls("open(p, 'rb')") == calls("p.open('wb')") == calls("z.open('3D/3dmodel.model')") == 0
    assert calls("Image.open(path)") == calls("webbrowser.open(url)") == calls("subprocess.run(c)") == 0
    assert calls("open(p, encoding='utf-8')") == calls("subprocess.run(c, text=True, encoding='utf-8')") == 0
    # the Path forms of a text open, and the other ways to open a text file
    assert calls("p.open()") == calls("p.open(newline='')") == calls("p.open(mode='w')") == 1
    assert calls("io.open(p, 'w')") == calls("os.fdopen(fd, 'w')") == calls("tempfile.NamedTemporaryFile('w')") == 1
    assert calls("tempfile.NamedTemporaryFile(mode='w+')") == calls("tempfile.SpooledTemporaryFile(mode='w')") == 1
    assert calls("p.open(mode='rb')") == calls("os.fdopen(fd, 'wb')") == calls("tempfile.NamedTemporaryFile()") == 0
    assert calls("p.open(newline='', encoding='utf-8')") == calls("io.open(p, 'rb')") == 0


def _trials_rows():
    rows = simulate(np.random.default_rng(3), "nwb", 0.33, 0.002, 0.004, 0.002, 2, 5, 2)
    rows += simulate(np.random.default_rng(4), "fwb", 0.30, 0.002, 0.004, 0.002, 2, 5, 2)
    return [{**r, "load_kg": "" if r["load_kg"] is None else r["load_kg"]} for r in rows]


def _write_trials(path, rows, encoding="utf-8"):
    with path.open("w", newline="", encoding=encoding) as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_repeatability_report_is_written_where_the_default_encoding_is_not_utf8(tmp_path):
    """The Windows crash, reproduced here: the C locale with UTF-8 mode off makes Python's default ASCII."""
    trials = tmp_path / "trials.csv"
    _write_trials(trials, _trials_rows())
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    if os.name != "nt":
        probe = subprocess.run([sys.executable, "-c", "import locale; print(locale.getpreferredencoding(False))"],
                               env=env, capture_output=True, text=True, encoding="utf-8", check=True).stdout
        assert "utf" not in probe.lower(), f"this setup didn't make the default encoding non-UTF-8 ({probe})"
    out = tmp_path / "report.md"
    run = subprocess.run([sys.executable, "-m", "footscan.cli", "repeatability", str(trials), "-o", str(out)],
                         env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert run.returncode == 0, run.stderr[-2000:]
    text = out.read_text(encoding="utf-8")
    assert "Not a medical device" in text and "√" in text


def test_trials_saved_by_excel_read_the_same_as_plain_utf8(tmp_path):
    """Excel's "CSV UTF-8" starts with a byte-order mark; its plain "CSV" on Windows is cp1252."""
    from footscan.repeatability import read_rows

    rows = [{**r, "session": "Zoë-" + r["session"]} for r in _trials_rows()]  # a non-ASCII letter in a column
    plain, bom, ansi = tmp_path / "plain.csv", tmp_path / "bom.csv", tmp_path / "ansi.csv"
    _write_trials(plain, rows)
    _write_trials(bom, rows, "utf-8-sig")
    _write_trials(ansi, rows, "cp1252")
    assert bom.read_bytes().startswith(b"\xef\xbb\xbf")
    want = read_rows([plain])
    assert want[0]["foot"] == "right" and want[0]["session"] == "Zoë-S0"
    assert read_rows([bom]) == want  # the first column is "foot", not "﻿foot"
    assert read_rows([ansi]) == want


def test_a_damaged_file_that_is_not_utf8_is_skipped_like_bad_json(tmp_path):
    """A capture.json or a pick written by another tool in cp1252 doesn't take down the list it's in."""
    from footscan import landmarks
    from footscan.server import list_captures

    caps = tmp_path / "captures"
    for cid, raw in (("good", json.dumps({"id": "good", "created": "2026-11-03"}).encode()),
                     ("ansi", '{"id": "ansi", "note": "Zoë"}'.encode("cp1252"))):
        (caps / cid).mkdir(parents=True)
        (caps / cid / "capture.json").write_bytes(raw)
    assert [m["id"] for m in list_captures(caps)] == ["good"]

    folder = tmp_path / "scan"
    (folder / "landmarks").mkdir(parents=True)
    (folder / "landmarks" / "pick-1.json").write_bytes('{"note": "Zoë"}'.encode("cp1252"))
    assert landmarks.list_picks(folder) == []


def test_a_calipers_file_saved_with_a_byte_order_mark_is_read(tmp_path, capsys):
    """Notepad's "UTF-8 with BOM" and PowerShell 5's Set-Content -Encoding UTF8 start the file with one."""
    from footscan import cli

    cal = tmp_path / "calipers.json"
    cal.write_bytes(b"\xef\xbb\xbf" + json.dumps({"width_mm": 40.0}).encode())
    assert cli.main(["accuracy-mesh", str(tmp_path / "missing.obj"), "--calipers", str(cal)]) == 1
    assert "missing.obj" in capsys.readouterr().err
