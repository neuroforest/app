import shlex
import subprocess

import invoke

from neuro.utils import internal_utils, build_utils

from tasks.actions import setup
from tasks.components import tw5, neurobase


MODES = {
    "unit": ["-m", "not (integration or e2e)"],
    "integration": ["-m", "not e2e"],
    "e2e": [],
}


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, mode="integration", location="neuro/tests", pytest_args=""):
    """Run neuro tests. Modes: unit, integration (default), e2e."""
    if mode not in MODES:
        raise SystemExit(f"Unknown mode: {mode}. Choose from {', '.join(MODES)}")
    if mode in ("integration", "e2e"):
        tw5.bundle(c)
        neurobase.reset(c, confirmed=True)
    extra = shlex.split(pytest_args) if pytest_args else []
    result = subprocess.run(["nenv/bin/pytest", location] + MODES[mode] + extra)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_local(c, mode="e2e", location="neuro/tests", pytest_args=""):
    """Rsync neuro and run tests. Modes: unit, integration, e2e (default)."""
    setup.rsync(c, components=["neuro"])
    test(c, mode, location, pytest_args)


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_branch(c, branch_name, mode="e2e", location="neuro/tests", pytest_args=""):
    """Set neuro branch and run tests. Modes: unit, integration, e2e (default)."""
    setup.branch(c, branch_name, components=["neuro"])
    test(c, mode, location, pytest_args)


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


@invoke.task(pre=[setup.env])
def update(c):
    """Push local neuro commits, then reset submodule to origin/develop."""
    try:
        with build_utils.chdir(internal_utils.get_path("neuro")):
            subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(e.returncode)
    setup.develop(c, components=["neuro"])