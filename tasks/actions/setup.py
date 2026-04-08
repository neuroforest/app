"""
Load environment config, chdir to APP_DIR, and manage submodules.
"""

import getpass
import os
import secrets
import subprocess

import invoke

from neuro.utils import build_utils, config, internal_utils, network_utils, terminal_style


def get_nenv_dir():
    return os.path.expanduser(os.environ["NENV"])


def reset_submodule(path, branch_name, remote=None):
    """Reset submodule to a branch. If remote is given, fetch first and reset to remote/branch."""
    with build_utils.chdir(path):
        if remote:
            subprocess.run(["git", "fetch", remote], check=True, capture_output=build_utils.quiet())
        target = f"{remote}/{branch_name}" if remote else branch_name
        result = subprocess.run(
            ["git", "rev-parse", "--short", target],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return
        commit = result.stdout.strip()
        with terminal_style.step(f"Reset {path} to {target} ({commit})"):
            subprocess.run(["git", "reset", "--hard", target], check=True, capture_output=build_utils.quiet())
            subprocess.run(["git", "clean", "-fdx"], check=True, capture_output=build_utils.quiet())


@invoke.task
def env(c, environment=None):
    """Load config and chdir to APP_DIR."""
    nf_dir = internal_utils.get_path("app")
    if environment:
        os.environ["ENVIRONMENT"] = environment
    config.main()
    env_name = os.environ.get("ENVIRONMENT", "DEVELOP")
    if env_name != "PRODUCTION" and not build_utils.quiet():
        terminal_style.header(f"Environment [{env_name}] {nf_dir}")
    try:
        os.chdir(nf_dir)
    except FileNotFoundError:
        raise invoke.exceptions.Exit("Invalid directory: {}")


@invoke.task(pre=[env])
def nenv(c, nenv_dir=None):
    """Create virtualenv and install neuro."""
    default = nenv_dir is None
    if nenv_dir is None:
        nenv_dir = get_nenv_dir()
    with terminal_style.step("Installing neuro"):
        subprocess.run(
            ["uv", "sync", "--frozen", "--project", "./neuro", "--extra", "dev"],
            env={**os.environ, "UV_PROJECT_ENVIRONMENT": os.path.abspath(nenv_dir)},
            check=True, capture_output=build_utils.quiet()
        )
    if default:
        nenv_bin = os.path.join(nenv_dir, "bin")
        if nenv_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = nenv_bin + os.pathsep + os.environ.get("PATH", "")


@invoke.task(pre=[env], iterable="components")
def master(c, components, remote="origin"):
    """Reset given submodules to master."""
    for component in components:
        reset_submodule(component, "master", remote=remote)


@invoke.task(pre=[env], iterable="components")
def develop(c, components, remote="origin"):
    """Reset given submodules to origin/develop."""
    for component in components:
        reset_submodule(component, "develop", remote=remote)


@invoke.task(pre=[env], iterable="components")
def branch(c, branch_name, components):
    """Reset given submodules to a branch."""
    for component in components:
        reset_submodule(component, branch_name)


@invoke.task(pre=[env])
def init(c):
    """Initialize per-user XDG directories and config for production installs."""
    if os.environ.get("ENVIRONMENT") != "PRODUCTION":
        return

    username = getpass.getuser()
    nf_config = os.environ.get("NF_CONFIG", "")
    nf_data = os.environ.get("NF_DATA", "")
    nf_state = os.environ.get("NF_STATE", "")
    nf_cache = os.environ.get("NF_CACHE", "")

    # Create XDG directory structure
    dirs = [
        nf_cache,
        nf_config,
        nf_data,
        nf_state
    ]

    # Generate per-user env
    env_local_path = os.path.join(nf_config, "env.production")
    if os.path.exists(env_local_path):
        print(f"{terminal_style.SUCCESS} User config already exists: {env_local_path}")
        return

    with terminal_style.step("Creating XDG directories"):
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    password = secrets.token_urlsafe(16)
    container_name = f"neurobase-{username}"
    default_http = int(os.environ["NEO4J_PORT_HTTP"])
    default_bolt = int(os.environ["NEO4J_PORT_BOLT"])
    defaults_free = (
        not network_utils.is_port_in_use(default_http)
        and not network_utils.is_port_in_use(default_bolt)
    )
    if defaults_free:
        http_port, bolt_port = default_http, default_bolt
    else:
        http_port, bolt_port = network_utils.get_free_ports(2)

    env_content = (
        f"ENVIRONMENT=PRODUCTION\n"
        f"NEO4J_PASSWORD={password}\n"
        f"\n"
        f"# Per-user NeuroBase container\n"
        f"BASE_NAME={container_name}\n"
        f"NEO4J_PORT_HTTP={http_port}\n"
        f"NEO4J_PORT_BOLT={bolt_port}\n"
        f"NEO4J_URI=bolt://127.0.0.1:{bolt_port}\n"
    )

    with terminal_style.step(f"Generating {env_local_path}"):
        with open(env_local_path, "w") as f:
            f.write(env_content)

    # Reload config with the new env
    config.CONFIG_INITIALIZED = False
    config.main()
