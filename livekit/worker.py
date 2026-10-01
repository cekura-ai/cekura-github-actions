#!/usr/bin/env python3
"""Run a pull request's LiveKit Agents worker inside the GitHub runner.

Subcommands:
  start   write the env file, start the container, wait until it registers
  stop    print the worker's logs and remove the container

LiveKit workers connect out to the LiveKit server, so a worker running here
registers with the customer's LiveKit project exactly as a deployed one would.
It registers under ``<base>-pr-<number>``, and Cekura dispatches to that name
with ``livekit_data.agent_name``.

The name reaches the worker two ways: ``LIVEKIT_AGENT_NAME_OVERRIDE``, which
livekit-agents 1.6+ applies over any name set in code, and the variable named
by ``AGENT_NAME_ENV`` for older bots that read their name themselves. The
worker's own "registered worker" log line is then checked: a worker that
registered under any other name, or none, is stopped at once. With no name it
would be dispatched automatically to every new room in the project, real
calls included; with the production name it would join production's pool.

Standard library only; every input arrives as an environment variable.
"""

import os
import re
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
from naming import Failure, output, preview_name  # noqa: E402

RESERVED = {"LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_AGENT_NAME_OVERRIDE"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REGISTERED_NAME = re.compile(r'"agent_name":\s*"([^"]*)"')


def docker(*args, check=True, capture=True):
    proc = subprocess.run(["docker", *args], capture_output=capture, text=True)
    if check and proc.returncode != 0:
        raise Failure(f"docker {args[0]} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def parse_env(text, reserved=frozenset()):
    """KEY=VALUE lines from the `env` input; blank lines and # comments skipped."""
    pairs = []
    for number, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not ENV_NAME.match(key):
            raise Failure(f"env line {number} is not KEY=VALUE.")
        if key in reserved:
            raise Failure(f"env sets {key}, which this action sets itself; pass LiveKit "
                          "settings as the livekit_* inputs.")
        pairs.append((key, value))
    return pairs


def write_env_file(path, name, env):
    for required in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not env.get(required, "").strip():
            raise Failure(f"{required.lower()} is empty. Is the repository secret set?")
    agent_name_env = env.get("AGENT_NAME_ENV", "LIVEKIT_AGENT_NAME").strip()
    if not ENV_NAME.match(agent_name_env) or agent_name_env in RESERVED - {"LIVEKIT_AGENT_NAME_OVERRIDE"}:
        raise Failure(f"agent_name_env {agent_name_env!r} must be an environment variable name "
                      "other than LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET.")
    lines = [(k, env[k].strip()) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")]
    lines.append(("LIVEKIT_AGENT_NAME_OVERRIDE", name))
    if agent_name_env != "LIVEKIT_AGENT_NAME_OVERRIDE":
        lines.append((agent_name_env, name))
    lines.extend(parse_env(env.get("WORKER_ENV"), reserved=RESERVED | {agent_name_env}))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for key, value in lines:
            if "\n" in value:
                raise Failure(f"{key} contains a newline, which a Docker env file cannot carry.")
            f.write(f"{key}={value}\n")
    return agent_name_env


def running(container):
    proc = docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", container, check=False)
    if proc.returncode != 0:
        return False, None
    state, code = proc.stdout.split()
    return state == "true", int(code)


def logs(container):
    proc = docker("logs", container, check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def check_registered_name(container, line, name, allow_unverified=False):
    """Stop the worker unless it registered under exactly the preview name."""
    match = REGISTERED_NAME.search(line)
    if match is None:
        if allow_unverified:
            print(f"::warning::The worker's registration line does not report its agent name, so it "
                  f"was not checked; make sure it registers as {name}: {line.strip()}")
            print(f"Worker registered with LiveKit (unverified, expected as {name})")
            return
        docker("rm", "-f", container, check=False)
        raise Failure(
            "The worker's registration line does not say which agent name it registered under, "
            "so it may be taking production's calls or every room's. It has been stopped. Use "
            "livekit-agents 1.6+ with its default logging, or set allow_unverified_agent_name "
            "once you have confirmed the worker reads its name from the environment."
        )
    registered = match.group(1)
    if registered == name:
        print(f"✅ Worker registered with LiveKit as {name}")
        return
    docker("rm", "-f", container, check=False)
    if not registered:
        raise Failure(
            "The worker registered with no agent name, so LiveKit would dispatch it to every new "
            "room in the project, real calls included. It has been stopped. Upgrade to "
            "livekit-agents 1.6+ or read agent_name from the environment."
        )
    raise Failure(
        f"The worker registered as {registered!r}, not {name!r}, so it would have taken calls "
        f"dispatched to {registered!r}. It has been stopped. Upgrade to livekit-agents 1.6+ or "
        "read agent_name from the environment."
    )


def start():
    env = os.environ
    name = preview_name(env.get("AGENT_NAME_BASE"), env.get("PR_NUMBER"))
    image = env["IMAGE"]
    container = env.get("CONTAINER") or "cekura-livekit-worker"
    pattern = env.get("READY_PATTERN") or "registered worker"
    timeout = int(env.get("READY_TIMEOUT") or "300")
    env_file = os.path.join(env.get("RUNNER_TEMP") or ".", "cekura-livekit-worker.env")

    docker("rm", "-f", container, check=False)
    try:
        agent_name_env = write_env_file(env_file, name, env)
        args = ["run", "-d", "--name", container, "--env-file", env_file, image]
        command = shlex.split(env.get("COMMAND") or "")
        print(f"Starting {image} as LiveKit agent {name} ({agent_name_env}={name})")
        docker(*args, *command)
    finally:
        # It holds the LiveKit secret and every provider key.
        if os.path.exists(env_file):
            os.remove(env_file)
    output("agent_name", name)
    output("container", container)

    deadline = time.time() + timeout
    while time.time() < deadline:
        alive, code = running(container)
        text = logs(container)
        line = next((l for l in text.splitlines() if pattern.lower() in l.lower()), None)
        if line is not None:
            check_registered_name(container, line, name,
                                  env.get("ALLOW_UNVERIFIED", "false").strip().lower() == "true")
            return
        if not alive:
            print(text[-6000:])
            raise Failure(f"The worker exited (code {code}) before registering with LiveKit; its logs are above.")
        time.sleep(3)
    print(logs(container)[-6000:])
    raise Failure(f"The worker did not log {pattern!r} within {timeout}s; its logs are above.")


def stop():
    container = os.environ.get("CONTAINER") or "cekura-livekit-worker"
    alive, code = running(container)
    if code is None:
        print(f"No worker container {container}; nothing to stop")
        return
    text = logs(container)
    print(f"::group::LiveKit worker logs ({container})")
    print(text[-200000:])
    print("::endgroup::")
    docker("rm", "-f", container, check=False)
    print(f"Removed {container}" + ("" if alive else f" (it had already exited, code {code})"))


def main(argv):
    commands = {"start": start, "stop": stop}
    if len(argv) != 2 or argv[1] not in commands:
        print(f"usage: worker.py {{{'|'.join(commands)}}}", file=sys.stderr)
        return 2
    try:
        commands[argv[1]]()
    except Failure as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
