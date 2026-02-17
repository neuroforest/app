"""
Tests for tasks.components.neurobase.
"""

import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult

import tasks.components.neurobase as neurobase_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(neurobase_mod.subprocess, "run", rec)
    return rec


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

class TestStart:
    def test_already_running(self, ctx, monkeypatch, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: True)
        neurobase_mod.start.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "is running" in out

    def test_exists_but_stopped(self, ctx, monkeypatch, subprocess_recorder, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)
        neurobase_mod.start.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "Starting existing" in out
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "start", "nb"]

    def test_does_not_exist(self, ctx, monkeypatch, subprocess_recorder, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: False)
        neurobase_mod.start.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "Creating" in out
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "compose", "up", "-d"]
