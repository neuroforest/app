import pytest
from invoke import task, call

from ..actions import setup


@task(pre=[call(setup.env, environment="TESTING")])
def test_local(c, pytest_args=""):
    """Rsync neuro and run tests."""
    setup.rsync(c, components=["neuro"])
    test(c, pytest_args)


@task(pre=[call(setup.env, environment="TESTING")])
def test_branch(c, branch_name, pytest_args=""):
    """Set neuro branch and run tests."""
    setup.branch(c, branch_name, components=["neuro"])
    test(c, pytest_args)


@task(pre=[call(setup.env, environment="TESTING")])
def test(c, pytest_args=""):
    """Run neuro tests."""
    if not pytest_args:
        pytest_args = ["neuro/tests"]
    else:
        pytest_args = pytest_args.split(" ")
    exit_code = pytest.main(pytest_args)
    if exit_code != 0:
        raise SystemExit(exit_code)
