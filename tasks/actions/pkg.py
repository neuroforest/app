"""
Update packages in PKG directory.
"""

import re
import socket
import subprocess
import time
from pathlib import Path

import invoke

from neuro.utils import build_utils, internal_utils, terminal_components, terminal_style

from tasks.actions import setup


def find_packages():
    """Discover subdirectories in PKG that contain a PKGBUILD file."""
    pkg_dir = internal_utils.get_path("pkg")
    return [d for d in sorted(pkg_dir.iterdir()) if d.is_dir() and (d / "PKGBUILD").exists()]


def get_app_git_info():
    """Get commit hash, short hash, and commit count from the app git repo."""
    nf_dir = str(internal_utils.get_path("app"))
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


def makepkg(package, args="-sf"):
    """Run makepkg in a package directory."""
    pkg_dir = internal_utils.get_path("pkg") / package
    with build_utils.chdir(pkg_dir):
        subprocess.run(["makepkg"] + args.split(), check=True)


def update_file(path, replacements):
    """Apply regex replacements to a file. Each replacement is (pattern, repl)."""
    text = path.read_text()
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.MULTILINE)
    path.write_text(text)


# Sirin's deploy recorder at the release's path — the one rodis records through.
# The apex install is the one NeuroForest channel off rodis (its ship is
# `pacman -U`), so `pkg.arch` records the build and `install.arch` the deploy by
# hand, as fleet-config's deploy does. One line under flock, no network, never
# fatal: recording must never break a build, and a box without a Sirin release
# simply records nothing.
RECORDER = Path("/opt/sirin/current/scripts/sirin-deploy-record")
ARTIFACT_FORMAT = "tarball"       # a .pkg.tar.zst is one; the dist name says what kind
INSTALL_PATH = "/opt/neuroforest"  # where package() puts the tree — the deploy's place


def pkgname(pkg_dir):
    """The package a PKGBUILD builds — the distribution name its artifact installs as."""
    m = re.search(r"^pkgname=(\S+)$", (pkg_dir / "PKGBUILD").read_text(), re.MULTILINE)
    return m.group(1).strip("'\"") if m else pkg_dir.name


def record(kind, *args):
    """One line into Sirin's deploy stream, best-effort — never raises."""
    if not RECORDER.exists():
        return
    try:
        subprocess.run([str(RECORDER), kind, *args], check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  ! deploy record not written: {e}")


@invoke.task(pre=[setup.env])
def arch(c, package=""):
    """Build the PKGBUILD packages in PKG: a recipe that is its own repo as it is
    pinned, the others updated to the current app commit and version first."""
    # One literal, the app's VERSION file (PLAN-2026-322) — no longer an env setting.
    version = (internal_utils.get_path("app") / "VERSION").read_text().strip()
    commit, short, count = get_app_git_info()
    pkgver = f"{version}.r{count}.{short}"

    if package:
        pkg_path = internal_utils.get_path("pkg") / package
        if not (pkg_path / "PKGBUILD").exists():
            raise SystemExit(f"No PKGBUILD found in {pkg_path}")
        packages = [pkg_path]
    else:
        packages = find_packages()
        if not packages:
            print(f"{terminal_style.FAIL} No packages found in PKG directory")
            return

    for pkg_dir in packages:
        name = pkg_dir.name
        pkgbuild = pkg_dir / "PKGBUILD"
        text = pkgbuild.read_text()
        if (pkg_dir / ".git").exists():
            # A recipe that is a repo of its own (arch-git, the AUR) is released on its
            # own: it pins the app's latest tag, and that pin moves only through its own
            # release. This builds exactly what it pins and rewrites nothing.
            pinned = re.search(r"^_commit=(\S+)$", text, re.MULTILINE)
            stated = re.search(r"^pkgver=(\S+)$", text, re.MULTILINE)
            if not pinned or not stated:
                raise SystemExit(f"{name}: PKGBUILD states no _commit= or pkgver= to build from")
            built_commit, built_pkgver = pinned.group(1), stated.group(1)
            print(f"  {name} is released on its own — building what it pins: {built_pkgver}", flush=True)
        else:
            built_commit, built_pkgver = commit, pkgver
            if not package and f"pkgver={pkgver}" in text:
                print(f"{terminal_style.SKIP} {name} already at {pkgver}")
                continue

            with terminal_components.step(f"Updating {name} to {pkgver} ({short})"):
                update_file(pkgbuild, [
                    (r"^pkgver=.*$", f"pkgver={pkgver}"),
                    (r"^_commit=.*$", f"_commit={commit}"),
                ])

                if (pkg_dir / ".SRCINFO").exists():
                    with build_utils.chdir(pkg_dir):
                        subprocess.run("makepkg --printsrcinfo > .SRCINFO", shell=True, check=True)

        # One :BuildProcess per run — an interval, so never idempotent; the artifact
        # it produces is keyed on pkgver + the commit it was built from.
        started = int(time.time())
        built = [
            "--host", socket.gethostname(),
            "--artifact", pkgname(pkg_dir), "--artifact-version", built_pkgver,
            "--artifact-format", ARTIFACT_FORMAT,
            "--built-from-path", str(internal_utils.get_path("app")),
            "--revision", built_commit,
        ]
        try:
            makepkg(name)
        except subprocess.CalledProcessError:
            record("build", "--outcome", "failed", "--started", str(started), *built)
            raise
        record("build", "--outcome", "succeeded", "--started", str(started), *built)

