"""
Prepare NeuroForest submodules
"""

import configparser
import os
import subprocess
import sys

from rich.console import Console

from neuro.utils import config, terminal_style, internal_utils


LOCAL_SUBMODULES = ["neuro", "desktop"]

NEUROFOREST_SUBMODULES = [
    "neuro",
    "desktop",
    "tw5-plugins/neuroforest/core",
    "tw5-plugins/neuroforest/front",
    "tw5-plugins/neuroforest/neo4j-syncadaptor",
    "tw5-plugins/neuroforest/basic",
    "tw5-plugins/neuroforest/mobile",
]


def parse_gitmodules():
    parser = configparser.ConfigParser()
    parser.read(".gitmodules")
    submodules = {}
    for section in parser.sections():
        path = parser.get(section, "path")
        submodules[path] = {
            "url": parser.get(section, "url"),
            "branch": parser.get(section, "branch", fallback="master"),
        }
    return submodules


def reset_submodule(path, branch):
    console = Console()
    with internal_utils.chdir(path):
        with console.status(f"[bold] Reset {path} to {branch}...", spinner="dots"):
            subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True)
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{branch}"],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "clean", "-fdx"], check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Reset {path} to {branch}")


def branch_exists_on_remote(branch):
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and branch in result.stdout


def rsync_local(name):
    console = Console()
    source = internal_utils.get_path(name)
    dest = internal_utils.get_path("app")
    rsync_command = [
        "rsync", "-va",
        "--filter=:- .gitignore",
        "--exclude=.git",
        "--delete",

        source, dest,
    ]
    with console.status(f"[bold] Sync {name}...", spinner="dots"):
        subprocess.run(rsync_command, check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Sync {name}")


def prepare_local():
    for name in LOCAL_SUBMODULES:
        rsync_local(name)


def prepare_master(submodules):
    for path, info in submodules.items():
        reset_submodule(path, info["branch"])


def prepare_develop(submodules):
    for path in NEUROFOREST_SUBMODULES:
        if path in submodules:
            reset_submodule(path, "develop")


def prepare_branch(submodules, branch):
    for path, info in submodules.items():
        with internal_utils.chdir(path):
            if branch_exists_on_remote(branch):
                target = branch
            else:
                target = info["branch"]
                print(f"  Branch '{branch}' not found for {path}, using {target}")
        reset_submodule(path, target)


def parse_arguments():
    args = sys.argv[1:]

    if len(args) == 0:
        return "local", None
    elif args[0] in ["-l", "--local"]:
        return "local", None
    elif args[0] in ["-m", "--master"]:
        return "master", None
    elif args[0] in ["-d", "--develop"]:
        return "develop", None
    elif args[0] in ["-b", "--branch"]:
        if len(args) < 2:
            print("Error: --branch requires a branch name")
            sys.exit(1)
        return "branch", args[1]
    else:
        print(f"Unknown option: {args[0]}")
        sys.exit(1)


def main():
    config.main()
    app_path = os.getenv("NF_DIR", os.getcwd())

    with internal_utils.chdir(app_path):
        mode, arg = parse_arguments()
        submodules = parse_gitmodules()

        if mode == "local":
            prepare_local()
        elif mode == "master":
            prepare_master(submodules)
        elif mode == "develop":
            prepare_develop(submodules)
        elif mode == "branch":
            prepare_branch(submodules, arg)


if __name__ == "__main__":
    main()
