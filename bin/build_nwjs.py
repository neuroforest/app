"""
Download and install NW.js SDK
"""

import os
import shutil
import subprocess

from rich.console import Console

from neuro.utils import internal_utils, terminal_style


class Nwjs:
    def __init__(self, version=None, url=None, overwrite=False):
        self.version = version
        self.url = url
        self.overwrite = overwrite
        app_path = internal_utils.get_path("app")
        self.nwjs_dir = os.path.join(app_path, "desktop", "nwjs")
        self.tarfile_local = os.path.join(self.nwjs_dir, f"v{self.version}.tar.gz")
        self.tarfile_remote = f"{self.url}/v{self.version}/nwjs-sdk-v{self.version}-linux-x64.tar.gz"
        self.extract_temp = os.path.join(self.nwjs_dir, f"nwjs-sdk-v{self.version}-linux-x64")
        self.extract_final = os.path.join(self.nwjs_dir, f"v{self.version}")

    def download(self):
        console = Console()
        os.makedirs(self.nwjs_dir, exist_ok=True)

        if os.path.isfile(self.tarfile_local) and not self.overwrite:
            print(f"{terminal_style.SUCCESS} Download v{self.version} (cached)")
            return
        if os.path.isfile(self.tarfile_local):
            os.remove(self.tarfile_local)

        self.overwrite = True
        with console.status(f"[bold] Downloading NW.js v{self.version}...", spinner="dots"):
            subprocess.run([
                "wget", "-c", "--show-progress", "-q",
                "-O", self.tarfile_local,
                self.tarfile_remote,
            ], check=True)
        print(f"{terminal_style.SUCCESS} Download NW.js v{self.version}")

    def extract(self):
        console = Console()

        if os.path.isdir(self.extract_final) and not self.overwrite:
            print(f"{terminal_style.SUCCESS} Extract v{self.version} (cached)")
            return
        if os.path.isdir(self.extract_final):
            shutil.rmtree(self.extract_final)

        with console.status(f"[bold] Extracting NW.js v{self.version}...", spinner="dots"):
            subprocess.run([
                "tar", "-xzf", self.tarfile_local,
                "-C", self.nwjs_dir,
            ], stdout=subprocess.DEVNULL, check=True)
            os.rename(self.extract_temp, self.extract_final)
        print(f"{terminal_style.SUCCESS} Extract NW.js v{self.version}")


def main():
    nwjs = Nwjs(
        version=os.getenv("NWJS_VERSION"),
        url=os.getenv("NWJS_URL"),
    )
    nwjs.download()
    nwjs.extract()


if __name__ == "__main__":
    main()
