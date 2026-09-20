import os
import re
import shlex
import subprocess

import invoke

from neuro.utils import internal_utils, build_utils, terminal_style

from tasks.actions import pkg, setup
from tasks.components import tw5, neurobase


MODES = {
    "unit": ["-m", "not (integration or e2e)"],
    "integration": ["-m", "not e2e"],
    "e2e": [],
}


# The version is declared twice and both must move together: pyproject.toml is
# what the wheel carries, neuro/__init__.py what an importing process reads.
VERSION_SITES = {
    ("neuro", "pyproject.toml"): (r'^version = "(.*)"$', 'version = "{}"'),
    ("neuro", "neuro", "__init__.py"): (r'^__version__ = "(.*)"$', '__version__ = "{}"'),
}


def version_paths():
    """Return {path: (pattern, template)} for every declared neuro version site."""
    app_dir = internal_utils.get_path("app")
    return {app_dir.joinpath(*parts): site for parts, site in VERSION_SITES.items()}


def read_versions():
    """Return {path: version} for every declared neuro version site."""
    versions = {}
    for path, (pattern, _) in version_paths().items():
        match = re.search(pattern, path.read_text(), re.MULTILINE)
        if not match:
            raise SystemExit(f"{terminal_style.FAIL} No version found in {path}")
        versions[path] = match.group(1)
    return versions


@invoke.task(pre=[setup.env])
def version(c, bump=""):
    """Show the neuro version. --bump major|minor|patch rewrites pyproject.toml and __init__.py."""
    versions = read_versions()
    distinct = set(versions.values())
    if len(distinct) > 1:
        for path, declared in versions.items():
            print(f"{terminal_style.WARN} {path}: {declared}")
        raise SystemExit(f"{terminal_style.FAIL} Version sites disagree")

    current = distinct.pop()
    if not bump:
        print(current)
        return
    try:
        new = build_utils.bump_version(current, bump)
    except ValueError as e:
        raise SystemExit(f"{terminal_style.FAIL} {e}")
    for path, (pattern, template) in version_paths().items():
        pkg.update_file(path, [(pattern, template.format(new))])
    print(f"{terminal_style.SUCCESS} neuro {current} ➜ {new}")


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