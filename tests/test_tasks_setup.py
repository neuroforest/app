"""
Tests for tasks.setup.
"""

import os

import pytest
from invoke.exceptions import Exit

import tasks.setup as setup_mod
from neuro.utils.test_utils import FakeContext, Recorder


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSetup:
    def test_prints_environment_and_dir(self, ctx, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        setup_mod.setup.__wrapped__(ctx, environment="TESTING")
        out = capsys.readouterr().out
        assert "TESTING" in out
        assert str(tmp_path) in out

    def test_sets_environment_variable(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        setup_mod.setup.__wrapped__(ctx, environment="TESTING")
        assert os.environ["ENVIRONMENT"] == "TESTING"

    def test_no_environment_does_not_set_var(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        setup_mod.setup.__wrapped__(ctx, environment=None)
        assert "ENVIRONMENT" not in os.environ

    def test_calls_config_main(self, ctx, monkeypatch, tmp_path):
        rec = Recorder()
        monkeypatch.setattr(setup_mod.config, "main", rec)
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        setup_mod.setup.__wrapped__(ctx)
        assert rec.call_count == 1

    def test_chdir_to_nf_dir(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setenv("NF_DIR", str(tmp_path))
        original = os.getcwd()
        try:
            setup_mod.setup.__wrapped__(ctx)
            assert os.getcwd() == str(tmp_path)
        finally:
            os.chdir(original)

    def test_raises_exit_on_bad_dir(self, ctx, monkeypatch):
        monkeypatch.setenv("NF_DIR", "/nonexistent/path/that/does/not/exist")
        with pytest.raises(Exit):
            setup_mod.setup.__wrapped__(ctx)
