"""
Tests for bin/nwjs.py

Logic:
    Downloads NW.js SDK tarball via wget.
    Extracts tarball and renames to versioned directory.
    Skips download/extract when cached files exist (unless overwrite).
"""

import importlib.util
import os
import sys

import pytest

from neuro.utils import internal_utils


# -- Load module --

@pytest.fixture(scope="session")
def nwjs():
    spec = importlib.util.spec_from_file_location(
        "nwjs",
        os.path.join(internal_utils.get_path("app"), "bin/nwjs.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nwjs"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mock_nwjs(nwjs, tmp_path, monkeypatch):
    monkeypatch.setattr(nwjs.internal_utils, "get_path", lambda k: str(tmp_path))
    obj = nwjs.Nwjs(version="0.90.0", url="https://example.com")
    return obj


# -- Tests --

class TestInit:
    """Nwjs.__init__() sets up paths from version and app_path."""

    def test_paths(self, mock_nwjs, tmp_path):
        assert mock_nwjs.nwjs_dir == os.path.join(str(tmp_path), "desktop", "nwjs")
        assert mock_nwjs.tarfile_local.endswith("v0.90.0.tar.gz")
        assert "nwjs-sdk-v0.90.0-linux-x64.tar.gz" in mock_nwjs.tarfile_remote
        assert mock_nwjs.extract_final.endswith("v0.90.0")


class TestDownload:
    """download() calls wget or skips when cached."""

    def test_downloads_when_no_cache(self, nwjs, mock_nwjs, monkeypatch):
        calls = []
        monkeypatch.setattr(nwjs.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        mock_nwjs.download()
        assert len(calls) == 1
        assert calls[0][0] == "wget"
        assert mock_nwjs.tarfile_remote in calls[0]
        assert os.path.isdir(mock_nwjs.nwjs_dir)

    def test_skips_when_cached(self, nwjs, mock_nwjs, monkeypatch, capsys):
        os.makedirs(mock_nwjs.nwjs_dir, exist_ok=True)
        open(mock_nwjs.tarfile_local, "w").close()
        calls = []
        monkeypatch.setattr(nwjs.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        mock_nwjs.download()
        assert calls == []
        assert "(cached)" in capsys.readouterr().out

    def test_redownloads_when_overwrite(self, nwjs, mock_nwjs, monkeypatch):
        os.makedirs(mock_nwjs.nwjs_dir, exist_ok=True)
        open(mock_nwjs.tarfile_local, "w").close()
        mock_nwjs.overwrite = True
        calls = []
        monkeypatch.setattr(nwjs.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        mock_nwjs.download()
        assert len(calls) == 1
        assert not os.path.isfile(mock_nwjs.tarfile_local)


class TestExtract:
    """extract() calls tar or skips when cached."""

    def test_extracts(self, nwjs, mock_nwjs, monkeypatch):
        mock_nwjs.overwrite = True
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "tar":
                os.makedirs(mock_nwjs.extract_temp, exist_ok=True)

        monkeypatch.setattr(nwjs.subprocess, "run", fake_run)
        mock_nwjs.extract()
        assert len(calls) == 1
        assert calls[0][0] == "tar"
        assert os.path.isdir(mock_nwjs.extract_final)

    def test_skips_when_cached(self, nwjs, mock_nwjs, monkeypatch, capsys):
        os.makedirs(mock_nwjs.extract_final, exist_ok=True)
        calls = []
        monkeypatch.setattr(nwjs.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        mock_nwjs.extract()
        assert calls == []
        assert "(cached)" in capsys.readouterr().out

    def test_replaces_when_overwrite(self, nwjs, mock_nwjs, monkeypatch):
        os.makedirs(mock_nwjs.extract_final, exist_ok=True)
        (mock_nwjs.extract_final + "/old_file").replace("/", os.sep)
        mock_nwjs.overwrite = True
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "tar":
                os.makedirs(mock_nwjs.extract_temp, exist_ok=True)

        monkeypatch.setattr(nwjs.subprocess, "run", fake_run)
        mock_nwjs.extract()
        assert len(calls) == 1
        assert os.path.isdir(mock_nwjs.extract_final)
