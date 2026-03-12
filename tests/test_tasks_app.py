"""
Tests for tasks.components.app.
"""


import pytest

from neuro.utils.test_utils import FakeContext, Recorder, SubprocessResult, noop_step

import tasks.components.app as app_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture
def subprocess_recorder(monkeypatch):
    rec = Recorder(return_value=SubprocessResult(0))
    monkeypatch.setattr(app_mod.subprocess, "run", rec)
    return rec


@pytest.fixture(autouse=True)
def patch_step(monkeypatch):
    monkeypatch.setattr(app_mod.terminal_style, "step", noop_step)


# ---------------------------------------------------------------------------
# pre-task wiring
# ---------------------------------------------------------------------------

class TestPreTasks:
    def test_build_pre(self):
        pre_names = [t.name for t in app_mod.build.pre]
        assert pre_names == ["env"]

    def test_run_pre(self):
        pre_names = [t.name for t in app_mod.run.pre]
        assert "env" in pre_names
        assert "init" in pre_names
        assert "start" in pre_names
        assert "run" in pre_names

    def test_stop_pre(self):
        pre_names = [t.name for t in app_mod.stop.pre]
        assert "env" in pre_names
        assert "close" in pre_names


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

class TestBuild:
    def test_creates_dir_and_delegates(self, ctx, monkeypatch, tmp_path,
                                       subprocess_recorder):
        build_dir = tmp_path / "app"
        tw5_rec = Recorder()
        desktop_rec = Recorder()
        monkeypatch.setattr(app_mod.tw5, "build", tw5_rec)
        monkeypatch.setattr(app_mod.desktop, "build", desktop_rec)

        app_mod.build.__wrapped__(ctx, build_dir=str(build_dir))

        assert build_dir.is_dir()
        assert tw5_rec.call_count == 1
        assert tw5_rec.calls[0][1] == {"build_dir": str(build_dir)}
        assert desktop_rec.call_count == 1
        assert desktop_rec.calls[0][1] == {"build_dir": str(build_dir)}

    def test_removes_existing_dir(self, ctx, monkeypatch, tmp_path,
                                   subprocess_recorder):
        build_dir = tmp_path / "app"
        build_dir.mkdir()
        (build_dir / "old_file").write_text("data")

        monkeypatch.setattr(app_mod.tw5, "build", Recorder())
        monkeypatch.setattr(app_mod.desktop, "build", Recorder())

        app_mod.build.__wrapped__(ctx, build_dir=str(build_dir))

        assert build_dir.is_dir()
        assert not (build_dir / "old_file").exists()

    def test_default_build_dir(self, ctx, monkeypatch, tmp_path):
        build_dir = tmp_path / "build"
        monkeypatch.setenv("BUILD", str(build_dir))
        monkeypatch.setattr(app_mod.tw5, "build", Recorder())
        monkeypatch.setattr(app_mod.desktop, "build", Recorder())
        monkeypatch.setattr(app_mod.subprocess, "run", lambda *a, **kw: None)

        app_mod.build.__wrapped__(ctx)

        assert build_dir.is_dir()


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

class TestTest:
    def test_runs_pytest(self, ctx, subprocess_recorder):
        app_mod.test.__wrapped__(ctx)
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["nenv/bin/pytest", "tests/"]

    def test_pytest_args(self, ctx, subprocess_recorder):
        app_mod.test.__wrapped__(ctx, pytest_args="-k foo")
        cmd = subprocess_recorder.calls[0][0][0]
        assert cmd == ["nenv/bin/pytest", "tests/", "-k", "foo"]

    def test_nonzero_exit(self, ctx, monkeypatch):
        monkeypatch.setattr(
            app_mod.subprocess, "run",
            Recorder(return_value=SubprocessResult(1)),
        )
        with pytest.raises(SystemExit):
            app_mod.test.__wrapped__(ctx)
