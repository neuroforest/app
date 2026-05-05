import os
import sys

import pytest
from invoke import MockContext

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from neuro.base import NeuroBase  # noqa: E402
from tasks.components import neurobase  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: integration tests (real NeuroBase, real task execution)",
    )


def pytest_collection_modifyitems(items):
    for item in items:
        if not any(m.name in ("unit", "e2e") for m in item.iter_markers()):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session", autouse=True)
def _neurobase_running():
    neurobase.start(MockContext())
    yield


@pytest.fixture
def nb():
    with NeuroBase() as nb:
        nb.clear(confirm=True)
        yield nb
