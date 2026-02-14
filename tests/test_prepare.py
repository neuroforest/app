"""
Tests for bin/prepare.py

Logic:
    --local     -> rsync neuro + desktop from local repos
    --master    -> reset ALL submodules to default branch (from .gitmodules)
    --develop   -> reset only neuroforest submodules to develop
    --branch X  -> use X if exists on remote, otherwise fall back to default
"""

import importlib.util
import os
import sys

import pytest

from neuro.utils import test_utils


# -- Load module --

@pytest.fixture(scope="session")
def prepare():
    spec = importlib.util.spec_from_file_location(
        "prepare",
        os.path.join(os.path.dirname(__file__), "../bin/prepare.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prepare"] = mod
    spec.loader.exec_module(mod)
    return mod


# -- Tests --

class TestParseGitmodules:
    """Reads submodule paths, URLs, and branches from .gitmodules."""

    def test_parses_entries(self, prepare, tmp_path):
        (tmp_path / ".gitmodules").write_text(
            '[submodule "neuro"]\n'
            "\tpath = neuro\n"
            "\turl = https://github.com/neuroforest/neuro\n"
            "\tbranch = master\n"
        )
        os.chdir(tmp_path)
        result = prepare.parse_gitmodules()
        assert result["neuro"]["url"] == "https://github.com/neuroforest/neuro"
        assert result["neuro"]["branch"] == "master"

    def test_missing_branch_defaults_to_master(self, prepare, tmp_path):
        (tmp_path / ".gitmodules").write_text(
            '[submodule "lib"]\n'
            "\tpath = lib\n"
            "\turl = https://example.com/lib.git\n"
        )
        os.chdir(tmp_path)
        assert prepare.parse_gitmodules()["lib"]["branch"] == "master"


class TestParseArguments:
    """Maps CLI flags to (mode, arg) tuples."""

    def test_default_is_local(self, prepare, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prepare.py"])
        assert prepare.parse_arguments() == ("local", None)

    def test_master(self, prepare, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prepare.py", "-m"])
        assert prepare.parse_arguments() == ("master", None)

    def test_develop(self, prepare, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prepare.py", "--develop"])
        assert prepare.parse_arguments() == ("develop", None)

    def test_branch(self, prepare, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prepare.py", "-b", "feat-x"])
        assert prepare.parse_arguments() == ("branch", "feat-x")

    def test_branch_missing_name_exits(self, prepare, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prepare.py", "--branch"])
        with pytest.raises(SystemExit):
            prepare.parse_arguments()


class TestPrepareDevelop:
    """--develop only resets neuroforest-owned submodules, skips third-party."""

    def test_skips_third_party(self, prepare, monkeypatch):
        reset_calls = []
        monkeypatch.setattr(prepare, "reset_submodule", lambda p, b: reset_calls.append((p, b)))

        submodules = {
            "neuro": {"branch": "master"},
            "desktop": {"branch": "master"},
            "tw5": {"branch": "master"},  # third-party, should be skipped
        }
        prepare.prepare_develop(submodules)

        paths = [p for p, _ in reset_calls]
        assert "neuro" in paths
        assert "desktop" in paths
        assert "tw5" not in paths
        assert all(b == "develop" for _, b in reset_calls)


class TestBranchExistsOnRemote:
    """Checks remote for branch via git ls-remote."""

    def test_found(self, prepare, monkeypatch):
        monkeypatch.setattr(
            prepare.subprocess, "run",
            test_utils.fake_subprocess(0, "abc\trefs/heads/develop\n"),
        )
        assert prepare.branch_exists_on_remote("develop") is True

    def test_not_found(self, prepare, monkeypatch):
        monkeypatch.setattr(
            prepare.subprocess, "run",
            test_utils.fake_subprocess(0, ""),
        )
        assert prepare.branch_exists_on_remote("nope") is False


class TestRsyncLocal:
    """--local rsyncs with .gitignore filter and .git exclusion."""

    def test_rsync_flags(self, prepare, monkeypatch):
        calls = []
        monkeypatch.setattr(prepare.internal_utils, "get_path", lambda k: f"/mock/{k}")
        monkeypatch.setattr(prepare.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

        prepare.rsync_local("neuro")

        cmd = calls[0]
        assert "--filter=:- .gitignore" in cmd
        assert "--exclude=.git" in cmd
        assert "--delete" in cmd
        assert "/mock/neuro" in cmd
