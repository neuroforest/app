import os
from os import environ

import pytest
from invoke import task, call

from ..actions import setup


@task(pre=[call(setup.env, environment="TESTING")])
def test(c):
    """Run neuro tests."""
    exit_code = pytest.main(["neuro/tests"])
    if exit_code != 0:
        raise SystemExit(exit_code)
