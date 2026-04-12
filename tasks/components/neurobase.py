import logging
import os
import subprocess
import sys
import time

import invoke
import neo4j

from neuro.base.api import NeuroBase
from neuro.utils import docker_tools
from neuro.utils import build_utils, internal_utils, network_utils, terminal_components, terminal_style

from tasks.actions import setup


def verify_neo4j(timeout=32):
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    deadline = time.monotonic() + timeout
    while True:
        driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
            return
        except (neo4j.exceptions.ServiceUnavailable, Exception):
            if time.monotonic() >= deadline:
                print(f"Neo4j inaccessible: {uri}")
                base_name = os.getenv("BASE_NAME")
                logs = subprocess.run(
                    ["docker", "logs", "--tail", "50", base_name],
                    capture_output=True, text=True,
                )
                print(logs.stdout)
                print(logs.stderr)
                sys.exit(1)
            time.sleep(0.5)
        finally:
            driver.close()


@invoke.task(pre=[setup.env])
def create(c):
    """Create the neurobase docker container if it doesn't exist."""
    base_name = os.getenv("BASE_NAME")

    if docker_tools.container_exists(base_name):
        return

    with terminal_components.step(f"Compose NeuroBase: {base_name}"):
        result = subprocess.run(["docker", "compose", "up", "-d"], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise SystemExit(1)


@invoke.task(pre=[setup.env])
def start(c):
    """Start the neurobase docker container and wait for Neo4j."""
    docker_tools.verify_access()
    base_name = os.getenv("BASE_NAME")
    create(c)
    bolt_port = int(os.getenv("NEO4J_PORT_BOLT", 7687))

    if not docker_tools.container_exists(base_name):
        print(f"{terminal_style.FAIL} NeuroBase container does not exist: {base_name}")
        raise SystemExit(1)

    with terminal_components.step(f"Start NeuroBase instance: {base_name}"):
        if not docker_tools.container_running(base_name):
            subprocess.run(["docker", "start", base_name], capture_output=build_utils.quiet())
        network_utils.wait_for_socket("127.0.0.1", bolt_port, timeout=32)
        verify_neo4j()


@invoke.task(pre=[setup.env])
def count(c):
    """Print the number of nodes in the neurobase."""
    with NeuroBase() as nb:
        print(nb.count())


@invoke.task(pre=[setup.env])
def clear(c, confirmed=False):
    """Clear all data from the test database after confirmation."""
    base_name = os.getenv("BASE_NAME")
    start(c)
    with NeuroBase() as nb:
        node_count = nb.count()
        if node_count == 0:
            return
        if not confirmed:
            if not terminal_components.bool_prompt(f"Clear '{base_name}'? ({node_count} nodes will be deleted)"):
                raise SystemExit("Aborting clear.")
        with terminal_components.step(f"Clear test database: {base_name}"):
            nb.clear(confirm=True)


@invoke.task(pre=[setup.env])
def stop(c):
    """Stop the neurobase docker container."""
    base_name = os.getenv("BASE_NAME")

    if not docker_tools.container_running(base_name):
        print(f"{terminal_style.SUCCESS} Already stopped: {base_name}")
        return

    with terminal_components.step(f"Stop NeuroBase instance: {base_name}"):
        subprocess.run(["docker", "stop", base_name], capture_output=build_utils.quiet())


@invoke.task(pre=[setup.env])
def backup(c):
    """Backup the neurobase docker container and clean up temporary artifacts."""
    base_name = os.getenv("BASE_NAME")
    stop(c)

    container = docker_tools.Container(name=base_name)
    with terminal_components.step(f"Backup '{base_name}' to {internal_utils.get_path('archive')}"):
        container.backup()
        container.clean()


@invoke.task(pre=[setup.env])
def restore(c, backup=None):
    """Restore the neurobase container from a backup."""
    base_name = os.getenv("BASE_NAME")
    container = docker_tools.Container(name=base_name)

    if not backup:
        archive_dir = internal_utils.get_path("archive") / "base"
        backups = [
            b for b in sorted(str(p) for p in __import__("pathlib").Path(archive_dir).iterdir())
            if docker_tools.Container.is_valid_backup(b) and base_name in b.rsplit("/", 1)[1]
        ]
        if not backups:
            print(f"{terminal_style.FAIL} No backups found for '{base_name}'")
            raise SystemExit(1)
        backup = terminal_components.selector([b.rsplit("/", 1)[1] for b in backups])
        if not backup:
            raise SystemExit("Aborting restore.")

    # Resolve backup path
    if not docker_tools.Container.is_valid_backup(backup):
        backup = str(internal_utils.get_path("archive") / "base" / backup)
    if not docker_tools.Container.is_valid_backup(backup):
        print(f"{terminal_style.FAIL} Invalid backup: {backup}")
        raise SystemExit(1)
    container.backup_location = backup

    stop(c)

    data_volume = f"{base_name}-data"
    with terminal_components.step(f"Restore data: {base_name}"):
        container.restore_data(data_volume)

    start(c)


@invoke.task(pre=[setup.env])
def delete(c):
    """Remove the neurobase container and its associated volumes."""
    base_name = os.getenv("BASE_NAME")
    stop(c)

    if not docker_tools.container_exists(base_name):
        print(f"{terminal_style.FAIL} NeuroBase '{base_name}' not found")
        return

    if not terminal_components.bool_prompt(f"Delete '{base_name}' and its volumes?", default=True):
        raise SystemExit("Aborting delete.")

    volumes = docker_tools.get_container_volumes(base_name)

    with terminal_components.step(f"Remove container: {base_name}"):
        subprocess.run(["docker", "rm", base_name], capture_output=build_utils.quiet())

    for vol in volumes:
        with terminal_components.step(f"Remove volume: {vol}"):
            subprocess.run(["docker", "volume", "rm", vol], capture_output=build_utils.quiet())
