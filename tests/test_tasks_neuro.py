"""
Tests for tasks.components.neuro.
"""

import pytest

import tasks.components.neuro as neuro_mod

from neuro.utils.test_utils import FakeContext, Recorder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)


@pytest.fixture
def pytest_recorder(monkeypatch):
    rec = Recorder(return_value=0)
    monkeypatch.setattr(neuro_mod.pytest, "main", rec)
    return rec


# ---------------------------------------------------------------------------
# test task
# ---------------------------------------------------------------------------

class TestTestTask:
    def test_runs_pytest_neuro_tests(self, ctx, pytest_recorder):
        neuro_mod.test.__wrapped__(ctx)
        assert pytest_recorder.last_args == (["neuro/tests"],)

    def test_raises_on_pytest_failure(self, ctx, monkeypatch):
        monkeypatch.setattr(neuro_mod.pytest, "main", Recorder(return_value=1))
        with pytest.raises(SystemExit):
            neuro_mod.test.__wrapped__(ctx)

    def test_no_raise_on_success(self, ctx, pytest_recorder):
        neuro_mod.test.__wrapped__(ctx)
