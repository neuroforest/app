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
def patch_test(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(neuro_mod, "test", rec)
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
# test
# ---------------------------------------------------------------------------

class TestTest:
    @pytest.fixture(autouse=True)
    def _patch_bundle(self, monkeypatch):
        monkeypatch.setattr(neuro_mod.tw5, "bundle", Recorder())

    def test_unit_mode(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx, mode="unit")
        args = patch_subprocess.last_args[0]
        assert "-m" in args
        assert "not (integration or e2e)" in args

    def test_integration_mode(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx, mode="integration")
        args = patch_subprocess.last_args[0]
        assert "-m" in args
        assert "not e2e" in args

    def test_e2e_mode(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx, mode="e2e")
        args = patch_subprocess.last_args[0]
        assert "-m" not in args

    def test_default_mode_is_integration(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx)
        args = patch_subprocess.last_args[0]
        assert "not e2e" in args

    def test_integration_bundles_tw5(self, ctx, patch_subprocess, monkeypatch):
        bundle_rec = Recorder()
        monkeypatch.setattr(neuro_mod.tw5, "bundle", bundle_rec)
        neuro_mod.test.__wrapped__(ctx, mode="integration")
        assert bundle_rec.call_count == 1

    def test_unit_skips_bundle(self, ctx, patch_subprocess, monkeypatch):
        bundle_rec = Recorder()
        monkeypatch.setattr(neuro_mod.tw5, "bundle", bundle_rec)
        neuro_mod.test.__wrapped__(ctx, mode="unit")
        assert bundle_rec.call_count == 0

    def test_unknown_mode(self, ctx):
        with pytest.raises(SystemExit):
            neuro_mod.test.__wrapped__(ctx, mode="bogus")

    def test_nonzero_exit_raises(self, ctx, monkeypatch):
        monkeypatch.setattr(neuro_mod.subprocess, "run", lambda *a: SubprocessResult(1))
        with pytest.raises(SystemExit):
            neuro_mod.test.__wrapped__(ctx, mode="unit")

    def test_passes_location_and_args(self, ctx, patch_subprocess):
        neuro_mod.test.__wrapped__(ctx, mode="unit", location="neuro/tests/core", pytest_args="-v")
        args = patch_subprocess.last_args[0]
        assert "neuro/tests/core" in args
        assert "-v" in args


# ---------------------------------------------------------------------------
# test_local
# ---------------------------------------------------------------------------

class TestTestLocal:
    def test_calls_rsync(self, ctx, patch_rsync, patch_test):
        neuro_mod.test_local.__wrapped__(ctx)
        assert patch_rsync.call_count == 1
        assert patch_rsync.last_kwargs == {"components": ["neuro"]}

    def test_default_mode_is_e2e(self, ctx, patch_rsync, patch_test):
        neuro_mod.test_local.__wrapped__(ctx)
        assert patch_test.last_args[1] == "e2e"

    def test_custom_mode(self, ctx, patch_rsync, patch_test):
        neuro_mod.test_local.__wrapped__(ctx, mode="unit")
        assert patch_test.last_args[1] == "unit"

    def test_passes_pytest_args(self, ctx, patch_rsync, patch_test):
        neuro_mod.test_local.__wrapped__(ctx, pytest_args="-k foo")
        assert patch_test.last_args[3] == "-k foo"


# ---------------------------------------------------------------------------
# test_branch
# ---------------------------------------------------------------------------

class TestTestBranch:
    def test_calls_branch(self, ctx, patch_branch, patch_test):
        neuro_mod.test_branch.__wrapped__(ctx, branch_name="feature/x")
        assert patch_branch.call_count == 1
        assert patch_branch.last_args[1] == "feature/x"
        assert patch_branch.last_kwargs == {"components": ["neuro"]}

    def test_default_mode_is_e2e(self, ctx, patch_branch, patch_test):
        neuro_mod.test_branch.__wrapped__(ctx, branch_name="dev")
        assert patch_test.last_args[1] == "e2e"

    def test_passes_pytest_args(self, ctx, patch_branch, patch_test):
        neuro_mod.test_branch.__wrapped__(ctx, branch_name="dev", pytest_args="-v")
        assert patch_test.last_args[3] == "-v"
