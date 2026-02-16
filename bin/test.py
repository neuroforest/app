"""
Unified test runner for NeuroForest.

Usage:
    app/bin/test.py local [COMPONENT...] [-- pytest-args]
    app/bin/test.py production [-- pytest-args]

Components: app, neuro, tw5, tw5-plugins
"""

import argparse
import importlib.util
import logging
import os
import subprocess
import sys

import pytest
from rich.console import Console

from neuro.utils import terminal_style, internal_utils


ALL_LOCAL_COMPONENTS = ["app", "neuro", "tw5"]


def reset_submodule(path, branch):
    with internal_utils.chdir(path):
        subprocess.run(["git", "fetch", "origin"], check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], check=True)
        subprocess.run(["git", "clean", "-fdx"], check=True)


def prepare_neuro_local():
    rsync_command = [
        "rsync",
        "-va",
        internal_utils.get_path("neuro"),
        internal_utils.get_path("app"),
        "--delete"
    ]
    with Console().status("[bold] Sync neuro...", spinner="dots"):
        subprocess.run(rsync_command, check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Sync neuro")

    install_command = [
        internal_utils.get_path("app") + "/nenv/bin/pip",
        "install",
        internal_utils.get_path("app") + "/neuro"
    ]
    with Console().status("[bold] Install neuro...", spinner="dots"):
        subprocess.run(install_command, check=True, capture_output=True)
    print(f"{terminal_style.SUCCESS} Install neuro")


def load_module(name, script_name):
    spec = importlib.util.spec_from_file_location(
        name,
        os.path.join(internal_utils.get_path("app"), f"bin/{script_name}"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_app(pytest_args):
    """Run app tests: nenv/bin/pytest tests"""
    print(f"\n{'='*60}")
    print(f"  Running app tests")
    print(f"{'='*60}\n")
    args = ["tests"] + pytest_args
    return pytest.main(args)


def test_neuro(pytest_args):
    """Prepare local neuro, run nenv/bin/pytest neuro/tests"""
    print(f"\n{'='*60}")
    print(f"  Running neuro tests")
    print(f"{'='*60}\n")
    prepare_neuro_local()
    args = ["neuro/tests"] + pytest_args
    return pytest.main(args)


def test_tw5():
    """Build tw5, run tw5/bin/test.sh"""
    print(f"\n{'='*60}")
    print(f"  Running tw5 tests")
    print(f"{'='*60}\n")
    build_tw5 = load_module("build_tw5", "build_tw5.py")
    build_tw5.main()
    tw5_path = internal_utils.get_path("tw5")
    result = subprocess.run(
        ["bin/test.sh"],
        cwd=tw5_path,
    )
    return result.returncode


def test_tw5_plugins():
    """Placeholder for future plugin tests"""
    print(f"\n{'='*60}")
    print(f"  tw5-plugins tests")
    print(f"{'='*60}\n")
    print("tw5-plugins tests not yet implemented")
    return 0


def test_production(pytest_args):
    """Build desktop, run production tests (stub)"""
    print(f"\n{'='*60}")
    print(f"  Running production tests")
    print(f"{'='*60}\n")
    build_desktop = load_module("build_desktop", "build_desktop.py")
    build_desktop.main()
    print("production tests not yet implemented")
    return 0


def run_local(components, pytest_args):
    if not components:
        components = ALL_LOCAL_COMPONENTS

    results = {}
    for component in components:
        if component == "app":
            results["app"] = test_app(pytest_args)
        elif component == "neuro":
            results["neuro"] = test_neuro(pytest_args)
        elif component == "tw5":
            results["tw5"] = test_tw5()
        elif component == "tw5-plugins":
            results["tw5-plugins"] = test_tw5_plugins()
        else:
            print(f"Unknown component: {component}")
            results[component] = 1

    print(f"\n{'='*60}")
    print(f"  Test Summary")
    print(f"{'='*60}")
    for name, code in results.items():
        status = terminal_style.SUCCESS if code == 0 else "FAIL"
        print(f"  {status} {name}")

    return 1 if any(code != 0 for code in results.values()) else 0


def main():
    logging.basicConfig(level=logging.INFO)
    os.environ["ENVIRONMENT"] = "TESTING"

    parser = argparse.ArgumentParser(description="NeuroForest test runner")
    subparsers = parser.add_subparsers(dest="command")

    local_parser = subparsers.add_parser("local", help="Run local component tests")
    local_parser.add_argument(
        "components", nargs="*",
        choices=ALL_LOCAL_COMPONENTS + ["tw5-plugins"],
        help="Components to test (default: all)",
    )
    local_parser.add_argument("pytest_args", nargs="*", help=argparse.SUPPRESS)

    prod_parser = subparsers.add_parser("production", help="Build and run production tests")
    prod_parser.add_argument("pytest_args", nargs="*", help=argparse.SUPPRESS)

    # Split on -- to separate our args from pytest args
    argv = sys.argv[1:]
    if "--" in argv:
        split_idx = argv.index("--")
        our_args = argv[:split_idx]
        pytest_args = argv[split_idx + 1:]
    else:
        our_args = argv
        pytest_args = []

    args = parser.parse_args(our_args)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    app_path = os.getenv("NF_DIR")
    with internal_utils.chdir(app_path):
        from neuro.utils import config
        config.main()

        if args.command == "local":
            exit_code = run_local(args.components, pytest_args)
        elif args.command == "production":
            exit_code = test_production(pytest_args)
        else:
            parser.print_help()
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
