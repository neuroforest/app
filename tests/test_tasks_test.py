"""
Tests for tasks.test (the test-runner invoke tasks).
"""

import os

import pytest

import tasks.actions.test as test_mod
from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(test_mod.terminal_style, "step", noop_step)


@pytest.fixture
def patch_get_path(monkeypatch):
    paths = {"neuro": "/src/neuro", "nf": "/app", "tw5": "/app/tw5"}
    monkeypatch.setattr(test_mod.internal_utils, "get_path", lambda k: paths[k])


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(test_mod.subprocess, "run", rec)
    return rec


@pytest.fixture
def pytest_recorder(monkeypatch):
    rec = Recorder(return_value=0)
    monkeypatch.setattr(test_mod.pytest, "main", rec)
    return rec


@pytest.fixture
def fake_neuro(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(test_mod.neuro_mod, "rsync_and_install", rec)
    return rec


@pytest.fixture
def fake_tw5(monkeypatch):
    monkeypatch.setattr(test_mod.tw5_mod, "copy_tw5_editions", lambda: None)
    monkeypatch.setattr(test_mod.tw5_mod, "copy_tw5_plugins", lambda: None)


# ---------------------------------------------------------------------------
# test.app
# ---------------------------------------------------------------------------

class TestApp:
    def test_sets_environment(self, ctx, pytest_recorder):
        test_mod.app.__wrapped__(ctx)
        assert os.environ["ENVIRONMENT"] == "TESTING"

    def test_runs_pytest_on_tests_dir(self, ctx, pytest_recorder):
        test_mod.app.__wrapped__(ctx)
        assert pytest_recorder.call_count == 1
        assert pytest_recorder.last_args == (["tests"],)

    def test_raises_on_failure(self, ctx, monkeypatch):
        monkeypatch.setattr(test_mod.pytest, "main", Recorder(return_value=1))
        with pytest.raises(SystemExit):
            test_mod.app.__wrapped__(ctx)

    def test_no_raise_on_success(self, ctx, pytest_recorder):
        test_mod.app.__wrapped__(ctx)


# ---------------------------------------------------------------------------
# test.local
# ---------------------------------------------------------------------------

class TestLocal:
    def test_defaults_to_all_components(self, ctx, patch_get_path,
                                        fake_neuro, subprocess_recorder,
                                        pytest_recorder, fake_tw5):
        test_mod.local.__wrapped__(ctx, components=[])
        assert pytest_recorder.call_count == 2
        pytest_args = [a[0][0] for a in pytest_recorder.calls]
        assert ["tests"] in pytest_args
        assert ["neuro/tests"] in pytest_args
        tw5_calls = [c for c in subprocess_recorder.calls
                     if c[0][0] == ["bin/test.sh"]]
        assert len(tw5_calls) == 1

    def test_single_component(self, ctx, pytest_recorder):
        test_mod.local.__wrapped__(ctx, components=["app"])
        assert pytest_recorder.call_count == 1
        assert pytest_recorder.last_args == (["tests"],)

    def test_unknown_component(self, ctx, capsys):
        with pytest.raises(SystemExit):
            test_mod.local.__wrapped__(ctx, components=["unknown"])
        out = capsys.readouterr().out
        assert "Unknown component: unknown" in out

    def test_summary_printed(self, ctx, pytest_recorder, capsys):
        test_mod.local.__wrapped__(ctx, components=["app"])
        out = capsys.readouterr().out
        assert "Test Summary" in out
        assert "app" in out

    def test_raises_on_any_failure(self, ctx, monkeypatch):
        monkeypatch.setattr(test_mod.pytest, "main", Recorder(return_value=1))
        with pytest.raises(SystemExit):
            test_mod.local.__wrapped__(ctx, components=["app"])

    def test_no_raise_all_pass(self, ctx, pytest_recorder):
        test_mod.local.__wrapped__(ctx, components=["app"])

    def test_catches_exception_in_component(self, ctx, monkeypatch, capsys):
        def explode(*a, **kw):
            raise RuntimeError("boom")
        monkeypatch.setattr(test_mod.pytest, "main", explode)
        with pytest.raises(SystemExit):
            test_mod.local.__wrapped__(ctx, components=["app"])
        out = capsys.readouterr().out
        assert "Error running app" in out


# ---------------------------------------------------------------------------
# test.production
# ---------------------------------------------------------------------------

class TestProduction:
    def test_sets_environment(self, ctx):
        test_mod.production.__wrapped__(ctx)
        assert os.environ["ENVIRONMENT"] == "TESTING"

    def test_prints_stub_message(self, ctx, capsys):
        test_mod.production.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "not yet implemented" in out


# ---------------------------------------------------------------------------
# Module-level
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_all_local_components(self):
        assert test_mod.ALL_LOCAL_COMPONENTS == ["app", "neuro", "tw5"]
