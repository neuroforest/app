"""
Install built packages from PKG directory.
"""

import socket
import subprocess

import invoke

from neuro.utils import internal_utils

from tasks.actions import pkg, setup


def built_from(pkgver):
    """The commit the package was built from — the pkgver's last field, resolved in
    the app repo. HEAD (via --repo) only when it no longer resolves."""
    app = str(internal_utils.get_path("app"))
    short = pkgver.rsplit(".", 1)[-1]
    res = subprocess.run(["git", "-C", app, "rev-parse", "--verify", "--quiet", f"{short}^{{commit}}"],
                         capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        return ["--revision", res.stdout.strip()]
    return ["--repo", app]


@invoke.task(pre=[setup.env])
def arch(c, package):
    """Install the latest built package from a PKG subdirectory."""
    pkg_dir = internal_utils.get_path("pkg") / package
    tarballs = sorted(pkg_dir.glob("*.pkg.tar*"), key=lambda p: p.stat().st_mtime)
    if not tarballs:
        raise SystemExit(f"No built package found in {pkg_dir}")
    tarball = tarballs[-1]

    # <pkgname>-<pkgver>-<pkgrel>-<arch>.pkg.tar.zst — pkgname may carry a hyphen,
    # pkgver and pkgrel cannot, so split from the right.
    name, pkgver, _rel, _arch = tarball.name.split(".pkg.tar")[0].rsplit("-", 3)

    # The :Deployment is the tree under /opt/neuroforest on this box; the version
    # key is the pkgver, so re-installing the same package is the idempotent
    # re-placement the model wants. Outcome from pacman's exit; failed on a raise.
    place = [
        "--host", socket.gethostname(), "--path", pkg.INSTALL_PATH,
        "--artifact", name, "--artifact-version", pkgver, "--artifact-format", pkg.ARTIFACT_FORMAT,
        *built_from(pkgver),
    ]
    try:
        subprocess.run(["sudo", "pacman", "-U", str(tarball)], check=True)
    except subprocess.CalledProcessError:
        pkg.record("deploy", "--outcome", "failed", *place)
        raise
    pkg.record("deploy", "--outcome", "succeeded", *place)
