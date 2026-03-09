"""
Update packages in PKG directory.
"""

import os
import re
import subprocess

import invoke

from neuro.utils import build_utils, internal_utils, terminal_style

from tasks.actions import setup


def find_packages():
    """Discover subdirectories in PKG that contain a PKGBUILD file."""
    pkg_dir = internal_utils.get_path("pkg")
    return [d for d in sorted(pkg_dir.iterdir()) if d.is_dir() and (d / "PKGBUILD").exists()]


def get_app_git_info():
    """Get commit hash, short hash, and commit count from the app git repo."""
    nf_dir = str(internal_utils.get_path("nf"))
    git = ["git", "-C", nf_dir]

    commit = subprocess.run(
        git + ["rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    short = subprocess.run(
        git + ["rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    count = subprocess.run(
        git + ["rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    return commit, short, count


def update_file(path, replacements):
    """Apply regex replacements to a file. Each replacement is (pattern, repl)."""
    text = path.read_text()
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.MULTILINE)
    path.write_text(text)


@invoke.task(pre=[setup.env])
def arch(c):
    """Update all PKGBUILD packages in PKG with current app commit and version."""
    version = os.environ["APP_VERSION"]
    commit, short, count = get_app_git_info()
    pkgver = f"{version}.r{count}.{short}"

    packages = find_packages()
    if not packages:
        print(f"{terminal_style.FAIL} No packages found in PKG directory")
        return

    for pkg_dir in packages:
        name = pkg_dir.name
        pkgbuild = pkg_dir / "PKGBUILD"
        text = pkgbuild.read_text()
        if f"pkgver={pkgver}" in text:
            print(f"{terminal_style.SKIP} {name} already at {pkgver}")
            continue

        with terminal_style.step(f"Updating {name} to {pkgver} ({short})"):
            update_file(pkgbuild, [
                (r"^pkgver=.*$", f"pkgver={pkgver}"),
                (r"^_commit=.*$", f"_commit={commit}"),
            ])

            if (pkg_dir / ".SRCINFO").exists():
                with build_utils.chdir(pkg_dir):
                    subprocess.run("makepkg --printsrcinfo > .SRCINFO", shell=True, check=True)

