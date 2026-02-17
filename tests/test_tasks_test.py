"""
Tests for tasks.actions.test.
"""

import os

import pytest

import tasks.actions.test as test_mod
from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture
def patch_subprocess(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(test_mod.subprocess, "run", rec)
    return rec


@pytest.fixture
def patch_tw5_test(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(test_mod.tw5, "test", rec)
    return rec


@pytest.fixture
def patch_neuro_test_local(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(test_mod.neuro, "test_local", rec)
    return rec


@pytest.fixture
def patch_app(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(test_mod, "app", rec)
    return rec


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------

class TestApp:
    def test_default_args(self, ctx, patch_subprocess):
        test_mod.app.__wrapped__(ctx)
        assert patch_subprocess.last_args == (["nenv/bin/pytest", "./tests"],)

    def test_custom_args(self, ctx, patch_subprocess):
        test_mod.app.__wrapped__(ctx, pytest_args="-x tests/test_foo.py")
        assert patch_subprocess.last_args == (["nenv/bin/pytest", "-x", "tests/test_foo.py"],)

    def test_exit_code_zero(self, ctx, patch_subprocess):
        test_mod.app.__wrapped__(ctx)  # should not raise

    def test_nonzero_exit_raises(self, ctx, monkeypatch):
        monkeypatch.setattr(test_mod.subprocess, "run", lambda args: SubprocessResult(1))
        with pytest.raises(SystemExit):
            test_mod.app.__wrapped__(ctx)


# ---------------------------------------------------------------------------
# local
# ---------------------------------------------------------------------------

class TestLocal:
    def test_defaults_to_all(self, ctx, patch_tw5_test, patch_neuro_test_local,
                             patch_app):
        test_mod.local.__wrapped__(ctx, components=[])
        assert patch_tw5_test.call_count == 1
        assert patch_neuro_test_local.call_count == 1
        assert patch_app.call_count == 1

    def test_only_tw5(self, ctx, patch_tw5_test, patch_neuro_test_local,
                      patch_app):
        test_mod.local.__wrapped__(ctx, components=["tw5"])
        assert patch_tw5_test.call_count == 1
        assert patch_neuro_test_local.call_count == 0
        assert patch_app.call_count == 0

    def test_only_neuro(self, ctx, patch_tw5_test, patch_neuro_test_local,
                        patch_app):
        test_mod.local.__wrapped__(ctx, components=["neuro"])
        assert patch_tw5_test.call_count == 0
        assert patch_neuro_test_local.call_count == 1
        assert patch_app.call_count == 0

    def test_only_app(self, ctx, patch_tw5_test, patch_neuro_test_local,
                      patch_app):
        test_mod.local.__wrapped__(ctx, components=["app"])
        assert patch_tw5_test.call_count == 0
        assert patch_neuro_test_local.call_count == 0
        assert patch_app.call_count == 1


# ---------------------------------------------------------------------------
# ruff
# ---------------------------------------------------------------------------

class TestRuff:
    def test_calls_neuro_ruff(self, ctx, monkeypatch, patch_subprocess):
        rec = Recorder()
        monkeypatch.setattr(test_mod.neuro, "ruff", rec)
        test_mod.ruff.__wrapped__(ctx)
        assert rec.call_count == 1

    def test_passes_ruff_args_to_neuro(self, ctx, monkeypatch, patch_subprocess):
        rec = Recorder()
        monkeypatch.setattr(test_mod.neuro, "ruff", rec)
        test_mod.ruff.__wrapped__(ctx, ruff_args="--fix")
        assert rec.last_kwargs == {"ruff_args": "--fix"}

    def test_runs_ruff_on_app(self, ctx, monkeypatch, patch_subprocess):
        monkeypatch.setattr(test_mod.neuro, "ruff", Recorder())
        test_mod.ruff.__wrapped__(ctx)
        assert patch_subprocess.last_args == (["nenv/bin/ruff", "check", "tasks/", "tests/"],)

    def test_custom_args(self, ctx, monkeypatch, patch_subprocess):
        monkeypatch.setattr(test_mod.neuro, "ruff", Recorder())
        test_mod.ruff.__wrapped__(ctx, ruff_args="--fix")
        assert patch_subprocess.last_args == (["nenv/bin/ruff", "check", "tasks/", "tests/", "--fix"],)

    def test_nonzero_exit_raises(self, ctx, monkeypatch):
        monkeypatch.setattr(test_mod.neuro, "ruff", Recorder())
        monkeypatch.setattr(test_mod.subprocess, "run", lambda args: SubprocessResult(1))
        with pytest.raises(SystemExit):
            test_mod.ruff.__wrapped__(ctx)


# ---------------------------------------------------------------------------
# production
# ---------------------------------------------------------------------------

class TestProduction:
    def test_sets_environment(self, ctx, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        test_mod.production.__wrapped__(ctx)
        assert os.environ["ENVIRONMENT"] == "TESTING"

    def test_prints_stub_message(self, ctx, capsys):
        test_mod.production.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "not yet implemented" in out


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_components(self):
        assert test_mod.COMPONENTS == ["app", "neuro", "tw5"]
