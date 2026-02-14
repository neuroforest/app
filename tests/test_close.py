"""
Tests for bin/close.py

Logic:
    Reads PID from build/nw.pid and terminates the process.
    Removes PID file after closing. Handles missing PID file and stale PIDs.
"""

import importlib.util
import os
import sys

import pytest

from neuro.utils import internal_utils

APP_PATH = internal_utils.get_path("app")


# -- Load module --

@pytest.fixture(scope="session")
def close_mod():
    spec = importlib.util.spec_from_file_location(
        "close",
        os.path.join(APP_PATH, "bin/close.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["close"] = mod
    spec.loader.exec_module(mod)
    return mod


# -- Tests --

class TestClose:
    """close() reads PID file from build dir and terminates the process."""

    def test_no_pid_file(self, close_mod, tmp_path, capsys):
        close_mod.close(str(tmp_path))
        assert "not running" in capsys.readouterr().out

    def test_kills_process(self, close_mod, tmp_path, monkeypatch, capsys):
        (tmp_path / "nw.pid").write_text("12345")
        killed = []
        monkeypatch.setattr(close_mod.os, "kill", lambda pid, sig: killed.append(pid))
        close_mod.close(str(tmp_path))
        assert killed == [12345]
        assert not (tmp_path / "nw.pid").exists()
        assert "Closed" in capsys.readouterr().out

    def test_stale_pid(self, close_mod, tmp_path, monkeypatch, capsys):
        (tmp_path / "nw.pid").write_text("99999")

        def fake_kill(pid, sig):
            raise ProcessLookupError()

        monkeypatch.setattr(close_mod.os, "kill", fake_kill)
        close_mod.close(str(tmp_path))
        assert not (tmp_path / "nw.pid").exists()
        assert "Already closed" in capsys.readouterr().out
