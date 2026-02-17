"""
Run NeuroForest tests.
"""

import os
import subprocess

import invoke

from . import setup
from ..components import neuro, tw5


COMPONENTS = ["app", "neuro", "tw5"]


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def app(c, pytest_args=""):
    """Run app tests (pytest tests/)."""
    if not pytest_args:
        pytest_args = ["./tests"]
    else:
        pytest_args = pytest_args.split()
    result = subprocess.run(["nenv/bin/pytest"] + pytest_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")], iterable="components")
def local(c, components):
    if not components:
        components = COMPONENTS

    if "tw5" in components:
        tw5.test(c)

    if "neuro" in components:
        neuro.test_local(c)

    if "app" in components:
        app(c)


@invoke.task
def ruff(c, ruff_args=""):
    """Run ruff check on neuro/ and app (tasks/, tests/)."""
    neuro.ruff(c, ruff_args=ruff_args)
    if not ruff_args:
        ruff_args = []
    else:
        ruff_args = ruff_args.split()
    result = subprocess.run(["nenv/bin/ruff", "check", "tasks/", "tests/"] + ruff_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[setup.env])
def production(c):
    """Build desktop and run production tests (stub)."""
    os.environ["ENVIRONMENT"] = "TESTING"
    print("Production tests not yet implemented.")
