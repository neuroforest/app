"""
Tests for tasks.components.neurobase.
"""

import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step

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


@pytest.fixture(autouse=True)
def patch_step(monkeypatch):
    monkeypatch.setattr(neurobase_mod.terminal_style, "step", noop_step)


@pytest.fixture(autouse=True)
def patch_wait(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(neurobase_mod.network_utils, "wait_for_socket", rec)
    return rec


@pytest.fixture(autouse=True)
def patch_verify_neo4j(monkeypatch, request):
    if request.node.cls and request.node.cls.__name__ != "TestVerifyNeo4j":
        monkeypatch.setattr(neurobase_mod, "verify_neo4j", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_already_exists(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)
        neurobase_mod.create.__wrapped__(ctx)
        assert subprocess_recorder.call_count == 0

    def test_does_not_exist(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: False)
        neurobase_mod.create.__wrapped__(ctx)
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "compose", "up", "-d"]

    def test_base_name_param(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "ignored")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: n == "custom")
        neurobase_mod.create.__wrapped__(ctx, name="custom")
        assert subprocess_recorder.call_count == 0


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

class TestStart:
    def test_already_running(self, ctx, monkeypatch, patch_wait, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: True)
        neurobase_mod.start.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "is running" in out
        assert patch_wait.call_count == 1

    def test_not_running_starts_container(self, ctx, monkeypatch, subprocess_recorder, patch_wait):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        neurobase_mod.start.__wrapped__(ctx)
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "start", "nb"]
        assert patch_wait.call_count == 1

    def test_wait_uses_bolt_port(self, ctx, monkeypatch, subprocess_recorder, patch_wait):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setenv("NEO4J_PORT_BOLT", "7688")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        neurobase_mod.start.__wrapped__(ctx)
        assert patch_wait.calls[0][0] == ("127.0.0.1", 7688)

    def test_base_name_param(self, ctx, monkeypatch, subprocess_recorder, patch_wait):
        monkeypatch.setenv("BASE_NAME", "ignored")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        neurobase_mod.start.__wrapped__(ctx, name="custom")
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "start", "custom"]


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

class TestStop:
    def test_not_running(self, ctx, monkeypatch, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        neurobase_mod.stop.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "Already stopped" in out

    def test_running_stops_container(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: True)
        neurobase_mod.stop.__wrapped__(ctx)
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "stop", "nb"]

    def test_name_param(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "ignored")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: True)
        neurobase_mod.stop.__wrapped__(ctx, name="custom")
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "stop", "custom"]


# ---------------------------------------------------------------------------
# verify_neo4j
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


class TestVerifyNeo4j:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USER", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pass")
        driver = FakeDriver(connectable=True)
        monkeypatch.setattr(neurobase_mod.neo4j.GraphDatabase, "driver",
                            lambda uri, auth: driver)
        neurobase_mod.verify_neo4j()
        assert driver.closed

    def test_failure_exits(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USER", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pass")
        driver = FakeDriver(connectable=False)
        monkeypatch.setattr(neurobase_mod.neo4j.GraphDatabase, "driver",
                            lambda uri, auth: driver)
        with pytest.raises(SystemExit):
            neurobase_mod.verify_neo4j(timeout=0)
