"""
Tests for tasks.prepare.
"""

import json
import os

import pytest

import tasks.prepare as prepare_mod
from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(prepare_mod.terminal_style, "step", noop_step)


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
    monkeypatch.setattr(prepare_mod.internal_utils, "get_path", lambda k: paths[k])
    return paths


@pytest.fixture
def rsync_recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(prepare_mod.build_utils, "rsync_local", rec)
    return rec


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(prepare_mod.subprocess, "run", rec)
    return rec


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_local_submodules(self):
        assert prepare_mod.LOCAL_SUBMODULES == ["neuro", "desktop"]

    def test_submodules_contains_neuro(self):
        assert "neuro" in prepare_mod.SUBMODULES

    def test_submodules_contains_tw5(self):
        assert "tw5" in prepare_mod.SUBMODULES


# ---------------------------------------------------------------------------
# Tw5 validation
# ---------------------------------------------------------------------------

class TestTw5Validation:
    def _make_tw5(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        return prepare_mod.Tw5()

    def test_validate_edition_valid(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        edition_dir = tmp_path / "edition_a"
        edition_dir.mkdir()
        info = {"description": "x", "plugins": [], "themes": [], "build": {}}
        (edition_dir / "tiddlywiki.info").write_text(json.dumps(info))
        assert tw.validate_tw5_edition(str(edition_dir)) is True

    def test_validate_edition_missing_info_file(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        edition_dir = tmp_path / "edition_b"
        edition_dir.mkdir()
        assert tw.validate_tw5_edition(str(edition_dir)) is False

    def test_validate_edition_invalid_json(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        edition_dir = tmp_path / "edition_c"
        edition_dir.mkdir()
        (edition_dir / "tiddlywiki.info").write_text("{bad json")
        assert tw.validate_tw5_edition(str(edition_dir)) is False

    def test_validate_edition_missing_fields(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        edition_dir = tmp_path / "edition_d"
        edition_dir.mkdir()
        (edition_dir / "tiddlywiki.info").write_text(json.dumps({"description": "x"}))
        assert tw.validate_tw5_edition(str(edition_dir)) is False

    def test_validate_plugin_valid(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        info = {"title": "$:/plugins/test/foo", "description": "A plugin"}
        info_path = plugin_dir / "plugin.info"
        info_path.write_text(json.dumps(info))
        result = tw.validate_tw5_plugin(str(info_path))
        assert result == info

    def test_validate_plugin_invalid_json(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        plugin_dir = tmp_path / "badplugin"
        plugin_dir.mkdir()
        info_path = plugin_dir / "plugin.info"
        info_path.write_text("not json")
        assert tw.validate_tw5_plugin(str(info_path)) is None

    def test_validate_plugin_missing_fields(self, monkeypatch, tmp_path):
        tw = self._make_tw5(monkeypatch, tmp_path)
        plugin_dir = tmp_path / "incomp"
        plugin_dir.mkdir()
        info_path = plugin_dir / "plugin.info"
        info_path.write_text(json.dumps({"title": "x"}))
        assert tw.validate_tw5_plugin(str(info_path)) is None


class TestTw5Discover:
    def test_discover_finds_plugins(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        plugins = nf / "tw5-plugins"
        for d in (nf, tw5, plugins):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()

        p1 = plugins / "alpha"
        p1.mkdir()
        (p1 / "plugin.info").write_text(json.dumps({
            "title": "$:/plugins/nf/alpha", "description": "Alpha"
        }))
        p2 = plugins / "beta"
        p2.mkdir()
        (p2 / "plugin.info").write_text(json.dumps({
            "title": "$:/plugins/nf/beta", "description": "Beta"
        }))

        results = tw.discover_tw5_plugins()
        assert len(results) == 2
        titles = [info["title"] for _, info in results]
        assert titles == ["$:/plugins/nf/alpha", "$:/plugins/nf/beta"]

    def test_discover_skips_invalid(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        plugins = nf / "tw5-plugins"
        for d in (nf, tw5, plugins):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()

        bad = plugins / "bad"
        bad.mkdir()
        (bad / "plugin.info").write_text("not json")

        assert tw.discover_tw5_plugins() == []


class TestTw5CopyEditions:
    def test_copies_valid_editions(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        editions_src = nf / "tw5-editions"  # this matches the join in Tw5.__init__
        # But Tw5.__init__ does: os.path.join(get_path("nf"), "tw5-editions")
        # and copy_tw5_editions does: os.path.join(app_path, self.editions_dir)
        # where self.editions_dir = os.path.join(get_path("nf"), "tw5-editions")
        # and app_path = get_path("nf"), so it becomes nf/nf/tw5-editions — that's a bug in the source
        # but let's match the actual behavior
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()

        # editions_dir is os.path.join(str(nf), "tw5-editions")
        # copy_tw5_editions does os.path.join(get_path("nf"), self.editions_dir)
        # = os.path.join(str(nf), str(nf) + "/tw5-editions")
        # Since editions_dir is absolute, os.path.join returns the absolute path
        editions_source = tw.editions_dir
        os.makedirs(editions_source, exist_ok=True)

        ed = os.path.join(editions_source, "myedition")
        os.makedirs(ed)
        info = {"description": "x", "plugins": [], "themes": [], "build": {}}
        with open(os.path.join(ed, "tiddlywiki.info"), "w") as f:
            json.dump(info, f)

        (tw5 / "editions").mkdir(exist_ok=True)
        tw.copy_tw5_editions()

        target = tw5 / "editions" / "myedition" / "tiddlywiki.info"
        assert target.exists()

    def test_skips_when_no_editions_dir(self, monkeypatch, tmp_path, capsys):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()
        tw.copy_tw5_editions()
        out = capsys.readouterr().out
        assert "No editions directory" in out


class TestTw5CopyPlugins:
    def test_copies_plugins(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        plugins_src = nf / "tw5-plugins"
        for d in (nf, tw5, plugins_src):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()

        p = plugins_src / "myplugin"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({
            "title": "$:/plugins/nf/myplugin",
            "description": "My plugin",
        }))
        (p / "somefile.tid").write_text("content")

        (tw5 / "plugins").mkdir(exist_ok=True)
        tw.copy_tw5_plugins()

        target = tw5 / "plugins" / "nf" / "myplugin" / "somefile.tid"
        assert target.exists()

    def test_copies_theme_to_themes_dir(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        plugins_src = nf / "tw5-plugins"
        for d in (nf, tw5, plugins_src):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()

        p = plugins_src / "mytheme"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({
            "title": "$:/themes/nf/mytheme",
            "description": "A theme",
            "plugin-type": "theme",
        }))

        (tw5 / "themes").mkdir(exist_ok=True)
        tw.copy_tw5_plugins()

        assert (tw5 / "themes" / "nf" / "mytheme" / "plugin.info").exists()

    def test_skips_when_no_plugins_dir(self, monkeypatch, tmp_path, capsys):
        nf = tmp_path / "nf_empty"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw = prepare_mod.Tw5()
        tw.copy_tw5_plugins()
        out = capsys.readouterr().out
        assert "No plugins directory" in out


# ---------------------------------------------------------------------------
# Nwjs
# ---------------------------------------------------------------------------

class TestNwjs:
    def _make_nwjs(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        nf.mkdir(exist_ok=True)
        monkeypatch.setattr(prepare_mod.internal_utils, "get_path", lambda k: str(nf))
        return prepare_mod.Nwjs(version="0.80.0", url="https://example.com")

    def test_init_paths(self, monkeypatch, tmp_path):
        nw = self._make_nwjs(monkeypatch, tmp_path)
        assert nw.version == "0.80.0"
        assert "v0.80.0.tar.gz" in nw.tarfile_local
        assert "nwjs-sdk-v0.80.0-linux-x64.tar.gz" in nw.tarfile_remote

    def test_download_cached(self, monkeypatch, tmp_path, capsys):
        nw = self._make_nwjs(monkeypatch, tmp_path)
        os.makedirs(nw.nwjs_dir, exist_ok=True)
        with open(nw.tarfile_local, "w") as f:
            f.write("fake")
        nw.download()
        out = capsys.readouterr().out
        assert "cached" in out

    def test_download_overwrite_removes_old(self, monkeypatch, tmp_path,
                                            subprocess_recorder):
        nw = self._make_nwjs(monkeypatch, tmp_path)
        nw.overwrite = True
        os.makedirs(nw.nwjs_dir, exist_ok=True)
        with open(nw.tarfile_local, "w") as f:
            f.write("old")
        nw.download()
        # wget was called
        assert subprocess_recorder.call_count == 1
        cmd = subprocess_recorder.calls[0][0][0]
        assert "wget" in cmd

    def test_download_creates_dir(self, monkeypatch, tmp_path,
                                  subprocess_recorder):
        nw = self._make_nwjs(monkeypatch, tmp_path)
        nw.download()
        assert os.path.isdir(nw.nwjs_dir)

    def test_extract_cached(self, monkeypatch, tmp_path, capsys):
        nw = self._make_nwjs(monkeypatch, tmp_path)
        os.makedirs(nw.extract_final, exist_ok=True)
        nw.extract()
        out = capsys.readouterr().out
        assert "cached" in out

    def test_extract_runs_tar(self, monkeypatch, tmp_path, subprocess_recorder):
        nw = self._make_nwjs(monkeypatch, tmp_path)
        nw.overwrite = True
        # Create extract_temp so os.rename works
        os.makedirs(nw.nwjs_dir, exist_ok=True)
        os.makedirs(nw.extract_temp, exist_ok=True)
        nw.extract()
        assert subprocess_recorder.call_count == 1
        cmd = subprocess_recorder.calls[0][0][0]
        assert "tar" in cmd


# ---------------------------------------------------------------------------
# reset_submodule
# ---------------------------------------------------------------------------

class TestResetSubmodule:
    def test_runs_git_commands(self, monkeypatch, tmp_path, subprocess_recorder):
        monkeypatch.setattr(prepare_mod.build_utils, "chdir", _noop_chdir)
        prepare_mod.reset_submodule(str(tmp_path), "main")
        assert subprocess_recorder.call_count == 3
        cmds = [c[0][0] for c in subprocess_recorder.calls]
        assert cmds[0] == ["git", "fetch", "origin"]
        assert cmds[1] == ["git", "reset", "--hard", "origin/main"]
        assert cmds[2] == ["git", "clean", "-fdx"]


from contextlib import contextmanager

@contextmanager
def _noop_chdir(path):
    yield


# ---------------------------------------------------------------------------
# Task: rsync
# ---------------------------------------------------------------------------

class TestRsyncTask:
    def test_defaults_to_local_submodules(self, ctx, patch_get_path, rsync_recorder):
        prepare_mod.rsync.__wrapped__(ctx, modules=[])
        assert rsync_recorder.call_count == len(prepare_mod.LOCAL_SUBMODULES)

    def test_specific_module(self, ctx, patch_get_path, rsync_recorder):
        prepare_mod.rsync.__wrapped__(ctx, modules=["neuro"])
        assert rsync_recorder.call_count == 1
        args = rsync_recorder.last_args
        assert args[2] == "neuro"


# ---------------------------------------------------------------------------
# Task: master / develop
# ---------------------------------------------------------------------------

class TestMasterTask:
    def test_resets_all_submodules(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setattr(prepare_mod.build_utils, "chdir", _noop_chdir)
        prepare_mod.master.__wrapped__(ctx, submodules=[])
        # 3 git commands per submodule
        assert subprocess_recorder.call_count == 3 * len(prepare_mod.SUBMODULES)

    def test_specific_submodule(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setattr(prepare_mod.build_utils, "chdir", _noop_chdir)
        prepare_mod.master.__wrapped__(ctx, submodules=["neuro"])
        assert subprocess_recorder.call_count == 3


class TestDevelopTask:
    def test_resets_to_develop(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setattr(prepare_mod.build_utils, "chdir", _noop_chdir)
        prepare_mod.develop.__wrapped__(ctx, submodules=["neuro"])
        reset_cmd = subprocess_recorder.calls[1][0][0]
        assert "origin/develop" in reset_cmd


class TestBranchTask:
    def test_resets_to_given_branch(self, ctx, monkeypatch, subprocess_recorder):
        monkeypatch.setattr(prepare_mod.build_utils, "chdir", _noop_chdir)
        prepare_mod.branch.__wrapped__(ctx, branch_name="feat/x", submodules=["neuro"])
        reset_cmd = subprocess_recorder.calls[1][0][0]
        assert "origin/feat/x" in reset_cmd
