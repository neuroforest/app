"""
Run NeuroForest tests.
"""

import os

import pytest
from invoke import task, call

from . import setup
from ..components import neuro, tw5


COMPONENTS = ["app", "neuro", "tw5"]


@task(pre=[call(setup.env, environment="TESTING")])
def app(c, pytest_args=""):
    """Run app tests (pytest tests/)."""
    if not pytest_args:
        pytest_args = ["tests"]
    else:
        pytest_args = pytest_args.split()
    exit_code = pytest.main(pytest_args)
    if exit_code != 0:
        raise SystemExit(exit_code)


@task(pre=[call(setup.env, environment="TESTING")], iterable="components")
def local(c, components):
    if not components:
        components = COMPONENTS

    if "tw5" in components:
        tw5.test(c)

    if "neuro" in components:
        neuro.test_local(c)

    if "app" in components:
        app(c)


@task(pre=[setup.env])
def production(c):
    """Build desktop and run production tests (stub)."""
    os.environ["ENVIRONMENT"] = "TESTING"
    print("Production tests not yet implemented.")
