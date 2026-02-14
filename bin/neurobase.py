import os
import subprocess


CONTAINER_NAME = os.getenv("BASE_NAME")


def container_exists():
    result = subprocess.run(
        ["docker", "container", "inspect", CONTAINER_NAME],
        capture_output=True,
    )
    return result.returncode == 0


def container_running():
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def main():
    if container_running():
        print(f"Container '{CONTAINER_NAME}' is already running.")
        return

    if container_exists():
        print(f"Starting existing container '{CONTAINER_NAME}'...")
        subprocess.run(["docker", "start", CONTAINER_NAME])
    else:
        print(f"Creating container '{CONTAINER_NAME}'...")
        subprocess.run(["docker", "compose", "up", "-d"])


if __name__ == "__main__":
    main()
