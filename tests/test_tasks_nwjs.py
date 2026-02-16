"""
Tests for tasks.components.nwjs.
"""

import os

import pytest

import tasks.components.nwjs as nwjs_mod
from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(nwjs_mod.terminal_style, "step", noop_step)


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(nwjs_mod.subprocess, "run", rec)
    return rec


@pytest.fixture
def patch_paths(monkeypatch, tmp_path):
    """Patch get_path and NWJS_URL so _nwjs_paths works."""
    nf = tmp_path / "nf"
    nf.mkdir()
    monkeypatch.setattr(nwjs_mod.internal_utils, "get_path", lambda k: str(nf))
    monkeypatch.setenv("NWJS_URL", "https://example.com")
    return str(nf)


# ---------------------------------------------------------------------------
# _resolve_version
# ---------------------------------------------------------------------------

class TestResolveVersion:
    def test_explicit_version(self):
        assert nwjs_mod._resolve_version("1.2.3") == "1.2.3"

    def test_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("NWJS_VERSION", "0.80.0")
        assert nwjs_mod._resolve_version(None) == "0.80.0"


# ---------------------------------------------------------------------------
# _nwjs_paths
# ---------------------------------------------------------------------------

class TestNwjsPaths:
    def test_paths(self, patch_paths):
        p = nwjs_mod._nwjs_paths("0.80.0")
        assert "v0.80.0.tar.gz" in p["tarfile_local"]
        assert "nwjs-sdk-v0.80.0-linux-x64.tar.gz" in p["tarfile_remote"]
        assert p["extract_final"].endswith("v0.80.0")


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

class TestDownload:
    def test_cached(self, ctx, patch_paths, capsys):
        p = nwjs_mod._nwjs_paths("0.80.0")
        os.makedirs(p["nwjs_dir"], exist_ok=True)
        with open(p["tarfile_local"], "w") as f:
            f.write("fake")
        nwjs_mod.download.__wrapped__(ctx, version="0.80.0")
        out = capsys.readouterr().out
        assert "cached" in out

    def test_overwrite_removes_old(self, ctx, patch_paths, subprocess_recorder):
        p = nwjs_mod._nwjs_paths("0.80.0")
        os.makedirs(p["nwjs_dir"], exist_ok=True)
        with open(p["tarfile_local"], "w") as f:
            f.write("old")
        nwjs_mod.download.__wrapped__(ctx, version="0.80.0", overwrite=True)
        assert subprocess_recorder.call_count == 1
        cmd = subprocess_recorder.calls[0][0][0]
        assert "wget" in cmd

    def test_creates_dir(self, ctx, patch_paths, subprocess_recorder):
        p = nwjs_mod._nwjs_paths("0.80.0")
        nwjs_mod.download.__wrapped__(ctx, version="0.80.0")
        assert os.path.isdir(p["nwjs_dir"])


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

class TestExtract:
    def test_cached(self, ctx, patch_paths, capsys):
        p = nwjs_mod._nwjs_paths("0.80.0")
        os.makedirs(p["extract_final"], exist_ok=True)
        nwjs_mod.extract.__wrapped__(ctx, version="0.80.0")
        out = capsys.readouterr().out
        assert "cached" in out

    def test_runs_tar(self, ctx, patch_paths, subprocess_recorder):
        p = nwjs_mod._nwjs_paths("0.80.0")
        os.makedirs(p["nwjs_dir"], exist_ok=True)
        os.makedirs(p["extract_temp"], exist_ok=True)
        nwjs_mod.extract.__wrapped__(ctx, version="0.80.0", overwrite=True)
        assert subprocess_recorder.call_count == 1
        cmd = subprocess_recorder.calls[0][0][0]
        assert "tar" in cmd
