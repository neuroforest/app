import os
import shlex
import subprocess

import invoke

from neuro.utils import internal_utils, build_utils, terminal_style

from tasks.actions import setup
from tasks.components import tw5, neurobase


MODES = {
    "unit": ["-m", "not (integration or e2e)"],
    "integration": ["-m", "not e2e"],
    "e2e": [],
}


# The version is one literal, neuro/VERSION (PLAN-2026-321): pyproject.toml reads
# it as `dynamic`, neuro.__version__ reads the file in a checkout and the installed
# metadata from a wheel. Moving it is a release, and a release is
# `deploy neuro --bump patch|minor|major` (rodis): bump, commit, tag, forge, wheel,
# host, record — so there is nothing left for a task to rewrite.
VERSION_FILE = ("neuro", "VERSION")


def read_version():
    """Return the declared neuro version."""
    path = internal_utils.get_path("app").joinpath(*VERSION_FILE)
    try:
        return path.read_text().strip()
    except OSError as e:
        raise SystemExit(f"{terminal_style.FAIL} No version file at {path}: {e}")


@invoke.task(pre=[setup.env])
def version(c, bump=""):
    """Show the neuro version. A bump is a release: `deploy neuro --bump patch|minor|major`."""
    if bump:
        raise SystemExit(f"{terminal_style.FAIL} neuro's version moves only through a release — "
                         f"run `deploy neuro --bump {bump}` (rodis, PLAN-2026-321)")
    print(read_version())


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, mode="integration", pytest_args=""):
    """Run neuro tests. Modes: unit, integration (default), e2e."""
    setup.nenv(c)
    if mode not in MODES:
        raise SystemExit(f"Unknown mode: {mode}. Choose from {', '.join(MODES)}")
    if mode in ("integration", "e2e"):
        tw5.bundle(c)
        neurobase.clear(c, confirmed=True)
    extra = shlex.split(pytest_args) if pytest_args else []
    result = subprocess.run([os.path.join(setup.get_nenv_dir(), "bin", "pytest"), "neuro/tests"] + MODES[mode] + extra)
    if result.returncode != 0:
        raise SystemExit(result.returncode)



@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test_branch(c, branch_name, mode="e2e", pytest_args=""):
    """Set neuro branch and run tests. Modes: unit, integration, e2e (default)."""
    setup.branch(c, branch_name, components=["neuro"])
    test(c, mode, pytest_args)


@invoke.task(pre=[setup.env])
def ruff(c, ruff_args=""):
    """Run ruff check on neuro/."""
    if not ruff_args:
        ruff_args = []
    else:
        ruff_args = shlex.split(ruff_args)
    result = subprocess.run([os.path.join(setup.get_nenv_dir(), "bin", "ruff"), "check", internal_utils.get_path("neuro")] + ruff_args)
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