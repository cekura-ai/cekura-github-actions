#!/usr/bin/env python3
"""Pipecat Cloud preview helpers for deploy-preview and delete-preview.

Subcommands:
  plan        resolve the preview name and scaling; writes step outputs
  wait-ready  poll until the deployment the last deploy asked for is serving
  delete      delete the preview (404 counts as done)

A preview is always named ``<base>-pr-<number>``. The name is built here, never
taken verbatim, so a misconfigured workflow cannot point a deploy or a delete
at the production agent.

Standard library only; every input arrives as an environment variable.
"""

import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
from naming import Failure, output, preview_name  # noqa: E402

MAX_AGENTS = 50
# Pipecat Cloud's serviceName is at most 54 characters.
MAX_PIPECAT_NAME = 54
# Total restarts across a revision's replicas, per warm agent, before it counts
# as crash-looping; waiting longer only hides the bot's own startup error.
CRASH_RESTARTS_PER_AGENT = 3
# Network errors and non-JSON answers while polling; all worth another try.
TRANSIENT = (urllib.error.URLError, OSError, http.client.HTTPException, ValueError)


def pipecat_name(base, pr_number):
    return preview_name(base, pr_number, max_len=MAX_PIPECAT_NAME)


def suite_runs(spec_path):
    """Number of calls the suite places at once: the sum of case frequencies."""
    try:
        with open(spec_path) as f:
            spec = json.load(f)
        default = int((spec.get("defaults") or {}).get("frequency") or 1)
        return sum(int(case.get("frequency") or default) for case in spec.get("scenarios") or [])
    except (OSError, ValueError, TypeError, AttributeError) as e:
        raise Failure(f"Cannot size the preview from {spec_path!r}: {e}") from None


def plan():
    env = os.environ
    name = pipecat_name(env.get("AGENT_NAME_BASE"), env.get("PR_NUMBER"))
    min_agents = env.get("MIN_AGENTS", "").strip()
    max_agents = env.get("MAX_AGENTS", "").strip()
    spec = env.get("SPEC", "").strip()

    if not max_agents:
        if spec:
            # Every case dials at once, so warm one agent per call; a cold
            # start mid-suite fails that call's session start.
            runs = suite_runs(spec)
            max_agents = str(max(1, min(runs, MAX_AGENTS)))
            print(f"Suite {spec} places {runs} call(s) at once; scaling to {max_agents}")
        else:
            max_agents = "1"
    if not min_agents:
        min_agents = max_agents
    for label, value in (("min_agents", min_agents), ("max_agents", max_agents)):
        if not value.isdigit():
            raise Failure(f"{label} must be a whole number, got {value!r}.")
    if int(min_agents) > int(max_agents):
        raise Failure(f"min_agents ({min_agents}) is above max_agents ({max_agents}).")

    output("agent_name", name)
    output("min_agents", min_agents)
    output("max_agents", max_agents)


