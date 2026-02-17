import subprocess

from invoke import task, call

from ..actions import setup


@task(pre=[call(setup.env, environment="TESTING")])
def test_local(c, pytest_args=""):
    """Rsync neuro and run tests."""
    setup.rsync(c, components=["neuro"])
    setup.nenv(c)
    test(c, pytest_args)


@task(pre=[call(setup.env, environment="TESTING")])
def test_branch(c, branch_name, pytest_args=""):
    """Set neuro branch and run tests."""
    setup.branch(c, branch_name, components=["neuro"])
    test(c, pytest_args)


@task
def ruff(c, ruff_args=""):
    """Run ruff check on neuro/."""
    if not ruff_args:
        ruff_args = []
    else:
        ruff_args = ruff_args.split()
    result = subprocess.run(["nenv/bin/ruff", "check", "neuro/"] + ruff_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@task(pre=[call(setup.env, environment="TESTING")])
def test(c, pytest_args=""):
    """Run neuro tests."""
    if not pytest_args:
        pytest_args = ["neuro/tests"]
    else:
        pytest_args = pytest_args.split(" ")
    result = subprocess.run(["nenv/bin/pytest"] + pytest_args)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
