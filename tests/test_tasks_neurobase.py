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
    @pytest.fixture(autouse=True)
    def _patch_create(self, monkeypatch):
        self.create_rec = Recorder()
        monkeypatch.setattr(neurobase_mod, "create", self.create_rec)

    @pytest.fixture(autouse=True)
    def _container_exists(self, monkeypatch):
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)

    def test_already_running(self, ctx, monkeypatch, patch_wait, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: True)
        neurobase_mod.start.__wrapped__(ctx)
        assert subprocess_recorder.call_count == 0
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

    def test_base_name_param_propagates_to_create(self, ctx, monkeypatch, subprocess_recorder, patch_wait):
        monkeypatch.setenv("BASE_NAME", "ignored")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_running", lambda n: False)
        neurobase_mod.start.__wrapped__(ctx, name="custom")
        assert self.create_rec.last_kwargs == {"name": "custom"}

    def test_container_not_exists_fails(self, ctx, monkeypatch, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: False)
        with pytest.raises(SystemExit):
            neurobase_mod.start.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "does not exist" in out


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
# reset
# ---------------------------------------------------------------------------

class FakeNeuroBase:
    def __init__(self, node_count=0):
        self._count = node_count
        self.cleared = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def count(self):
        return self._count

    def clear(self, confirm=False):
        self.cleared = confirm


class TestReset:
    @pytest.fixture(autouse=True)
    def _patch_start(self, monkeypatch):
        self.start_rec = Recorder()
        monkeypatch.setattr(neurobase_mod, "start", self.start_rec)

    def test_empty_db_skips(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        nb = FakeNeuroBase(node_count=0)
        monkeypatch.setattr(neurobase_mod, "NeuroBase", lambda: nb)
        neurobase_mod.reset.__wrapped__(ctx)
        assert not nb.cleared

    def test_clears_on_confirm(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        nb = FakeNeuroBase(node_count=5)
        monkeypatch.setattr(neurobase_mod, "NeuroBase", lambda: nb)
        monkeypatch.setattr(neurobase_mod.terminal_components, "bool_prompt", lambda msg: True)
        neurobase_mod.reset.__wrapped__(ctx)
        assert nb.cleared

    def test_aborts_on_decline(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        nb = FakeNeuroBase(node_count=5)
        monkeypatch.setattr(neurobase_mod, "NeuroBase", lambda: nb)
        monkeypatch.setattr(neurobase_mod.terminal_components, "bool_prompt", lambda msg: False)
        with pytest.raises(SystemExit):
            neurobase_mod.reset.__wrapped__(ctx)

    def test_name_propagates_to_start(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "ignored")
        nb = FakeNeuroBase(node_count=0)
        monkeypatch.setattr(neurobase_mod, "NeuroBase", lambda: nb)
        neurobase_mod.reset.__wrapped__(ctx, name="custom")
        assert self.start_rec.last_kwargs == {"name": "custom"}

    def test_prompt_includes_name(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        nb = FakeNeuroBase(node_count=3)
        monkeypatch.setattr(neurobase_mod, "NeuroBase", lambda: nb)
        prompts = []
        monkeypatch.setattr(neurobase_mod.terminal_components, "bool_prompt",
                            lambda msg: (prompts.append(msg), True)[1])
        neurobase_mod.reset.__wrapped__(ctx)
        assert "nb" in prompts[0]
        assert "3" in prompts[0]


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


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

class FakeContainer:
    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.backup_called = False
        self.clean_called = False

    def backup(self):
        self.backup_called = True

    def clean(self):
        self.clean_called = True


class TestBackup:
    @pytest.fixture(autouse=True)
    def _patch_get_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(neurobase_mod.internal_utils, "get_path",
                            lambda k, **kw: tmp_path)

    def test_calls_backup_and_clean(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        container = FakeContainer()
        monkeypatch.setattr(neurobase_mod.docker_tools, "Container",
                            lambda **kw: container)
        neurobase_mod.backup.__wrapped__(ctx)
        assert container.backup_called
        assert container.clean_called

    def test_passes_name_to_container(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "ignored")
        captured = {}
        def fake_container(**kwargs):
            captured.update(kwargs)
            return FakeContainer()
        monkeypatch.setattr(neurobase_mod.docker_tools, "Container", fake_container)
        neurobase_mod.backup.__wrapped__(ctx, name="custom")
        assert captured["name"] == "custom"

    def test_uses_env_default(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        captured = {}
        def fake_container(**kwargs):
            captured.update(kwargs)
            return FakeContainer()
        monkeypatch.setattr(neurobase_mod.docker_tools, "Container", fake_container)
        neurobase_mod.backup.__wrapped__(ctx)
        assert captured["name"] == "nb"

    def test_pre_includes_stop(self):
        pre_names = [t.name for t in neurobase_mod.backup.pre]
        assert "stop" in pre_names


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.fixture(autouse=True)
    def _confirm(self, monkeypatch):
        monkeypatch.setattr(neurobase_mod.terminal_components, "bool_prompt",
                            lambda msg: True)

    def test_not_exists(self, ctx, monkeypatch, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: False)
        neurobase_mod.delete.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "not found" in out

    def test_removes_container_and_volumes(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)
        monkeypatch.setattr(neurobase_mod.docker_tools, "get_container_volumes", lambda n: ["vol1", "vol2"])
        neurobase_mod.delete.__wrapped__(ctx)
        cmds = [c[0][0] for c in subprocess_recorder.calls]
        assert ["docker", "rm", "nb"] in cmds
        assert ["docker", "volume", "rm", "vol1"] in cmds
        assert ["docker", "volume", "rm", "vol2"] in cmds

    def test_name_param(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "ignored")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)
        monkeypatch.setattr(neurobase_mod.docker_tools, "get_container_volumes", lambda n: [])
        neurobase_mod.delete.__wrapped__(ctx, name="custom")
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "rm", "custom"]

    def test_no_volumes(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)
        monkeypatch.setattr(neurobase_mod.docker_tools, "get_container_volumes", lambda n: [])
        neurobase_mod.delete.__wrapped__(ctx)
        assert subprocess_recorder.call_count == 1
        assert subprocess_recorder.calls[0][0][0] == ["docker", "rm", "nb"]

    def test_aborts_on_decline(self, ctx, monkeypatch):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(neurobase_mod.docker_tools, "container_exists", lambda n: True)
        monkeypatch.setattr(neurobase_mod.terminal_components, "bool_prompt",
                            lambda msg: False)
        with pytest.raises(SystemExit):
            neurobase_mod.delete.__wrapped__(ctx)

    def test_pre_includes_stop(self):
        pre_names = [t.name for t in neurobase_mod.delete.pre]
        assert "stop" in pre_names
