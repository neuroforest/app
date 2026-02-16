"""
Tests for tasks.desktop (run/close NW.js app).
"""

import os
import signal

import pytest

import tasks.desktop as desktop_mod
from neuro.utils.test_utils import FakeContext, Recorder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeDriver:
    def __init__(self, connectable=True):
        self.connectable = connectable
        self.closed = False

    def verify_connectivity(self):
        if not self.connectable:
            raise Exception("unavailable")

    def close(self):
        self.closed = True


class FakePopen:
    def __init__(self, pid=12345, poll_result=None):
        self.pid = pid
        self._poll_result = poll_result

    def poll(self):
        return self._poll_result


# ---------------------------------------------------------------------------
# save_pid / get_app_dir
# ---------------------------------------------------------------------------

class TestSavePid:
    def test_writes_pid_file(self, tmp_path):
        desktop_mod.save_pid(str(tmp_path), 42)
        pid_path = tmp_path / "nw.pid"
        assert pid_path.exists()
        assert pid_path.read_text() == "42"


class TestGetAppDir:
    def test_returns_absolute(self, monkeypatch):
        monkeypatch.setattr(desktop_mod.internal_utils, "get_path",
                            lambda k: "/absolute/app")
        assert desktop_mod.get_app_dir() == "/absolute/app"


# ---------------------------------------------------------------------------
# verify_neo4j
# ---------------------------------------------------------------------------

class TestVerifyNeo4j:
    def test_success(self, monkeypatch, capsys):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USER", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pass")
        driver = FakeDriver(connectable=True)
        monkeypatch.setattr(desktop_mod.neo4j.GraphDatabase, "driver",
                            lambda uri, auth: driver)
        desktop_mod.verify_neo4j()
        out = capsys.readouterr().out
        assert "connected" in out
        assert driver.closed

    def test_failure_exits(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USER", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pass")
        driver = FakeDriver(connectable=False)
        monkeypatch.setattr(desktop_mod.neo4j.GraphDatabase, "driver",
                            lambda uri, auth: driver)
        with pytest.raises(SystemExit):
            desktop_mod.verify_neo4j()


# ---------------------------------------------------------------------------
# register_protocol
# ---------------------------------------------------------------------------

class TestRegisterProtocol:
    def test_not_running(self, monkeypatch, capsys):
        monkeypatch.setenv("ND_PORT", "8080")
        monkeypatch.setattr(desktop_mod.network_utils, "is_port_in_use",
                            lambda p: False)
        desktop_mod.register_protocol("neuro://abc-123")
        out = capsys.readouterr().out
        assert "not running" in out

    def test_found(self, monkeypatch):
        monkeypatch.setenv("ND_PORT", "8080")
        monkeypatch.setattr(desktop_mod.network_utils, "is_port_in_use",
                            lambda p: True)
        opened = []
        monkeypatch.setattr(desktop_mod.tw_get, "filter_output",
                            lambda q: ["MyTiddler"])
        monkeypatch.setattr(desktop_mod.tw_actions, "open_tiddler",
                            lambda t: opened.append(t))
        desktop_mod.register_protocol("neuro://abc-123")
        assert opened == ["MyTiddler"]

    def test_not_found(self, monkeypatch, capsys):
        monkeypatch.setenv("ND_PORT", "8080")
        monkeypatch.setattr(desktop_mod.network_utils, "is_port_in_use",
                            lambda p: True)
        monkeypatch.setattr(desktop_mod.tw_get, "filter_output", lambda q: [])
        desktop_mod.register_protocol("neuro://abc-123")
        out = capsys.readouterr().out
        assert "Not found" in out


# ---------------------------------------------------------------------------
# Task: run
# ---------------------------------------------------------------------------

class TestRunTask:
    def test_no_binary_exits(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setattr(desktop_mod, "get_app_dir", lambda: str(tmp_path))
        with pytest.raises(SystemExit):
            desktop_mod.run.__wrapped__(ctx)

    def test_launches_nwjs(self, ctx, monkeypatch, tmp_path, capsys):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        nw = app_dir / "nw"
        nw.write_text("fake")

        monkeypatch.setattr(desktop_mod, "get_app_dir", lambda: str(app_dir))
        monkeypatch.setattr(desktop_mod, "verify_neo4j", lambda: None)
        monkeypatch.setattr(desktop_mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(desktop_mod.subprocess, "Popen",
                            lambda *a, **kw: FakePopen(pid=999))
        desktop_mod.run.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "999" in out
        assert (app_dir / "nw.pid").exists()

    def test_already_running(self, ctx, monkeypatch, tmp_path, capsys):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        nw = app_dir / "nw"
        nw.write_text("fake")

        monkeypatch.setattr(desktop_mod, "get_app_dir", lambda: str(app_dir))
        monkeypatch.setattr(desktop_mod, "verify_neo4j", lambda: None)
        monkeypatch.setattr(desktop_mod.time, "sleep", lambda s: None)
        # poll() returns non-None means process already exited
        monkeypatch.setattr(desktop_mod.subprocess, "Popen",
                            lambda *a, **kw: FakePopen(poll_result=1))
        desktop_mod.run.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "Already running" in out


# ---------------------------------------------------------------------------
# Task: close
# ---------------------------------------------------------------------------

class TestCloseTask:
    def test_no_pid_file(self, ctx, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(desktop_mod, "get_app_dir", lambda: str(tmp_path))
        desktop_mod.close.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "No PID file" in out

    def test_kills_process(self, ctx, monkeypatch, tmp_path, capsys):
        pid_path = tmp_path / "nw.pid"
        pid_path.write_text("12345")
        monkeypatch.setattr(desktop_mod, "get_app_dir", lambda: str(tmp_path))

        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        desktop_mod.close.__wrapped__(ctx)

        assert killed == [(12345, signal.SIGTERM)]
        assert not pid_path.exists()
        out = capsys.readouterr().out
        assert "Closed" in out

    def test_process_already_gone(self, ctx, monkeypatch, tmp_path, capsys):
        pid_path = tmp_path / "nw.pid"
        pid_path.write_text("99999")
        monkeypatch.setattr(desktop_mod, "get_app_dir", lambda: str(tmp_path))

        def fake_kill(pid, sig):
            raise ProcessLookupError()
        monkeypatch.setattr(os, "kill", fake_kill)
        desktop_mod.close.__wrapped__(ctx)

        out = capsys.readouterr().out
        assert "not found" in out
        assert not pid_path.exists()
