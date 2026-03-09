"""
Install built packages from PKG directory.
"""

import subprocess

import invoke

from neuro.utils import internal_utils

from tasks.actions import setup


@invoke.task(pre=[setup.env])
def arch(c, package):
    """Install the latest built package from a PKG subdirectory."""
    pkg_dir = internal_utils.get_path("pkg") / package
    tarballs = sorted(pkg_dir.glob("*.pkg.tar*"), key=lambda p: p.stat().st_mtime)
    if not tarballs:
        raise SystemExit(f"No built package found in {pkg_dir}")
    subprocess.run(["sudo", "pacman", "-U", str(tarballs[-1])], check=True)
