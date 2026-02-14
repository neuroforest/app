"""
Tests for bin/build.py

Logic:
    Copies valid edition directories from tw5-editions/ into tw5/editions/.
    Validates tiddlywiki.info exists and contains required fields.
    Replaces existing editions. Skips non-directory files and invalid editions.
"""

import importlib.util
import json
import os
import sys

import pytest

from neuro.utils import internal_utils


VALID_INFO = json.dumps({
    "description": "test",
    "plugins": ["neuroforest/core"],
    "themes": ["neuroforest/basic"],
    "build": {"index": ["--rendertiddler"]},
})


# -- Load module --

@pytest.fixture(scope="session")
def build():
    spec = importlib.util.spec_from_file_location(
        "build",
        os.path.join(internal_utils.get_path("app"), "bin/build.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mock_paths(build, tmp_path, monkeypatch):
    (tmp_path / "tw5" / "editions").mkdir(parents=True)
    monkeypatch.setattr(build.internal_utils, "get_path", lambda k: {
        "app": str(tmp_path),
        "tw5": str(tmp_path / "tw5"),
    }[k])
    return tmp_path


def make_edition(base, name, info_content=VALID_INFO):
    edition_dir = base / "tw5-editions" / name
    edition_dir.mkdir(parents=True, exist_ok=True)
    if info_content is not None:
        (edition_dir / "tiddlywiki.info").write_text(info_content)
    return edition_dir


# -- Tests --

class TestValidateEdition:
    """validate_tw5_edition() checks tiddlywiki.info exists and has required fields."""

    def test_valid(self, build, tmp_path):
        edition = make_edition(tmp_path, "good")
        assert build.validate_tw5_edition(str(edition)) is True

    def test_missing_file(self, build, tmp_path, capsys):
        edition = make_edition(tmp_path, "no-info", info_content=None)
        assert build.validate_tw5_edition(str(edition)) is False
        assert "missing tiddlywiki.info" in capsys.readouterr().out

    def test_invalid_json(self, build, tmp_path, capsys):
        edition = make_edition(tmp_path, "bad-json", info_content="{broken")
        assert build.validate_tw5_edition(str(edition)) is False
        assert "invalid JSON" in capsys.readouterr().out

    def test_missing_fields(self, build, tmp_path, capsys):
        edition = make_edition(tmp_path, "incomplete", info_content='{"description": "x"}')
        assert build.validate_tw5_edition(str(edition)) is False
        assert "missing fields" in capsys.readouterr().out


class TestCopyEditions:
    """copy_tw5_editions() copies valid editions, skips invalid ones."""

    def test_copies_valid_edition(self, build, mock_paths):
        make_edition(mock_paths, "my-edition")
        build.copy_tw5_editions()
        target = mock_paths / "tw5" / "editions" / "my-edition" / "tiddlywiki.info"
        assert target.exists()
        assert json.loads(target.read_text())["description"] == "test"

    def test_replaces_existing(self, build, mock_paths):
        make_edition(mock_paths, "my-edition")
        old = mock_paths / "tw5" / "editions" / "my-edition"
        old.mkdir(parents=True)
        (old / "tiddlywiki.info").write_text('{"old": true}')
        build.copy_tw5_editions()
        assert json.loads((old / "tiddlywiki.info").read_text())["description"] == "test"

    def test_skips_invalid_edition(self, build, mock_paths):
        make_edition(mock_paths, "bad", info_content='{"description": "x"}')
        build.copy_tw5_editions()
        assert not (mock_paths / "tw5" / "editions" / "bad").exists()

    def test_skips_files(self, build, mock_paths):
        (mock_paths / "tw5-editions").mkdir(exist_ok=True)
        (mock_paths / "tw5-editions" / "README.md").write_text("ignore")
        build.copy_tw5_editions()
        assert not (mock_paths / "tw5" / "editions" / "README.md").exists()

    def test_no_editions_dir(self, build, mock_paths, capsys):
        build.copy_tw5_editions()
        assert "No editions directory found" in capsys.readouterr().out
