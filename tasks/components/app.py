"""
Top-level NeuroForest app tasks: build, run, stop, test.
"""

import os
import shlex
import shutil
import subprocess

import invoke

from neuro.utils import internal_utils, terminal_components, terminal_style

from tasks.actions import setup
from tasks.components import desktop, neurobase, tw5


@invoke.task(pre=[setup.env, neurobase.create])
def build(c, build_dir=None):
    """Build tw5, desktop and create neurobase."""
    if not build_dir:
        build_dir = internal_utils.get_path("nf") + "/app"
    if os.path.exists(build_dir):
        if terminal_components.bool_prompt(f"Rewrite {build_dir}?"):
            with terminal_style.step(f"Removing {build_dir}"):
                shutil.rmtree(build_dir)
        else:
            raise SystemExit("Aborting build.")
    os.makedirs(build_dir)
    desktop.build(c, build_dir=build_dir)
    tw5.build(c, build_dir=build_dir)


@invoke.task(pre=[setup.env, neurobase.start, desktop.run])
def run(c):
    """Start neurobase and launch desktop."""
    pass


@invoke.task(pre=[setup.env, neurobase.stop, desktop.close])
def stop(c):
    """Close desktop and stop neurobase."""
    pass


@invoke.task(pre=[invoke.call(setup.env, environment="TESTING")])
def test(c, pytest_args=""):
    """Run app tests (pytest tests/)."""
    extra = shlex.split(pytest_args) if pytest_args else []
    result = subprocess.run(["nenv/bin/pytest", "tests/"] + extra)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
