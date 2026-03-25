"""
Top-level NeuroForest app tasks: build, run, stop, test.
"""

import glob
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import invoke

from neuro.utils import build_utils, internal_utils, terminal_style

from tasks.actions import setup
from tasks.components import desktop, neurobase, tw5


@invoke.task(pre=[setup.env])
def build(c, build_dir=None):
    """Build tw5 and desktop into build_dir."""
    if not build_dir:
        build_dir = Path(os.environ["BUILD"])
    if os.path.exists(build_dir):
        with terminal_style.step(f"Removing {build_dir}"):
            shutil.rmtree(build_dir)
    os.makedirs(build_dir)
    desktop.build(c, build_dir=build_dir)
    tw5.build(c, build_dir=build_dir)

    nenv_dir = os.path.join(build_dir, "nenv")
    neuro_dir = str(internal_utils.get_path("neuro"))
    with terminal_style.step("Creating package nenv"):
        subprocess.run(["python3", "-m", "venv", nenv_dir], check=True, capture_output=build_utils.quiet())
        subprocess.run([os.path.join(nenv_dir, "bin", "pip"), "install", neuro_dir],
                       check=True, capture_output=build_utils.quiet())


def _patch_rsync(source, dest, name):
    """Rsync source to dest, showing ✔ if files changed or ⊘ if already up to date."""
    result = subprocess.run(
        ["rsync", "-rlci", "--exclude=__pycache__", "--exclude=.git",
         "--delete", source, dest],
        check=True, capture_output=True, text=True,
    )
    if result.stdout.strip():
        print(f"{terminal_style.SUCCESS} {name}")
    else:
        print(f"{terminal_style.SKIP} {name}")


@invoke.task(pre=[setup.env], iterable="components")
def patch(c, components):
    """Rsync SUBMODULES components into build/.
    Components: neuro, desktop, tw5-plugins/neuroforest/front, etc.
    Without arguments, patches all SUBMODULES.
    """
    build_dir = internal_utils.get_path("build")
    submodules = setup.get_submodules()
    if not components:
        components = list(submodules)
    for comp in components:
        if comp not in submodules:
            print(f"{terminal_style.FAIL} {comp} not found in SUBMODULES")
            continue
        comp_root = submodules[comp]
        source_label = os.path.relpath(comp_root, os.path.dirname(internal_utils.get_path("nf")))
        if comp == "neuro":
            site_packages = glob.glob(str(build_dir / "nenv" / "lib" / "python*" / "site-packages" / "neuro"))
            if not site_packages:
                print(f"{terminal_style.FAIL} neuro not found in build nenv")
                continue
            source_dir = os.path.join(comp_root, "neuro") + "/"
            _patch_rsync(source_dir, site_packages[0], f"Patch {source_label} ➜  build")
        elif comp == "desktop":
            source_dir = os.path.join(comp_root, "source") + "/"
            _patch_rsync(source_dir, str(build_dir / "source"), f"Patch {source_label} ➜  build")
        elif comp.startswith("tw5-plugins/"):
            info_path, info = tw5.discover_tw5_plugins(comp_root)
            if not info:
                print(f"{terminal_style.FAIL} No plugin.info found in {source_label}")
                continue
            plugin_type = info.get("plugin-type", "plugin")
            target_base = "themes" if plugin_type == "theme" else "plugins"
            relative = comp.removeprefix("tw5-plugins/")
            source_dir = os.path.dirname(info_path) + "/"
            dest = str(build_dir / "tw5" / target_base / relative)
            _patch_rsync(source_dir, dest, f"Patch {source_label} ➜  build")


@invoke.task(pre=[setup.env, setup.init, neurobase.start, desktop.run])
def run(c):
    """Initialize (if needed), start neurobase and launch desktop."""
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
