"""
Tests for tasks.components.neuro.
"""

from pathlib import Path

import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult

import tasks.components.neuro as neuro_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture
def patch_subprocess(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(neuro_mod.subprocess, "run", rec)
    return rec


@pytest.fixture
def patch_rsync(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(neuro_mod.setup, "rsync", rec)
    return rec


@pytest.fixture
def patch_branch(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(neuro_mod.setup, "branch", rec)
    return rec


@pytest.fixture
def patch_nenv(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(neuro_mod.setup, "nenv", rec)
    return rec


@pytest.fixture
def patch_test(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(neuro_mod, "test", rec)
    monkeypatch.setattr(neuro_mod, "test_integration", rec)
    return rec


# ---------------------------------------------------------------------------
# ruff
# ---------------------------------------------------------------------------

class TestRuff:
    def test_runs_ruff_on_neuro(self, ctx, patch_subprocess, monkeypatch):
        monkeypatch.setattr(neuro_mod.internal_utils, "get_path", lambda k: Path("/neuro"))
        neuro_mod.ruff.__wrapped__(ctx)
        assert patch_subprocess.last_args == (["nenv/bin/ruff", "check", Path("/neuro")],)

    def test_custom_args(self, ctx, patch_subprocess, monkeypatch):
        monkeypatch.setattr(neuro_mod.internal_utils, "get_path", lambda k: Path("/neuro"))
        neuro_mod.ruff.__wrapped__(ctx, ruff_args="--fix --select E")
        assert patch_subprocess.last_args == (["nenv/bin/ruff", "check", Path("/neuro"), "--fix", "--select", "E"],)

    def test_nonzero_exit_raises(self, ctx, monkeypatch):
        monkeypatch.setattr(neuro_mod.subprocess, "run", lambda args: SubprocessResult(1))
        with pytest.raises(SystemExit):
            neuro_mod.ruff.__wrapped__(ctx)


# ---------------------------------------------------------------------------
# test (the inner pytest runner)
# ---------------------------------------------------------------------------

class TestTest:
    def test_default_args(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx)
        assert patch_subprocess.last_args == (["nenv/bin/pytest", "neuro/tests"],)

    def test_custom_args(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx, pytest_args="-m 'not integration'")
        assert patch_subprocess.last_args == (["nenv/bin/pytest", "neuro/tests", "-m", "not integration"],)

    def test_exit_code_zero(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx)  # should not raise

    def test_nonzero_exit_raises(self, ctx, monkeypatch):
        monkeypatch.setattr(neuro_mod.subprocess, "run", lambda args: SubprocessResult(1))
        with pytest.raises(SystemExit):
            neuro_mod.test.__wrapped__(ctx)


# ---------------------------------------------------------------------------
# test_local
# ---------------------------------------------------------------------------

class TestTestLocal:
    def test_calls_rsync(self, ctx, patch_rsync, patch_nenv, patch_test):
        neuro_mod.test_local.__wrapped__(ctx)
        assert patch_rsync.call_count == 1
        assert patch_rsync.last_kwargs == {"components": ["neuro"]}

    def test_calls_nenv(self, ctx, patch_rsync, patch_nenv, patch_test):
        neuro_mod.test_local.__wrapped__(ctx)
        assert patch_nenv.call_count == 1

    def test_calls_test(self, ctx, patch_rsync, patch_nenv, patch_test):
        neuro_mod.test_local.__wrapped__(ctx)
        assert patch_test.call_count == 1

    def test_passes_pytest_args(self, ctx, patch_rsync, patch_nenv, patch_test):
        neuro_mod.test_local.__wrapped__(ctx, pytest_args="-k foo")
        assert patch_test.last_args[2] == "-k foo"


# ---------------------------------------------------------------------------
# test_branch
# ---------------------------------------------------------------------------

class TestTestBranch:
    def test_calls_branch(self, ctx, patch_branch, patch_test):
        neuro_mod.test_branch.__wrapped__(ctx, branch_name="feature/x")
        assert patch_branch.call_count == 1
        assert patch_branch.last_args[1] == "feature/x"
        assert patch_branch.last_kwargs == {"components": ["neuro"]}

    def test_calls_test(self, ctx, patch_branch, patch_test):
        neuro_mod.test_branch.__wrapped__(ctx, branch_name="dev")
        assert patch_test.call_count == 1

    def test_passes_pytest_args(self, ctx, patch_branch, patch_test):
        neuro_mod.test_branch.__wrapped__(ctx, branch_name="dev", pytest_args="-v")
        assert patch_test.last_args[2] == "-v"
