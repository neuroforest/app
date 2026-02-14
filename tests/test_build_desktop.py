"""
Tests for bin/build_desktop.py

Logic:
    Assembles NW.js SDK, TW5, and desktop source into a build directory.
    copy_nwjs: rsyncs NW.js SDK, fails gracefully if not found.
    copy_tw5: rsyncs TW5, removes .git directory.
    copy_source: rsyncs source, moves package.json to build root.
    install_node_modules: runs npm install in build directory.
"""

import importlib.util
import os
import sys

import pytest

from neuro.utils import internal_utils


# -- Load module --

@pytest.fixture(scope="session")
def desktop():
    spec = importlib.util.spec_from_file_location(
        "build_desktop",
        os.path.join(internal_utils.get_path("app"), "bin/build_desktop.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_desktop"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mock_paths(desktop, tmp_path, monkeypatch):
    (tmp_path / "desktop" / "nwjs" / "v0.90.0").mkdir(parents=True)
    (tmp_path / "desktop" / "source").mkdir(parents=True)
    (tmp_path / "desktop" / "source" / "package.json").write_text("{}")
    (tmp_path / "desktop" / "source" / "main.js").write_text("//main")
    (tmp_path / "tw5" / ".git").mkdir(parents=True)
    (tmp_path / "tw5" / "tiddlywiki.js").write_text("//tw5")
    monkeypatch.setenv("NWJS_VERSION", "0.90.0")
    monkeypatch.setattr(desktop.internal_utils, "get_path", lambda k: {
        "app": str(tmp_path),
        "tw5": str(tmp_path / "tw5"),
    }[k])
    return tmp_path


# -- Tests --

class TestCopyNwjs:
    """copy_nwjs() rsyncs NW.js SDK into build directory."""

    def test_copies(self, desktop, mock_paths, monkeypatch):
        build_dir = str(mock_paths / "build")
        os.makedirs(build_dir)
        calls = []
        monkeypatch.setattr(desktop.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        result = desktop.copy_nwjs(build_dir)
        assert result is True
        assert calls[0][0] == "rsync"
        assert "v0.90.0/" in calls[0][3]

    def test_fails_when_missing(self, desktop, mock_paths, capsys):
        build_dir = str(mock_paths / "build")
        os.makedirs(build_dir)
        os.environ["NWJS_VERSION"] = "9.9.9"
        result = desktop.copy_nwjs(build_dir)
        assert result is False
        assert "not found" in capsys.readouterr().out


class TestCopyTw5:
    """copy_tw5() rsyncs TW5 and removes .git."""

    def test_copies_and_removes_git(self, desktop, mock_paths, monkeypatch):
        build_dir = str(mock_paths / "build")
        os.makedirs(build_dir)

        def fake_run(cmd, **kw):
            tw5_target = os.path.join(build_dir, "tw5")
            os.makedirs(os.path.join(tw5_target, ".git"), exist_ok=True)

        monkeypatch.setattr(desktop.subprocess, "run", fake_run)
        desktop.copy_tw5(build_dir)
        assert not os.path.isdir(os.path.join(build_dir, "tw5", ".git"))


class TestCopySource:
    """copy_source() rsyncs source and moves package.json."""

    def test_moves_package_json(self, desktop, mock_paths, monkeypatch):
        build_dir = str(mock_paths / "build")
        os.makedirs(build_dir)

        def fake_run(cmd, **kw):
            source_target = os.path.join(build_dir, "source")
            os.makedirs(source_target, exist_ok=True)
            open(os.path.join(source_target, "package.json"), "w").close()

        monkeypatch.setattr(desktop.subprocess, "run", fake_run)
        desktop.copy_source(build_dir)
        assert os.path.isfile(os.path.join(build_dir, "package.json"))
        assert not os.path.isfile(os.path.join(build_dir, "source", "package.json"))


class TestInstallNodeModules:
    """install_node_modules() runs npm install in build directory."""

    def test_runs_npm(self, desktop, mock_paths, monkeypatch):
        build_dir = str(mock_paths / "build")
        calls = []
        monkeypatch.setattr(desktop.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
        desktop.install_node_modules(build_dir)
        assert calls[0][0][0] == "npm"
        assert calls[0][1]["cwd"] == build_dir
