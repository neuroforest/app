"""
Tests for bin/run.py

Logic:
    verify_neo4j: connects to Neo4j, exits on failure.
    register_protocol: handles neuro:// URLs via TW5 API.
    run: verifies Neo4j then launches NW.js from build directory.
"""

import importlib.util
import os
import sys

import pytest

from neuro.utils import internal_utils

APP_PATH = internal_utils.get_path("app")


# -- Load module --

@pytest.fixture(scope="session")
def run_mod():
    spec = importlib.util.spec_from_file_location(
        "run",
        os.path.join(APP_PATH, "bin/run.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run"] = mod
    spec.loader.exec_module(mod)
    return mod


# -- Tests --

class TestVerifyNeo4j:
    """verify_neo4j() checks database connectivity."""

    def test_success(self, run_mod, monkeypatch, capsys):
        class FakeDriver:
            def verify_connectivity(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(run_mod.neo4j.GraphDatabase, "driver", lambda *a, **kw: FakeDriver())
        run_mod.verify_neo4j()
        assert "Neo4j connected" in capsys.readouterr().out

    def test_exits_on_failure(self, run_mod, monkeypatch):
        import neo4j as neo4j_mod

        class FailDriver:
            def verify_connectivity(self):
                raise neo4j_mod.exceptions.ServiceUnavailable("down")
            def close(self):
                pass

        monkeypatch.setattr(run_mod.neo4j.GraphDatabase, "driver", lambda *a, **kw: FailDriver())
        with pytest.raises(SystemExit, match="1"):
            run_mod.verify_neo4j()


class TestRegisterProtocol:
    """register_protocol() handles neuro:// deep links."""

    def test_not_running(self, run_mod, monkeypatch, capsys):
        monkeypatch.setattr(run_mod.network_utils, "is_port_in_use", lambda p: False)
        run_mod.register_protocol("neuro://abc-123")
        assert "not running" in capsys.readouterr().out

    def test_not_found(self, run_mod, monkeypatch, capsys):
        monkeypatch.setattr(run_mod.network_utils, "is_port_in_use", lambda p: True)
        monkeypatch.setattr(run_mod.tw_get, "filter_output", lambda q: [])
        run_mod.register_protocol("neuro://abc-123")
        assert "Not found" in capsys.readouterr().out

    def test_opens_tiddler(self, run_mod, monkeypatch):
        monkeypatch.setattr(run_mod.network_utils, "is_port_in_use", lambda p: True)
        monkeypatch.setattr(run_mod.tw_get, "filter_output", lambda q: ["MyTiddler"])
        opened = []
        monkeypatch.setattr(run_mod.tw_actions, "open_tiddler", lambda t: opened.append(t))
        run_mod.register_protocol("neuro://abc-123")
        assert opened == ["MyTiddler"]


class TestRun:
    """run() verifies Neo4j then launches NW.js."""

    def test_exits_if_no_binary(self, run_mod, tmp_path):
        with pytest.raises(SystemExit, match="1"):
            run_mod.run(str(tmp_path))

    def test_launches_and_saves_pid(self, run_mod, tmp_path, monkeypatch):
        nw = tmp_path / "nw"
        nw.write_text("#!/bin/sh")
        nw.chmod(0o755)
        monkeypatch.setattr(run_mod, "verify_neo4j", lambda: None)
        monkeypatch.setattr(run_mod.time, "sleep", lambda s: None)

        class FakeProcess:
            pid = 12345
            def poll(self):
                return None

        calls = []

        def fake_popen(*a, **kw):
            calls.append((a, kw))
            return FakeProcess()

        monkeypatch.setattr(run_mod.subprocess, "Popen", fake_popen)
        run_mod.run(str(tmp_path))
        assert len(calls) == 1
        assert calls[0][0][0] == [str(nw)]
        assert calls[0][1]["cwd"] == str(tmp_path)
        assert (tmp_path / "nw.pid").read_text() == "12345"

    def test_detects_immediate_exit(self, run_mod, tmp_path, monkeypatch, capsys):
        nw = tmp_path / "nw"
        nw.write_text("#!/bin/sh")
        nw.chmod(0o755)
        monkeypatch.setattr(run_mod, "verify_neo4j", lambda: None)
        monkeypatch.setattr(run_mod.time, "sleep", lambda s: None)

        class FakeProcess:
            pid = 99999
            def poll(self):
                return 0

        monkeypatch.setattr(run_mod.subprocess, "Popen", lambda *a, **kw: FakeProcess())
        run_mod.run(str(tmp_path))
        assert "Already running" in capsys.readouterr().out
        assert not (tmp_path / "nw.pid").exists()
