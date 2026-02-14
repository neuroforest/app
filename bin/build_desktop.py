"""
Build NeuroForest desktop application

Assembles NW.js SDK, TiddlyWiki, and desktop source into a build directory.
"""

import json
import os
import shutil
import subprocess
import sys
import time

from rich.console import Console

from neuro.utils import internal_utils, terminal_style


BUILD_DIR = "build"


def copy_nwjs(build_dir):
    console = Console()
    app_path = internal_utils.get_path("app")
    nwjs_version = os.getenv("NWJS_VERSION")
    nwjs_source = os.path.join(app_path, "desktop", "nwjs", f"v{nwjs_version}")

    if not os.path.isdir(nwjs_source):
        print(f"  NW.js v{nwjs_version} not found. Run build_nwjs.py first.")
        return False

    with console.status("[bold] Copy NW.js...", spinner="dots"):
        subprocess.run([
            "rsync", "-a", "--delete",
            nwjs_source + "/",
            build_dir,
        ], check=True, stdout=subprocess.DEVNULL)
    print(f"{terminal_style.SUCCESS} Copy NW.js v{nwjs_version}")
    return True


def copy_tw5(build_dir):
    console = Console()
    tw5_path = internal_utils.get_path("tw5")

    with console.status("[bold] Copy TW5...", spinner="dots"):
        subprocess.run([
            "rsync", "-a", "--delete",
            tw5_path + "/",
            os.path.join(build_dir, "tw5"),
        ], check=True, stdout=subprocess.DEVNULL)
        git_dir = os.path.join(build_dir, "tw5", ".git")
        if os.path.isdir(git_dir):
            shutil.rmtree(git_dir)
    print(f"{terminal_style.SUCCESS} Copy TW5")


def copy_source(build_dir):
    console = Console()
    app_path = internal_utils.get_path("app")
    source_dir = os.path.join(app_path, "desktop", "source")

    with console.status("[bold] Copy desktop source...", spinner="dots"):
        subprocess.run([
            "rsync", "-a", "--delete",
            source_dir + "/",
            os.path.join(build_dir, "source"),
        ], check=True, stdout=subprocess.DEVNULL)
        os.remove(os.path.join(build_dir, "source", "package.json"))
    print(f"{terminal_style.SUCCESS} Copy desktop source")


def read_version():
    app_path = internal_utils.get_path("app")
    version_path = os.path.join(app_path, "desktop", "VERSION")
    with open(version_path) as f:
        return f.read().strip()


def generate_package_json(build_dir):
    app_path = internal_utils.get_path("app")
    source_path = os.path.join(app_path, "desktop", "source", "package.json")

    with open(source_path) as f:
        package = json.load(f)

    app_name = os.getenv("APP_NAME", "NeuroDesktop")
    version = read_version()
    package["name"] = app_name
    package["version"] = version
    user_data_dir = os.path.join(build_dir, "user-data")
    chromium_args = package.get("chromium-args", "")
    package["chromium-args"] = f"{chromium_args} --user-data-dir={user_data_dir}"

    with open(os.path.join(build_dir, "package.json"), "w") as f:
        json.dump(package, f, indent=2)
    print(f"{terminal_style.SUCCESS} Generate package.json ({app_name} v{version})")


def install_node_modules(build_dir):
    console = Console()
    with console.status("[bold] Installing node modules...", spinner="dots"):
        subprocess.run([
            "npm", "install", "-l",
            "fs", "neo4j-driver",
        ], cwd=build_dir, stdout=subprocess.DEVNULL)
    print(f"{terminal_style.SUCCESS} Install node modules")


def build(build_dir=None):
    if build_dir is None:
        app_path = internal_utils.get_path("app")
        build_dir = os.path.join(app_path, BUILD_DIR)

    os.makedirs(build_dir, exist_ok=True)
    version = read_version()
    print(f"Building {os.getenv('APP_NAME', 'NeuroDesktop')} v{version}")
    start_time = time.time()

    if not copy_nwjs(build_dir):
        return
    copy_tw5(build_dir)
    copy_source(build_dir)
    generate_package_json(build_dir)
    install_node_modules(build_dir)

    elapsed = time.time() - start_time
    print(f"{terminal_style.SUCCESS} {terminal_style.BOLD}Finished in {elapsed:.1f}s{terminal_style.RESET}")


def main():
    if len(sys.argv) > 1:
        build_path = sys.argv[1]
        if not os.path.isabs(build_path):
            build_path = os.path.abspath(build_path)
        build(build_path)
    else:
        build()


if __name__ == "__main__":
    main()
