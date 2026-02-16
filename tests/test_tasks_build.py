"""
Tests for tasks.build.
"""

import json
import os

import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step

import tasks.build as build_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()

@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(build_mod.terminal_style, "step", noop_step)


@pytest.fixture
def rsync_recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(build_mod.build_utils, "rsync_local", rec)
    return rec


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(build_mod.subprocess, "run", rec)
    return rec


# ---------------------------------------------------------------------------
# neurobase
# ---------------------------------------------------------------------------

class TestNeurobase:
    def test_already_running(self, ctx, monkeypatch, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(build_mod.docker_tools, "container_running", lambda n: True)
        build_mod.neurobase.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "is running" in out

    def test_exists_but_stopped(self, ctx, monkeypatch, subprocess_recorder, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(build_mod.docker_tools, "container_running", lambda n: False)
        monkeypatch.setattr(build_mod.docker_tools, "container_exists", lambda n: True)
        build_mod.neurobase.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "Starting existing" in out
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "start", "nb"]

    def test_does_not_exist(self, ctx, monkeypatch, subprocess_recorder, capsys):
        monkeypatch.setenv("BASE_NAME", "nb")
        monkeypatch.setattr(build_mod.docker_tools, "container_running", lambda n: False)
        monkeypatch.setattr(build_mod.docker_tools, "container_exists", lambda n: False)
        build_mod.neurobase.__wrapped__(ctx)
        out = capsys.readouterr().out
        assert "Creating" in out
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["docker", "compose", "up", "-d"]


# ---------------------------------------------------------------------------
# desktop
# ---------------------------------------------------------------------------

class TestDesktop:
    def _setup_desktop(self, monkeypatch, tmp_path):
        """Common setup: stub get_path, env vars, bool_prompt, shutil.rmtree."""
        nf = tmp_path / "nf"
        nf.mkdir()
        monkeypatch.setattr(build_mod.internal_utils, "get_path", lambda k: str(nf))
        monkeypatch.setenv("NWJS_VERSION", "0.80.0")
        monkeypatch.setenv("APP_NAME", "TestApp")
        # Always stub the prompt so it never reads stdin
        monkeypatch.setattr(build_mod.terminal_components, "bool_prompt", lambda msg: True)
        # Stub rmtree so source/package.json survives the "rewrite" path
        monkeypatch.setattr(build_mod.shutil, "rmtree", lambda *a, **kw: None)
        return nf

    def _make_source_pkg(self, build_dir, content=None):
        if content is None:
            content = {"name": "placeholder"}
        source_dir = os.path.join(build_dir, "source")
        os.makedirs(source_dir, exist_ok=True)
        with open(os.path.join(source_dir, "package.json"), "w") as f:
            json.dump(content, f)

    def test_rsyncs_nwjs_tw5_desktop(self, ctx, monkeypatch, tmp_path,
                                      rsync_recorder, subprocess_recorder):
        self._setup_desktop(monkeypatch, tmp_path)
        build_dir = str(tmp_path / "build")
        self._make_source_pkg(build_dir)

        build_mod.desktop.__wrapped__(ctx, build_dir=build_dir)

        assert rsync_recorder.call_count == 3
        names = [c[0][2] for c in rsync_recorder.calls]
        assert "NW.js v0.80.0" in names
        assert "tw5" in names
        assert "desktop source" in names

    def test_writes_package_json_with_app_name(self, ctx, monkeypatch, tmp_path,
                                                rsync_recorder, subprocess_recorder):
        self._setup_desktop(monkeypatch, tmp_path)
        build_dir = str(tmp_path / "build")
        self._make_source_pkg(build_dir, {"name": "placeholder", "version": "1.0"})

        build_mod.desktop.__wrapped__(ctx, build_dir=build_dir)

        with open(os.path.join(build_dir, "package.json")) as f:
            pkg = json.load(f)
        assert pkg["name"] == "TestApp"
        assert pkg["version"] == "1.0"

    def test_runs_npm_install(self, ctx, monkeypatch, tmp_path,
                               rsync_recorder, subprocess_recorder):
        self._setup_desktop(monkeypatch, tmp_path)
        build_dir = str(tmp_path / "build")
        self._make_source_pkg(build_dir)

        build_mod.desktop.__wrapped__(ctx, build_dir=build_dir)

        npm_calls = [c for c in subprocess_recorder.calls
                     if c[0][0] == ["npm", "install"]]
        assert len(npm_calls) == 1
        assert npm_calls[0][1]["cwd"] == build_dir

    def test_prompts_on_existing_dir(self, ctx, monkeypatch, tmp_path,
                                      rsync_recorder, subprocess_recorder):
        self._setup_desktop(monkeypatch, tmp_path)
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._make_source_pkg(str(build_dir))

        prompted = []
        monkeypatch.setattr(build_mod.terminal_components, "bool_prompt",
                            lambda msg: (prompted.append(msg), True)[1])

        build_mod.desktop.__wrapped__(ctx, build_dir=str(build_dir))
        assert len(prompted) == 1
        assert "Rewrite" in prompted[0]
        assert rsync_recorder.call_count == 3

    def test_default_build_dir(self, ctx, monkeypatch, tmp_path,
                                rsync_recorder, subprocess_recorder):
        nf = self._setup_desktop(monkeypatch, tmp_path)
        build_dir = os.path.join(str(nf), "app")
        self._make_source_pkg(build_dir)

        build_mod.desktop.__wrapped__(ctx, build_dir=None)
        assert rsync_recorder.call_count == 3
