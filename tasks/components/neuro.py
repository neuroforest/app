import shlex
import subprocess

import invoke

from neuro.utils import internal_utils, build_utils

from tasks.actions import setup
from tasks.components import tw5


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_local(c, location="neuro/tests", pytest_args="", integration=True):
    """Rsync neuro and run tests."""
    setup.rsync(c, components=["neuro"])
    if integration:
        test_integration(c, location, pytest_args)
    else:
        test(c, location, pytest_args)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_branch(c, branch_name, location="neuro/tests", pytest_args="", integration=True):
    """Set neuro branch and run tests."""
    setup.branch(c, branch_name, components=["neuro"])
    if integration:
        test_integration(c, location, pytest_args)
    else:
        test(c, location, pytest_args)


@invoke.task(pre=[setup.env])
def ruff(c, ruff_args=""):
    """Run ruff check on neuro/."""
    if not ruff_args:
        ruff_args = []
    else:
        ruff_args = shlex.split(ruff_args)
    result = subprocess.run(["nenv/bin/ruff", "check", internal_utils.get_path("neuro")] + ruff_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, location="neuro/tests", pytest_args=""):
    """Run neuro tests."""
    extra = shlex.split(pytest_args) if pytest_args else []
    result = subprocess.run(["nenv/bin/pytest", location] + extra)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[setup.env])
def update(c):
    """Push local neuro commits, then fetch and merge origin/develop."""
    try:
        with build_utils.chdir(internal_utils.get_path("neuro")):
            subprocess.run(["git", "push"], check=True)
        with build_utils.chdir("neuro"):
            subprocess.run(["git", "fetch"], check=True)
            subprocess.run(["git", "checkout", "devlop"], check=True)
            subprocess.run(["git", "merge", "origin/develop"], check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(e.returncode)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_integration(c, location="neuro/tests", pytest_args=""):
    """Run neuro tests."""
    extra = shlex.split(pytest_args) if pytest_args else []
    tw5.bundle(c)
    result = subprocess.run(["nenv/bin/pytest", location] + extra)
    if result.returncode != 0:
        raise SystemExit(result.returncode)