"""Shared by the preview actions: PR-scoped names and step outputs."""

import os
import re

NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
MAX_NAME = 63


class Failure(Exception):
    """Ends the step with a message instead of a traceback."""


def output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"{key}={value}")


def preview_name(base, pr_number, max_len=MAX_NAME):
    """Return <base>-pr-<number>.

    The name is built, never taken verbatim, so a misconfigured workflow
    cannot deploy over, register as, or delete the production agent.
    """
    base = (base or "").strip()
    pr_number = (pr_number or "").strip()
    if not NAME_RE.match(base):
        raise Failure(
            f"agent_name_base {base!r} must be lowercase letters, digits and hyphens, "
            "starting and ending with a letter or digit."
        )
    if not pr_number.isdigit():
        raise Failure(
            f"No pull request number (got {pr_number!r}). Run this on a pull_request event "
            "or pass pr_number."
        )
    name = f"{base}-pr-{pr_number}"
    if len(name) > max_len:
        raise Failure(f"Preview name {name!r} is longer than {max_len} characters; shorten agent_name_base.")
    return name
