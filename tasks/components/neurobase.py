import logging
import os
import subprocess
import sys
import time

import invoke
import neo4j

from neuro.utils import docker_tools
from neuro.utils import internal_utils, network_utils, terminal_components, terminal_style

from tasks.actions import setup


def verify_neo4j(timeout=60):
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
def create(c, name=None):
    """Create the neurobase docker container if it doesn't exist."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if docker_tools.container_exists(base_name):
        return

    with terminal_style.step(f"Compose NeuroBase: {base_name}"):
        result = subprocess.run(["docker", "compose", "up", "-d"], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise SystemExit(1)


@invoke.task(pre=[setup.env, create])
def start(c, name=None):
    """Start the neurobase docker container and wait for Neo4j."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")
    bolt_port = int(os.getenv("NEO4J_PORT_BOLT", 7687))

    if not docker_tools.container_exists(base_name):
        print(f"{terminal_style.FAIL} NeuroBase container does not exist: {base_name}")
        raise SystemExit(1)

    with terminal_style.step(f"Start NeuroBase instance: {base_name}"):
        if not docker_tools.container_running(base_name):
            subprocess.run(["docker", "start", base_name], capture_output=True)
        network_utils.wait_for_socket("127.0.0.1", bolt_port, timeout=60)
        verify_neo4j()


@invoke.task(pre=[setup.env])
def stop(c, name=None):
    """Stop the neurobase docker container."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if not docker_tools.container_running(base_name):
        print(f"{terminal_style.SUCCESS} Already stopped: {base_name}")
        return

    with terminal_style.step(f"Stop NeuroBase instance: {base_name}"):
        subprocess.run(["docker", "stop", base_name], capture_output=True)


@invoke.task(pre=[setup.env, stop])
def backup(c, name=None):
    """Backup the neurobase docker container and clean up temporary artifacts."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    container = docker_tools.Container(name=base_name)
    with terminal_style.step(f"Backup '{base_name}' to {internal_utils.get_path('archive')}"):
        container.backup()
        container.clean()


@invoke.task(pre=[setup.env, stop])
def delete(c, name=None):
    """Remove the neurobase container and its associated volumes."""
    if name:
        base_name = name
    else:
        base_name = os.getenv("BASE_NAME")

    if not docker_tools.container_exists(base_name):
        print(f"{terminal_style.FAIL} NeuroBase '{base_name}' not found")
        return

    if not terminal_components.bool_prompt(f"Delete '{base_name}' and its volumes?"):
        raise SystemExit("Aborting delete.")

    volumes = docker_tools.get_container_volumes(base_name)

    with terminal_style.step(f"Remove container: {base_name}"):
        subprocess.run(["docker", "rm", base_name], capture_output=True)

    for vol in volumes:
        with terminal_style.step(f"Remove volume: {vol}"):
            subprocess.run(["docker", "volume", "rm", vol], capture_output=True)
