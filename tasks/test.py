"""
Run NeuroForest tests.
"""

import os
import subprocess

import pytest
from invoke import task

from neuro.utils import internal_utils, terminal_style

from . import setup
from .components import neuro as neuro_mod, tw5 as tw5_mod


ALL_LOCAL_COMPONENTS = ["app", "neuro", "tw5"]


@task(pre=[setup.env])
def app(c):
    """Run app tests (pytest tests/)."""
    os.environ["ENVIRONMENT"] = "TESTING"
    with terminal_style.step("pytest tests/"):
        exit_code = pytest.main(["tests"])
    if exit_code != 0:
        raise SystemExit(exit_code)


@task(pre=[setup.env], iterable="components")
def local(c, components):
    """Run local component tests (default: all). Use -c app -c neuro etc."""
    os.environ["ENVIRONMENT"] = "TESTING"

    if not components:
        components = ALL_LOCAL_COMPONENTS

    results = {}
    for component in components:
        try:
            if component == "app":
                results["app"] = pytest.main(["tests"])
            elif component == "neuro":
                neuro_mod.rsync_and_install()
                results["neuro"] = pytest.main(["neuro/tests"])
            elif component == "tw5":
                tw5_mod.copy_tw5_editions()
                tw5_mod.copy_tw5_plugins()
                tw5_path = internal_utils.get_path("tw5")
                result = subprocess.run(["bin/test.sh"], cwd=tw5_path)
                results["tw5"] = result.returncode
            else:
                print(f"Unknown component: {component}")
                results[component] = 1
        except Exception as e:
            print(f"Error running {component}: {e}")
            results[component] = 1

    print(f"\n{'='*60}")
    print(f"  Test Summary")
    print(f"{'='*60}")
    for name, code in results.items():
        status = terminal_style.SUCCESS if code == 0 else terminal_style.FAIL
        print(f"  {status} {name}")

    if any(code != 0 for code in results.values()):
        raise SystemExit(1)


@task(pre=[setup.env])
def production(c):
    """Build desktop and run production tests (stub)."""
    os.environ["ENVIRONMENT"] = "TESTING"
    print("Production tests not yet implemented.")
