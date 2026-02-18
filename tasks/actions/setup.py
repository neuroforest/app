"""
Load environment config, chdir to NF_DIR, and prepare submodules.
"""

import os
import subprocess

import invoke

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


def reset_submodule(path, branch_name):
    """git fetch + reset --hard + clean."""
    with build_utils.chdir(path):
        with terminal_style.step(f"Reset {path} to {branch_name}"):
            subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
            subprocess.run(
                ["git", "reset", "--hard", f"{branch_name}"],
                check=True,
                capture_output=True
            )
            subprocess.run(["git", "clean", "-fdx"], check=True, capture_output=True)


@invoke.task
def env(c, environment=None):
    """Load config and chdir to NF_DIR."""
    nf_dir = internal_utils.get_path("nf")
    if environment:
        os.environ["ENVIRONMENT"] = environment
    print(f"Environment [{os.environ['ENVIRONMENT']}] {nf_dir}")

    config.main()
    try:
        os.chdir(nf_dir)
    except FileNotFoundError:
        raise invoke.exceptions.Exit("Invalid directory: {}")


@invoke.task
def nenv(c):
    """Create virtualenv and install neuro."""
    with terminal_style.step("Installing neuro"):
        subprocess.run(["python3", "-m", "venv", "nenv"], check=True, capture_output=True)
        subprocess.run(["nenv/bin/pip", "install", "./neuro"], check=True, capture_output=True)


@invoke.task(pre=[env], iterable="components")
def rsync(c, components):
    """Rsync local submodules (neuro, desktop) into app/."""
    if not components:
        components = LOCAL_SUBMODULES
    for component in components:
        source = internal_utils.get_path(component) + "/"
        dest = internal_utils.get_path("nf") + "/" + component
        build_utils.rsync_local(source, dest, component)


@invoke.task(pre=[env], iterable="components")
def master(c, components):
    """Reset all submodules to their configured branches."""
    if not components:
        components = SUBMODULES
    for component in components:
        reset_submodule(component, "master")


@invoke.task(pre=[env], iterable="components")
def develop(c, components):
    """Reset NF submodules to develop."""
    if not components:
        components = SUBMODULES
    for component in components:
        reset_submodule(component, "develop")


@invoke.task(pre=[env], iterable="components")
def branch(c, branch_name, components):
    """Reset submodules to a branch, with fallback to configured branch."""
    if not components:
        components = SUBMODULES
    for component in components:
        reset_submodule(component, branch_name)
