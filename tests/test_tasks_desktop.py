"""
Tests for tasks.components.desktop (build, run, close).
"""

import json
import os
import signal

import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step

import tasks.components.desktop as desktop_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(desktop_mod.terminal_style, "step", noop_step)


@pytest.fixture
def rsync_recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(desktop_mod.build_utils, "rsync_local", rec)
    return rec


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(desktop_mod.subprocess, "run", rec)
    return rec


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
# Task: build
# ---------------------------------------------------------------------------

class TestBuild:
    def _setup_build(self, monkeypatch, tmp_path):
        """Common setup: stub get_path, env vars, bool_prompt, shutil.rmtree."""
        nf = tmp_path / "nf"
        nf.mkdir()
        monkeypatch.setattr(desktop_mod.internal_utils, "get_path", lambda k: str(nf))
        monkeypatch.setenv("NWJS_VERSION", "0.80.0")
        monkeypatch.setenv("APP_NAME", "TestApp")
        monkeypatch.setattr(desktop_mod.terminal_components, "bool_prompt", lambda msg: True)
        monkeypatch.setattr(desktop_mod.shutil, "rmtree", lambda *a, **kw: None)
        return nf

    def _make_source_pkg(self, build_dir, content=None):
        if content is None:
            content = {"name": "placeholder"}
        source_dir = os.path.join(build_dir, "source")
        os.makedirs(source_dir, exist_ok=True)
        with open(os.path.join(source_dir, "package.json"), "w") as f:
            json.dump(content, f)

    def test_rsyncs_nwjs_tw5_desktop(self, ctx, monkeypatch, tmp_path,
                                      rsync_recorder, subprocess_recorder):
        self._setup_build(monkeypatch, tmp_path)
        build_dir = str(tmp_path / "build")
        self._make_source_pkg(build_dir)

        desktop_mod.build.__wrapped__(ctx, build_dir=build_dir)

        assert rsync_recorder.call_count == 3
        names = [c[0][2] for c in rsync_recorder.calls]
        assert "NW.js v0.80.0" in names
        assert "tw5" in names
        assert "desktop source" in names

    def test_writes_package_json_with_app_name(self, ctx, monkeypatch, tmp_path,
                                                rsync_recorder, subprocess_recorder):
        self._setup_build(monkeypatch, tmp_path)
        build_dir = str(tmp_path / "build")
        self._make_source_pkg(build_dir, {"name": "placeholder", "version": "1.0"})

        desktop_mod.build.__wrapped__(ctx, build_dir=build_dir)

        with open(os.path.join(build_dir, "package.json")) as f:
            pkg = json.load(f)
        assert pkg["name"] == "TestApp"
        assert pkg["version"] == "1.0"

    def test_runs_npm_install(self, ctx, monkeypatch, tmp_path,
                               rsync_recorder, subprocess_recorder):
        self._setup_build(monkeypatch, tmp_path)
        build_dir = str(tmp_path / "build")
        self._make_source_pkg(build_dir)

        desktop_mod.build.__wrapped__(ctx, build_dir=build_dir)

        npm_calls = [c for c in subprocess_recorder.calls
                     if c[0][0] == ["npm", "install"]]
        assert len(npm_calls) == 1
        assert npm_calls[0][1]["cwd"] == build_dir

    def test_prompts_on_existing_dir(self, ctx, monkeypatch, tmp_path,
                                      rsync_recorder, subprocess_recorder):
        self._setup_build(monkeypatch, tmp_path)
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._make_source_pkg(str(build_dir))

        prompted = []
        monkeypatch.setattr(desktop_mod.terminal_components, "bool_prompt",
                            lambda msg: (prompted.append(msg), True)[1])

        desktop_mod.build.__wrapped__(ctx, build_dir=str(build_dir))
        assert len(prompted) == 1
        assert "Rewrite" in prompted[0]
        assert rsync_recorder.call_count == 3

    def test_default_build_dir(self, ctx, monkeypatch, tmp_path,
                                rsync_recorder, subprocess_recorder):
        nf = self._setup_build(monkeypatch, tmp_path)
        build_dir = os.path.join(str(nf), "app")
        self._make_source_pkg(build_dir)

        desktop_mod.build.__wrapped__(ctx, build_dir=None)
        assert rsync_recorder.call_count == 3


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
