"""
Tests for tasks.components.tw5.
"""

import json
from pathlib import Path

import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step

import tasks.components.tw5 as tw5_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(tw5_mod.terminal_style, "step", noop_step)


@pytest.fixture(autouse=True)
def _patch_header(monkeypatch):
    monkeypatch.setattr(tw5_mod.terminal_style, "header", lambda t: None)


@pytest.fixture
def nf_tree(monkeypatch, tmp_path):
    """Create nf/tw5 dirs and patch get_path."""
    nf = tmp_path / "nf"
    tw5 = tmp_path / "tw5"
    nf.mkdir()
    tw5.mkdir()
    paths = {"nf": nf, "tw5": tw5}
    monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: paths[k])
    return paths


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(tw5_mod.subprocess, "run", rec)
    return rec


@pytest.fixture
def patch_bundle(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(tw5_mod, "bundle", rec)
    return rec


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateEdition:
    def test_valid(self, tmp_path):
        ed = tmp_path / "myedition"
        ed.mkdir()
        info = {"description": "x", "plugins": [], "themes": [], "build": {}}
        (ed / "tiddlywiki.info").write_text(json.dumps(info))
        assert tw5_mod.validate_tw5_edition(str(ed)) is True

    def test_missing_info_file(self, tmp_path):
        ed = tmp_path / "myedition"
        ed.mkdir()
        assert tw5_mod.validate_tw5_edition(str(ed)) is False

    def test_invalid_json(self, tmp_path):
        ed = tmp_path / "myedition"
        ed.mkdir()
        (ed / "tiddlywiki.info").write_text("{bad")
        assert tw5_mod.validate_tw5_edition(str(ed)) is False

    def test_missing_fields(self, tmp_path):
        ed = tmp_path / "myedition"
        ed.mkdir()
        (ed / "tiddlywiki.info").write_text(json.dumps({"description": "x"}))
        assert tw5_mod.validate_tw5_edition(str(ed)) is False


class TestValidatePlugin:
    def test_valid(self, tmp_path):
        p = tmp_path / "myplugin"
        p.mkdir()
        info = {"title": "$:/plugins/nf/foo", "description": "Foo"}
        (p / "plugin.info").write_text(json.dumps(info))
        assert tw5_mod.validate_tw5_plugin(str(p / "plugin.info")) == info

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "myplugin"
        p.mkdir()
        (p / "plugin.info").write_text("not json")
        assert tw5_mod.validate_tw5_plugin(str(p / "plugin.info")) is None

    def test_missing_fields(self, tmp_path):
        p = tmp_path / "myplugin"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({"title": "x"}))
        assert tw5_mod.validate_tw5_plugin(str(p / "plugin.info")) is None


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------

class TestDiscover:
    def test_finds_and_sorts(self, nf_tree, tmp_path):
        plugins = tmp_path / "nf" / "tw5-plugins"
        plugins.mkdir()
        for name in ("beta", "alpha"):
            p = plugins / name
            p.mkdir()
            (p / "plugin.info").write_text(json.dumps({
                "title": f"$:/plugins/nf/{name}", "description": name,
            }))
        results = tw5_mod.discover_tw5_plugins()
        titles = [info["title"] for _, info in results]
        assert titles == ["$:/plugins/nf/alpha", "$:/plugins/nf/beta"]

    def test_skips_invalid(self, nf_tree, tmp_path):
        plugins = tmp_path / "nf" / "tw5-plugins"
        plugins.mkdir()
        bad = plugins / "bad"
        bad.mkdir()
        (bad / "plugin.info").write_text("not json")
        assert tw5_mod.discover_tw5_plugins() == []


# ---------------------------------------------------------------------------
# Copy editions
# ---------------------------------------------------------------------------

class TestCopyEditions:
    def test_copies_valid_edition(self, nf_tree, tmp_path):
        editions_src = tmp_path / "nf" / "tw5-editions"
        editions_src.mkdir()
        ed = editions_src / "myedition"
        ed.mkdir()
        info = {"description": "x", "plugins": [], "themes": [], "build": {}}
        (ed / "tiddlywiki.info").write_text(json.dumps(info))
        (tmp_path / "tw5" / "editions").mkdir()

        tw5_mod.copy_tw5_editions()
        assert (tmp_path / "tw5" / "editions" / "myedition" / "tiddlywiki.info").exists()

    def test_no_editions_dir(self, nf_tree, capsys):
        tw5_mod.copy_tw5_editions()
        assert "No editions directory" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Copy plugins
# ---------------------------------------------------------------------------

