"""
Tests for tasks.components.tw5.
"""

import json
import os

import pytest

import tasks.components.tw5 as tw5_mod
from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _patch_step(monkeypatch):
    monkeypatch.setattr(tw5_mod.terminal_style, "step", noop_step)


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(tw5_mod.subprocess, "run", rec)
    return rec


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_edition_valid(self, tmp_path):
        edition_dir = tmp_path / "edition_a"
        edition_dir.mkdir()
        info = {"description": "x", "plugins": [], "themes": [], "build": {}}
        (edition_dir / "tiddlywiki.info").write_text(json.dumps(info))
        assert tw5_mod.validate_tw5_edition(str(edition_dir)) is True

    def test_validate_edition_missing_info_file(self, tmp_path):
        edition_dir = tmp_path / "edition_b"
        edition_dir.mkdir()
        assert tw5_mod.validate_tw5_edition(str(edition_dir)) is False

    def test_validate_edition_invalid_json(self, tmp_path):
        edition_dir = tmp_path / "edition_c"
        edition_dir.mkdir()
        (edition_dir / "tiddlywiki.info").write_text("{bad json")
        assert tw5_mod.validate_tw5_edition(str(edition_dir)) is False

    def test_validate_edition_missing_fields(self, tmp_path):
        edition_dir = tmp_path / "edition_d"
        edition_dir.mkdir()
        (edition_dir / "tiddlywiki.info").write_text(json.dumps({"description": "x"}))
        assert tw5_mod.validate_tw5_edition(str(edition_dir)) is False

    def test_validate_plugin_valid(self, tmp_path):
        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        info = {"title": "$:/plugins/test/foo", "description": "A plugin"}
        info_path = plugin_dir / "plugin.info"
        info_path.write_text(json.dumps(info))
        result = tw5_mod.validate_tw5_plugin(str(info_path))
        assert result == info

    def test_validate_plugin_invalid_json(self, tmp_path):
        plugin_dir = tmp_path / "badplugin"
        plugin_dir.mkdir()
        info_path = plugin_dir / "plugin.info"
        info_path.write_text("not json")
        assert tw5_mod.validate_tw5_plugin(str(info_path)) is None

    def test_validate_plugin_missing_fields(self, tmp_path):
        plugin_dir = tmp_path / "incomp"
        plugin_dir.mkdir()
        info_path = plugin_dir / "plugin.info"
        info_path.write_text(json.dumps({"title": "x"}))
        assert tw5_mod.validate_tw5_plugin(str(info_path)) is None


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------

class TestDiscover:
    def test_discover_finds_plugins(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        plugins = nf / "tw5-plugins"
        plugins.mkdir(parents=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tmp_path / "tw5")}[k])

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

        results = tw5_mod.discover_tw5_plugins()
        assert len(results) == 2
        titles = [info["title"] for _, info in results]
        assert titles == ["$:/plugins/nf/alpha", "$:/plugins/nf/beta"]

    def test_discover_skips_invalid(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        plugins = nf / "tw5-plugins"
        plugins.mkdir(parents=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tmp_path / "tw5")}[k])

        bad = plugins / "bad"
        bad.mkdir()
        (bad / "plugin.info").write_text("not json")

        assert tw5_mod.discover_tw5_plugins() == []


# ---------------------------------------------------------------------------
# Copy editions
# ---------------------------------------------------------------------------

class TestCopyEditions:
    def test_copies_valid_editions(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])

        # _editions_dir() returns os.path.join(nf, "tw5-editions")
        # copy_tw5_editions does os.path.join(get_path("nf"), _editions_dir())
        # Since _editions_dir() is absolute, os.path.join returns the absolute path
        editions_source = tw5_mod._editions_dir()
        os.makedirs(editions_source, exist_ok=True)

        ed = os.path.join(editions_source, "myedition")
        os.makedirs(ed)
        info = {"description": "x", "plugins": [], "themes": [], "build": {}}
        with open(os.path.join(ed, "tiddlywiki.info"), "w") as f:
            json.dump(info, f)

        (tw5 / "editions").mkdir(exist_ok=True)
        tw5_mod.copy_tw5_editions()

        target = tw5 / "editions" / "myedition" / "tiddlywiki.info"
        assert target.exists()

    def test_skips_when_no_editions_dir(self, monkeypatch, tmp_path, capsys):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw5_mod.copy_tw5_editions()
        out = capsys.readouterr().out
        assert "No editions directory" in out