def api(method, path):
    url = os.environ.get("PIPECAT_API_URL", "https://api.pipecat.daily.co").rstrip("/") + path
    req = urllib.request.Request(
        url, method=method, headers={"Authorization": f"Bearer {os.environ['PIPECAT_API_KEY']}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return resp.status, (json.loads(body) if body else {})


def deployment_errors(agent):
    errors = agent.get("errors") or []
    if not errors:
        return None
    return "; ".join(
        f"{e.get('code', '?')}: {e.get('message', '')}" if isinstance(e, dict) else str(e)
        for e in errors
    )


def readiness(agent, min_agents):
    """Return (ready, description) using the Pipecat Cloud CLI's own rules.

    Ready means the operator has reconciled the deployment the last deploy
    asked for (so an old revision cannot pass for the new one), the service
    is available, and as many agents of that revision are up as were asked to
    stay warm. With none kept warm, Pipecat reports ready at zero replicas.
    """
    desired = agent.get("desiredDeploymentId") or agent.get("activeDeploymentId")
    reconciled = agent.get("reconciledDeploymentId")
    available = agent.get("available", agent.get("ready", False))
    ready = agent.get("ready", False) or agent.get("activeDeploymentReady", False)
    rev = agent.get("currentRevision") or {}
    replicas = rev.get("readyReplicas") or 0
    phase = rev.get("phase") or "?"
    desc = f"phase={phase} readyReplicas={replicas}/{min_agents} available={available} ready={ready}"
    if desired and reconciled != desired:
        return False, "waiting for the operator to pick up the new deployment"
    return bool(available and ready and replicas >= min_agents), desc


def is_new_revision(agent):
    """Whether currentRevision is the deployment the last deploy asked for."""
    desired = agent.get("desiredDeploymentId") or agent.get("activeDeploymentId")
    if desired and agent.get("reconciledDeploymentId") != desired:
        return False
    revision_id = (agent.get("currentRevision") or {}).get("deploymentID")
    return not (desired and revision_id and revision_id != desired)


def crash_reason(agent, min_agents):
    """The crash reason when the new revision is restarting with nothing serving.

    Only the revision this deploy asked for counts: until the operator picks it
    up, currentRevision is the previous one, which may be the crash being fixed.
    """
    if not is_new_revision(agent):
        return None
    rev = agent.get("currentRevision") or {}
    if rev.get("phase") == "Failed":
        return "the revision failed to deploy"
    health = rev.get("health") or {}
    restarts = health.get("restartCount") or 0
    if (rev.get("readyReplicas") or 0) > 0 or restarts < CRASH_RESTARTS_PER_AGENT * max(1, min_agents):
        return None
    reason = health.get("headline") or health.get("reason") or "container keeps restarting"
    message = (health.get("message") or "").strip().splitlines()
    return f"{reason} ({restarts} restarts)" + (f": {message[-1]}" if message else "")


def wait_ready():
    name = os.environ["AGENT_NAME"]
    timeout = int(os.environ.get("WAIT_TIMEOUT") or "600")
    min_agents = int(os.environ.get("MIN_AGENTS") or "1")
    deadline = time.time() + timeout
    last = "no response yet"
    while time.time() < deadline:
        try:
            _, agent = api("GET", f"/v1/agents/{name}")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (401, 403):
                raise Failure(f"Pipecat Cloud rejected the API key (HTTP {e.code}); use a private key.") from None
        except TRANSIENT as e:
            last = f"{type(e).__name__}: {e}"
        else:
            errors = deployment_errors(agent)
            if errors:
                raise Failure(f"{name} failed to deploy: {errors}")
            ok, last = readiness(agent, min_agents)
            print(f"  {name}: {last}")
            if ok:
                print(f"✅ {name} is ready")
                return
            crash = crash_reason(agent, min_agents)
            if crash:
                raise Failure(
                    f"{name} is crash-looping: {crash}. Check `pcc agent logs {name}`."
                )
        time.sleep(10)
    raise Failure(f"{name} was not ready within {timeout}s (last: {last}). Check `pcc agent logs {name}`.")


def delete():
    env = os.environ
    name = pipecat_name(env.get("AGENT_NAME_BASE"), env.get("PR_NUMBER"))
    if not env.get("PIPECAT_API_KEY"):
        raise Failure("api_key is empty. Is the secret set, and is this a fork pull request?")
    last = None
    for attempt in range(3):
        try:
            status, _ = api("DELETE", f"/v1/agents/{name}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"{name} does not exist; nothing to delete")
                output("deleted", "false")
                return
            if e.code < 500 and e.code != 429:
                raise Failure(f"Deleting {name} failed with HTTP {e.code}.") from None
            last = f"HTTP {e.code}"
        except TRANSIENT as e:
            last = f"{type(e).__name__}: {e}"
        else:
            print(f"Deleted {name} (HTTP {status})")
            output("deleted", "true")
            return
        print(f"  delete attempt {attempt + 1}/3 failed ({last}); retrying")
        time.sleep(5)
    raise Failure(f"Deleting {name} failed ({last}); delete it with `pcc agent delete {name}`.")


def main(argv):
    commands = {"plan": plan, "wait-ready": wait_ready, "delete": delete}
    if len(argv) != 2 or argv[1] not in commands:
        print(f"usage: preview.py {{{'|'.join(commands)}}}", file=sys.stderr)
        return 2
    try:
        commands[argv[1]]()
    except Failure as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