class TestCopyPlugins:
    def test_copies_plugin(self, nf_tree, tmp_path):
        plugins_src = tmp_path / "nf" / "tw5-plugins"
        plugins_src.mkdir()
        p = plugins_src / "myplugin"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({
            "title": "$:/plugins/nf/myplugin", "description": "My plugin",
        }))
        (p / "somefile.tid").write_text("content")
        (tmp_path / "tw5" / "plugins").mkdir()

        tw5_mod.copy_tw5_plugins()
        assert (tmp_path / "tw5" / "plugins" / "nf" / "myplugin" / "somefile.tid").exists()

    def test_copies_theme_to_themes_dir(self, nf_tree, tmp_path):
        plugins_src = tmp_path / "nf" / "tw5-plugins"
        plugins_src.mkdir()
        p = plugins_src / "mytheme"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({
            "title": "$:/themes/nf/mytheme", "description": "A theme",
            "plugin-type": "theme",
        }))
        (tmp_path / "tw5" / "themes").mkdir()

        tw5_mod.copy_tw5_plugins()
        assert (tmp_path / "tw5" / "themes" / "nf" / "mytheme" / "plugin.info").exists()

    def test_no_plugins_dir(self, nf_tree, capsys):
        tw5_mod.copy_tw5_plugins()
        assert "No plugins directory" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# bundle task
# ---------------------------------------------------------------------------

class TestBundle:
    def test_calls_copy_functions(self, ctx, monkeypatch):
        ed_rec = Recorder()
        pl_rec = Recorder()
        monkeypatch.setattr(tw5_mod, "copy_tw5_editions", ed_rec)
        monkeypatch.setattr(tw5_mod, "copy_tw5_plugins", pl_rec)
        tw5_mod.bundle.__wrapped__(ctx)
        assert ed_rec.call_count == 1
        assert pl_rec.call_count == 1


# ---------------------------------------------------------------------------
# build task
# ---------------------------------------------------------------------------

class TestBuild:
    def test_rsyncs_tw5_to_build_dir(self, ctx, monkeypatch, tmp_path, patch_bundle):
        rsync_rec = Recorder()
        monkeypatch.setattr(tw5_mod.build_utils, "rsync_local", rsync_rec)
        nf = tmp_path / "nf"
        nf.mkdir()
        app_dir = nf / "app"
        app_dir.mkdir()
        (nf / "tw5").mkdir()
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": nf, "tw5": nf / "tw5"}[k])
        tw5_mod.build.__wrapped__(ctx)
        args = rsync_rec.calls[0][0]
        assert args == (nf / "tw5", nf / "app", "tw5")

    def test_custom_build_dir(self, ctx, monkeypatch, tmp_path, patch_bundle):
        rsync_rec = Recorder()
        monkeypatch.setattr(tw5_mod.build_utils, "rsync_local", rsync_rec)
        build_dir = tmp_path / "custom"
        build_dir.mkdir()
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": tmp_path, "tw5": tmp_path / "tw5"}[k])
        tw5_mod.build.__wrapped__(ctx, build_dir=str(build_dir))
        args = rsync_rec.calls[0][0]
        assert args == (tmp_path / "tw5", str(build_dir), "tw5")

    def test_exits_if_dir_missing(self, ctx, monkeypatch, tmp_path, patch_bundle):
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: tmp_path)
        with pytest.raises(SystemExit):
            tw5_mod.build.__wrapped__(ctx, build_dir=str(tmp_path / "nope"))

    def test_pre_includes_bundle(self):
        pre_names = [t.name for t in tw5_mod.build.pre]
        assert "bundle" in pre_names


# ---------------------------------------------------------------------------
# test task
# ---------------------------------------------------------------------------

class TestTestTask:
    def test_calls_bundle(self, ctx, patch_bundle, subprocess_recorder, monkeypatch):
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: Path("/app/tw5"))
        tw5_mod.test.__wrapped__(ctx)
        assert patch_bundle.call_count == 1

    def test_runs_test_sh(self, ctx, patch_bundle, subprocess_recorder, monkeypatch):
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: Path("/app/tw5"))
        tw5_mod.test.__wrapped__(ctx)
        args, kwargs = subprocess_recorder.calls[0]
        assert args[0] == ["bin/test.sh"]
        assert kwargs["cwd"] == Path("/app/tw5")

    def test_nonzero_exit_raises(self, ctx, patch_bundle, monkeypatch):
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: Path("/app/tw5"))
        monkeypatch.setattr(tw5_mod.subprocess, "run",
                            Recorder(return_value=SubprocessResult(1)))
        with pytest.raises(SystemExit):
            tw5_mod.test.__wrapped__(ctx)

    def test_zero_exit_ok(self, ctx, patch_bundle, subprocess_recorder, monkeypatch):
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: Path("/app/tw5"))
        tw5_mod.test.__wrapped__(ctx)  # should not raise