# ---------------------------------------------------------------------------
# Copy plugins
# ---------------------------------------------------------------------------

class TestCopyPlugins:
    def test_copies_plugins(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        plugins_src = nf / "tw5-plugins"
        for d in (nf, tw5, plugins_src):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])

        p = plugins_src / "myplugin"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({
            "title": "$:/plugins/nf/myplugin",
            "description": "My plugin",
        }))
        (p / "somefile.tid").write_text("content")

        (tw5 / "plugins").mkdir(exist_ok=True)
        tw5_mod.copy_tw5_plugins()

        target = tw5 / "plugins" / "nf" / "myplugin" / "somefile.tid"
        assert target.exists()

    def test_copies_theme_to_themes_dir(self, monkeypatch, tmp_path):
        nf = tmp_path / "nf"
        tw5 = tmp_path / "tw5"
        plugins_src = nf / "tw5-plugins"
        for d in (nf, tw5, plugins_src):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])

        p = plugins_src / "mytheme"
        p.mkdir()
        (p / "plugin.info").write_text(json.dumps({
            "title": "$:/themes/nf/mytheme",
            "description": "A theme",
            "plugin-type": "theme",
        }))

        (tw5 / "themes").mkdir(exist_ok=True)
        tw5_mod.copy_tw5_plugins()

        assert (tw5 / "themes" / "nf" / "mytheme" / "plugin.info").exists()

    def test_skips_when_no_plugins_dir(self, monkeypatch, tmp_path, capsys):
        nf = tmp_path / "nf_empty"
        tw5 = tmp_path / "tw5"
        for d in (nf, tw5):
            d.mkdir(exist_ok=True)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path",
                            lambda k: {"nf": str(nf), "tw5": str(tw5)}[k])
        tw5_mod.copy_tw5_plugins()
        out = capsys.readouterr().out
        assert "No plugins directory" in out


# ---------------------------------------------------------------------------
# test task
# ---------------------------------------------------------------------------

class TestTestTask:
    def _patch_copy(self, monkeypatch):
        """Stub out copy functions so test task only runs test.sh."""
        monkeypatch.setattr(tw5_mod, "copy_tw5_editions", lambda: None)
        monkeypatch.setattr(tw5_mod, "copy_tw5_plugins", lambda: None)

    def test_sets_environment(self, ctx, monkeypatch, subprocess_recorder):
        self._patch_copy(monkeypatch)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: "/app/tw5")
        tw5_mod.test.__wrapped__(ctx)
        assert os.environ["ENVIRONMENT"] == "TESTING"

    def test_runs_test_sh(self, ctx, monkeypatch, subprocess_recorder):
        self._patch_copy(monkeypatch)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: "/app/tw5")
        tw5_mod.test.__wrapped__(ctx)
        args, kwargs = subprocess_recorder.calls[0]
        assert args[0] == ["bin/test.sh"]
        assert kwargs["cwd"] == "/app/tw5"

    def test_raises_on_failure(self, ctx, monkeypatch):
        self._patch_copy(monkeypatch)
        monkeypatch.setattr(tw5_mod.internal_utils, "get_path", lambda k: "/app/tw5")
        monkeypatch.setattr(
            tw5_mod.subprocess, "run",
            Recorder(return_value=SubprocessResult(1)),
        )
        with pytest.raises(SystemExit):
            tw5_mod.test.__wrapped__(ctx)
