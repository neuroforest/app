"""
Run NeuroForest tests.
"""

import os
import shlex
import subprocess

import invoke

from neuro.utils import terminal_style

from tasks.actions import setup
from tasks.components import app as app_tasks, neuro, tw5


COMPONENTS = ["app", "neuro", "tw5"]


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")], iterable="components")
def local(c, components):
    if not components:
        components = COMPONENTS

    failed = []

    if "app" in components:
        terminal_style.header("Testing APP")
        try:
            app_tasks.test(c)
        except SystemExit:
            failed.append("app")

    if "neuro" in components:
        terminal_style.header("Testing NEURO")
        try:
            neuro.test_local(c)
        except SystemExit:
            failed.append("neuro")

    if "tw5" in components:
        terminal_style.header("Testing TW5")
        try:
            tw5.test(c)
        except SystemExit:
            failed.append("tw5")

    terminal_style.header("Results")
    for component in components:
        if component in failed:
            print(f"  {terminal_style.FAIL} {component}")
        else:
            print(f"  {terminal_style.SUCCESS} {component}")

    if failed:
        raise SystemExit(1)


@invoke.task(pre=[setup.env])
def ruff(c, ruff_args=""):
    """Run ruff check on neuro/ and app (tasks/, tests/)."""
    neuro.ruff(c, ruff_args=ruff_args)
    if not ruff_args:
        ruff_args = []
    else:
        ruff_args = shlex.split(ruff_args)
    result = subprocess.run(["nenv/bin/ruff", "check", "tasks/", "tests/"] + ruff_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[setup.env])
def production(c):
    """Build desktop and run production tests (stub)."""
    os.environ["ENVIRONMENT"] = "TESTING"
    print("Production tests not yet implemented.")
