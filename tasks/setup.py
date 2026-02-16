"""
Load environment config, chdir to NF_DIR, and prepare submodules.
"""

import os
import subprocess

from invoke import task
from invoke.exceptions import Exit

from neuro.utils import build_utils, config, internal_utils, terminal_style


LOCAL_SUBMODULES = [
    "neuro",
    "desktop"
]

SUBMODULES = [
    "neuro",
    "desktop",
    "tw5",
    "tw5-plugins/neuroforest/core",
    "tw5-plugins/neuroforest/front",
    "tw5-plugins/neuroforest/neo4j-syncadaptor",
    "tw5-plugins/neuroforest/basic",
    "tw5-plugins/neuroforest/mobile",
]


@task
def env(c, environment=None):
    """Load config and chdir to NF_DIR."""
    nf_dir = os.getenv("NF_DIR")
    print(f"Environment [{environment}] {nf_dir}")
    if environment:
        os.environ["ENVIRONMENT"] = environment
    config.main()
    try:
        os.chdir(nf_dir)
    except FileNotFoundError:
        raise Exit("Invalid directory: {}")


def reset_submodule(path, branch_name):
    """git fetch + reset --hard + clean."""
    with build_utils.chdir(path):
        with terminal_style.step(f"Reset {path} to {branch_name}"):
            subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{branch_name}"],
                check=True,
                capture_output=True
            )
            subprocess.run(["git", "clean", "-fdx"], check=True, capture_output=True)


@task(iterable="modules")
def rsync(c, modules):
    """Rsync local submodules (neuro, desktop) into app/."""
    if not modules:
        modules = LOCAL_SUBMODULES
    for module in modules:
        source = internal_utils.get_path(module) + "/"
        dest = internal_utils.get_path("nf") + "/" + module
        build_utils.rsync_local(source, dest, module)


@task(pre=[env], iterable="submodules")
def master(c, submodules):
    """Reset all submodules to their configured branches."""
    if not submodules:
        submodules = SUBMODULES
    for submodule in submodules:
        reset_submodule(submodule, "master")


@task(pre=[env], iterable="submodules")
def develop(c, submodules):
    """Reset NF submodules to develop."""
    if not submodules:
        submodules = SUBMODULES
    for path in submodules:
        reset_submodule(path, "develop")


@task(pre=[env], iterable="submodules")
def branch(c, branch_name, submodules):
    """Reset submodules to a branch, with fallback to configured branch."""
    if not submodules:
        submodules = SUBMODULES
    for submodules in submodules:
        reset_submodule(submodules, branch_name)
