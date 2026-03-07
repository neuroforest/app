"""
Load environment config, chdir to NF_DIR, and prepare submodules.
"""

import getpass
import os
import secrets
import subprocess

import invoke

from neuro.utils import build_utils, config, internal_utils, network_utils, terminal_style


LOCAL_SUBMODULES = [
    "neuro",
    "desktop"
]

SUBMODULES = [
    "neuro",
    "desktop",
    "tw5",
    "tw5-plugins/neuroforest/core",
    "tw5-plugins/neuroforest/front",
    "tw5-plugins/neuroforest/neo4j-syncadaptor",
    "tw5-plugins/neuroforest/basic",
    "tw5-plugins/neuroforest/mobile",
]


def reset_submodule(path, branch_name, remote=None):
    """Reset submodule to a branch. If remote is given, fetch first and reset to remote/branch."""
    with build_utils.chdir(path):
        if remote:
            subprocess.run(["git", "fetch", remote], check=True, capture_output=True)
        target = f"{remote}/{branch_name}" if remote else branch_name
        result = subprocess.run(
            ["git", "rev-parse", "--short", target],
            check=True, capture_output=True, text=True
        )
        commit = result.stdout.strip()
        with terminal_style.step(f"Reset {path} to {target} ({commit})"):
            subprocess.run(["git", "reset", "--hard", target], check=True, capture_output=True)
            subprocess.run(["git", "clean", "-fdx"], check=True, capture_output=True)


@invoke.task
def env(c, environment=None):
    """Load config and chdir to NF_DIR."""
    nf_dir = internal_utils.get_path("nf")
    if environment:
        os.environ["ENVIRONMENT"] = environment
    config.main()
    terminal_style.header(f"Environment [{os.environ['ENVIRONMENT']}] {nf_dir}")
    try:
        os.chdir(nf_dir)
    except FileNotFoundError:
        raise invoke.exceptions.Exit("Invalid directory: {}")


@invoke.task(pre=[env])
def nenv(c):
    """Create virtualenv and install neuro."""
    with terminal_style.step("Installing neuro"):
        subprocess.run(["python3", "-m", "venv", "nenv"], check=True, capture_output=True)
        subprocess.run(["nenv/bin/pip", "install", "./neuro"], check=True, capture_output=True)
    nenv_bin = os.path.abspath("nenv/bin")
    if nenv_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = nenv_bin + os.pathsep + os.environ.get("PATH", "")


@invoke.task(pre=[env], iterable="components")
def rsync(c, components):
    """Rsync local submodules (neuro, desktop) into app/."""
    if not components:
        components = LOCAL_SUBMODULES
    for component in components:
        source = str(internal_utils.get_path(component)) + "/"
        dest = internal_utils.get_path("nf") / component
        build_utils.rsync_local(source, dest, component)

    if "neuro" in components:
        nenv(c)


@invoke.task(pre=[env], iterable="components")
def master(c, components):
    """Reset all submodules to their configured branches."""
    if not components:
        components = SUBMODULES
    for component in components:
        reset_submodule(component, "master")


@invoke.task(pre=[env], iterable="components")
def develop(c, components):
    """Fetch and reset NF submodules to origin/develop."""
    if not components:
        components = SUBMODULES
    for component in components:
        reset_submodule(component, "develop", remote="origin")


@invoke.task(pre=[env], iterable="components")
def branch(c, branch_name, components):
    """Reset submodules to a branch, with fallback to configured branch."""
    if not components:
        components = SUBMODULES
    for component in components:
        reset_submodule(component, branch_name)


@invoke.task(pre=[env])
def init(c):
    """Initialize per-user XDG directories and config for system-mode installs."""
    username = getpass.getuser()
    nf_config = os.environ.get("NF_CONFIG", "")
    nf_data = os.environ.get("NF_DATA", "")
    nf_state = os.environ.get("NF_STATE", "")
    nf_cache = os.environ.get("NF_CACHE", "")

    # Create XDG directory structure
    dirs = [
        nf_config,
        os.path.join(nf_data, "storage"),
        os.path.join(nf_data, "archive"),
        os.path.join(nf_state, "logs"),
        nf_cache,
    ]
    with terminal_style.step("Creating XDG directories"):
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    # Generate per-user .env.local
    env_local_path = os.path.join(nf_config, ".env.local")
    if os.path.exists(env_local_path):
        terminal_style.header(f"User config already exists: {env_local_path}")
        return

    password = secrets.token_urlsafe(16)
    container_name = f"neurobase-{username}"
    default_http = int(os.environ["NEO4J_PORT_HTTP"])
    default_bolt = int(os.environ["NEO4J_PORT_BOLT"])
    http_port = default_http if not network_utils.is_port_in_use(default_http) else network_utils.get_free_port(start=8000, end=8999)
    bolt_port = default_bolt if not network_utils.is_port_in_use(default_bolt) else network_utils.get_free_port(start=8000, end=8999)

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

    # Reload config with the new .env.local
    config.CONFIG_INITIALIZED = False
    config.main()
