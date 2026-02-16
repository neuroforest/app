import os
import shutil
import subprocess

from invoke import task

from neuro.utils import internal_utils, terminal_style

from .. import setup


def _resolve_version(version):
    return version or os.getenv("NWJS_VERSION")


def _nwjs_paths(version):
    app_path = internal_utils.get_path("nf")
    nwjs_dir = os.path.join(app_path, "nwjs")
    url = os.getenv("NWJS_URL")
    return {
        "nwjs_dir": nwjs_dir,
        "tarfile_local": os.path.join(nwjs_dir, f"v{version}.tar.gz"),
        "tarfile_remote": f"{url}/v{version}/nwjs-sdk-v{version}-linux-x64.tar.gz",
        "extract_temp": os.path.join(nwjs_dir, f"nwjs-sdk-v{version}-linux-x64"),
        "extract_final": os.path.join(nwjs_dir, f"v{version}"),
    }


@task(pre=[setup.setup])
def download(c, version=None, overwrite=False):
    """Download NW.js SDK tarball."""
    version = _resolve_version(version)
    p = _nwjs_paths(version)
    os.makedirs(p["nwjs_dir"], exist_ok=True)

    if os.path.isfile(p["tarfile_local"]) and not overwrite:
        print(f"{terminal_style.SUCCESS} Download v{version} (cached)")
        return
    if os.path.isfile(p["tarfile_local"]):
        os.remove(p["tarfile_local"])

    with terminal_style.step(f"Download NW.js v{version}"):
        subprocess.run([
            "wget", "-c", "--show-progress", "-q",
            "-O", p["tarfile_local"],
            p["tarfile_remote"],
        ], check=True)


@task(pre=[setup.setup])
def extract(c, version=None, overwrite=False):
    """Extract NW.js SDK tarball."""
    version = _resolve_version(version)
    p = _nwjs_paths(version)

    if os.path.isdir(p["extract_final"]) and not overwrite:
        print(f"{terminal_style.SUCCESS} Extract v{version} (cached)")
        return
    if os.path.isdir(p["extract_final"]):
        shutil.rmtree(p["extract_final"])

    with terminal_style.step(f"Extract NW.js v{version}"):
        subprocess.run([
            "tar", "-xzf", p["tarfile_local"],
            "-C", p["nwjs_dir"],
        ], stdout=subprocess.DEVNULL, check=True)
        os.rename(p["extract_temp"], p["extract_final"])


@task(pre=[setup.setup])
def get(c, version=None, overwrite=False):
    """Download and extract NW.js SDK."""
    download(c, version=version, overwrite=overwrite)
    extract(c, version=version, overwrite=overwrite)
