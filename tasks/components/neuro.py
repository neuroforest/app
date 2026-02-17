import shlex
import subprocess

import invoke

from ..actions import setup


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_local(c, pytest_args=""):
    """Rsync neuro and run tests."""
    setup.rsync(c, components=["neuro"])
    setup.nenv(c)
    test(c, pytest_args)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_branch(c, branch_name, pytest_args=""):
    """Set neuro branch and run tests."""
    setup.branch(c, branch_name, components=["neuro"])
    test(c, pytest_args)


@invoke.task
def ruff(c, ruff_args=""):
    """Run ruff check on neuro/."""
    if not ruff_args:
        ruff_args = []
    else:
        ruff_args = shlex.split(ruff_args)
    result = subprocess.run(["nenv/bin/ruff", "check", "neuro/"] + ruff_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, pytest_args=""):
    """Run neuro tests."""
    extra = shlex.split(pytest_args) if pytest_args else []
    result = subprocess.run(["nenv/bin/pytest", "neuro/tests"] + extra)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
