"""
Tests for tasks.setup.
"""

import os
from contextlib import contextmanager

import pytest
import invoke

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step

import tasks.actions.setup as setup_mod


@contextmanager
def _noop_chdir(path):
    yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr(setup_mod.config, "main", Recorder())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(setup_mod.terminal_style, "step", noop_step)


@pytest.fixture
def patch_get_path(monkeypatch, tmp_path):
    """Provide real tmp dirs for nf and tw5 so file operations work."""
    nf = tmp_path / "nf"
    tw5 = tmp_path / "tw5"
    neuro = tmp_path / "neuro"
    desktop = tmp_path / "desktop"
    for d in (nf, tw5, neuro, desktop):
        d.mkdir()
    paths = {
        "nf": str(nf),
        "tw5": str(tw5),
        "neuro": str(neuro),
        "desktop": str(desktop),
    }
    monkeypatch.setattr(setup_mod.internal_utils, "get_path", lambda k: paths[k])
    return paths


@pytest.fixture
def rsync_recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(setup_mod.build_utils, "rsync_local", rec)
    return rec


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(setup_mod.subprocess, "run", rec)
    return rec


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------

class TestEnv:
    def test_prints_environment_and_dir(self, ctx, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        setup_mod.env.__wrapped__(ctx, environment="TESTING")
        out = capsys.readouterr().out
        assert "TESTING" in out
        assert str(tmp_path) in out

    def test_sets_environment_variable(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        setup_mod.env.__wrapped__(ctx, environment="TESTING")
        assert os.environ["ENVIRONMENT"] == "TESTING"

    def test_no_environment_param_keeps_existing(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        monkeypatch.setenv("ENVIRONMENT", "PRODUCTION")
        setup_mod.env.__wrapped__(ctx, environment=None)
        assert os.environ["ENVIRONMENT"] == "PRODUCTION"

    def test_calls_config_main(self, ctx, monkeypatch, tmp_path):
        rec = Recorder()
        monkeypatch.setattr(setup_mod.config, "main", rec)
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        monkeypatch.setenv("ENVIRONMENT", "TESTING")
        setup_mod.env.__wrapped__(ctx)
        assert rec.call_count == 1

    def test_chdir_to_nf_dir(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        monkeypatch.setenv("ENVIRONMENT", "TESTING")
        original = os.getcwd()
        try:
            setup_mod.env.__wrapped__(ctx)
            assert os.getcwd() == str(tmp_path)
        finally:
            os.chdir(original)

    def test_raises_exit_on_bad_dir(self, ctx, monkeypatch):
        bad_path = "/nonexistent/path/that/does/not/exist"
        monkeypatch.setattr(setup_mod.internal_utils, "get_path", lambda k: bad_path)
        monkeypatch.setenv("ENVIRONMENT", "TESTING")
        with pytest.raises(invoke.exceptions.Exit):
            setup_mod.env.__wrapped__(ctx)


# ---------------------------------------------------------------------------
# Task: nenv
# ---------------------------------------------------------------------------

class TestNenvTask:
    def test_creates_venv_and_installs(self, ctx, subprocess_recorder):
        setup_mod.nenv.__wrapped__(ctx)
        assert subprocess_recorder.call_count == 2
        cmds = [c[0][0] for c in subprocess_recorder.calls]
        assert cmds[0] == ["python3", "-m", "venv", "nenv"]
        assert cmds[1] == ["nenv/bin/pip", "install", "./neuro"]

    def test_passes_check_true(self, ctx, subprocess_recorder):
        setup_mod.nenv.__wrapped__(ctx)
        for call in subprocess_recorder.calls:
            assert call[1].get("check") is True


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_local_submodules(self):
        assert setup_mod.LOCAL_SUBMODULES == ["neuro", "desktop"]

    def test_submodules_contains_neuro(self):
        assert "neuro" in setup_mod.SUBMODULES

    def test_submodules_contains_tw5(self):
        assert "tw5" in setup_mod.SUBMODULES


# ---------------------------------------------------------------------------
# Task: rsync
# ---------------------------------------------------------------------------

class TestRsyncTask:
    @pytest.fixture(autouse=True)
    def _patch_nenv(self, monkeypatch):
        monkeypatch.setattr(setup_mod, "nenv", Recorder())

    def test_defaults_to_local_submodules(self, ctx, patch_get_path, rsync_recorder):
        setup_mod.rsync.__wrapped__(ctx, components=[])
        assert rsync_recorder.call_count == len(setup_mod.LOCAL_SUBMODULES)

    def test_specific_module(self, ctx, patch_get_path, rsync_recorder):
        setup_mod.rsync.__wrapped__(ctx, components=["neuro"])
        assert rsync_recorder.call_count == 1
        args = rsync_recorder.last_args
        assert args[2] == "neuro"


# ---------------------------------------------------------------------------
# reset_submodule
# ---------------------------------------------------------------------------

class TestResetSubmodule:
    def test_runs_git_commands(self, monkeypatch, tmp_path, subprocess_recorder):
        monkeypatch.setattr(setup_mod.build_utils, "chdir", _noop_chdir)
        setup_mod.reset_submodule(str(tmp_path), "main")
        assert subprocess_recorder.call_count == 3
        cmds = [c[0][0] for c in subprocess_recorder.calls]
        assert cmds[0] == ["git", "rev-parse", "--short", "main"]
        assert cmds[1] == ["git", "reset", "--hard", "main"]
        assert cmds[2] == ["git", "clean", "-fdx"]


class TestBranchTask:
    def test_resets_to_given_branch(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setattr(setup_mod.build_utils, "chdir", _noop_chdir)
        setup_mod.branch.__wrapped__(ctx, branch_name="feat/x", components=["neuro"])
        reset_cmd = subprocess_recorder.calls[1][0][0]
        assert "feat/x" in reset_cmd
