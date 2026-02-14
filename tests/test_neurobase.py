"""
Tests for bin/neurobase.py

Logic:
    container running?  -> do nothing
    container exists?   -> docker start
    otherwise           -> docker compose up -d
"""

import importlib.util
import os
import sys

import pytest

from neuro.utils import internal_utils, test_utils


# -- Load module --

@pytest.fixture(scope="session")
def neurobase():
    spec = importlib.util.spec_from_file_location(
        "neurobase",
        os.path.join(internal_utils.get_path("app"), "bin/neurobase.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["neurobase"] = mod
    os.environ["BASE_NAME"] = "test-container"
    spec.loader.exec_module(mod)
    return mod


# -- Tests --

class TestContainerRunning:
    """container_running() checks docker inspect exit code and stdout."""

    def test_true_when_running(self, neurobase, monkeypatch):
        monkeypatch.setattr(neurobase.subprocess, "run", test_utils.fake_subprocess(0, "true\n"))
        assert neurobase.container_running() is True

    def test_false_when_stopped(self, neurobase, monkeypatch):
        monkeypatch.setattr(neurobase.subprocess, "run", test_utils.fake_subprocess(0, "false\n"))
        assert neurobase.container_running() is False

    def test_false_when_missing(self, neurobase, monkeypatch):
        monkeypatch.setattr(neurobase.subprocess, "run", test_utils.fake_subprocess(1))
        assert neurobase.container_running() is False


class TestContainerExists:
    """container_exists() checks docker container inspect exit code."""

    def test_true(self, neurobase, monkeypatch):
        monkeypatch.setattr(neurobase.subprocess, "run", test_utils.fake_subprocess(0))
        assert neurobase.container_exists() is True

    def test_false(self, neurobase, monkeypatch):
        monkeypatch.setattr(neurobase.subprocess, "run", test_utils.fake_subprocess(1))
        assert neurobase.container_exists() is False


class TestMain:
    """main() picks the right action based on container state."""

    def test_running_skips(self, neurobase, monkeypatch, capsys):
        monkeypatch.setattr(neurobase, "container_running", lambda: True)
        calls = []
        monkeypatch.setattr(neurobase.subprocess, "run", lambda *a, **kw: calls.append(a))
        neurobase.main()
        assert calls == []
        assert "already running" in capsys.readouterr().out

    def test_stopped_starts(self, neurobase, monkeypatch, capsys):
        monkeypatch.setattr(neurobase, "container_running", lambda: False)
        monkeypatch.setattr(neurobase, "container_exists", lambda: True)
        calls = []
        monkeypatch.setattr(neurobase.subprocess, "run", lambda cmd: calls.append(cmd))
        neurobase.main()
        assert calls == [["docker", "start", "test-container"]]

    def test_missing_creates(self, neurobase, monkeypatch, capsys):
        monkeypatch.setattr(neurobase, "container_running", lambda: False)
        monkeypatch.setattr(neurobase, "container_exists", lambda: False)
        calls = []
        monkeypatch.setattr(neurobase.subprocess, "run", lambda cmd: calls.append(cmd))
        neurobase.main()
        assert calls == [["docker", "compose", "up", "-d"]]
