#!/usr/bin/env python3
"""Run many Cekura agent/scenario groups under one GitHub-level call budget.

Invoked by run-batch/action.yml; every input arrives as an environment
variable. Standard library only; a YAML batch also needs PyYAML.

A batch is a list of groups. A group either runs one agent's scenarios
(`agent_id` + `scenario_ids`) as one Cekura result, or lists two or more
`legs` that must run at the same time (e.g. a caller and a transfer target):
scenario i of every leg is started together, each leg as its own Cekura
result. A group is started only when its calls fit in the remaining
`concurrency`, so the calls in flight never exceed it.
"""

import datetime
import http.client
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque

try:
    import yaml
except ImportError:
    yaml = None

ENDPOINTS = {
    "voice": "/test_framework/v1/scenarios/run_scenarios/",
    "text": "/test_framework/v1/scenarios/run_scenarios_text/",
    "livekit_v2": "/test_framework/v1/scenarios-external/run_scenarios_livekit_v2/",
    "pipecat_v2": "/test_framework/v1/scenarios/run_scenarios_pipecat_v2/",
}
# Backend TERMINAL_RESULT_STATUSES.
TERMINAL = {"completed", "failed", "timeout", "cancelled"}
MAX_POLL_FAILURES = 7
TRANSIENT = (urllib.error.URLError, OSError, http.client.HTTPException, ValueError)
RUN_KEYS = {"agent_id", "scenario_ids", "execution_mode", "phone_number", "websocket_url",
            "livekit_data", "pipecat_data"}
LEG_KEYS = RUN_KEYS | {"name"}
GROUP_KEYS = RUN_KEYS | {"name", "frequency", "legs"}


class Failure(Exception):
    """A configuration or API error that ends the step with a message."""


class Config:
    def __init__(self, env):
        self.api_url = (env.get("API_URL") or "https://api.cekura.ai").rstrip("/")
        self.api_key = env.get("API_KEY", "")
        self.batch = env.get("BATCH", "").strip()
        self.batch_file = env.get("BATCH_FILE", "").strip()
        self.concurrency = env.get("CONCURRENCY", "").strip()
        self.frequency = env.get("FREQUENCY", "").strip() or "1"
        self.execution_mode = (env.get("EXECUTION_MODE") or "voice").strip()
        self.name = env.get("NAME", "").strip() or (
            f"GitHub run {env['GITHUB_RUN_ID']}" if env.get("GITHUB_RUN_ID") else "GitHub batch")
        self.timeout = env.get("TIMEOUT", "").strip() or "3600"
        self.poll_interval = int(env.get("POLL_INTERVAL") or "30")
        self.share_links = env.get("SHARE_LINKS", "true").strip().lower() != "false"
        self.dry_run = env.get("DRY_RUN", "false").strip().lower() == "true"
        self.output_path = env.get("GITHUB_OUTPUT")
        self.summary_path = env.get("GITHUB_STEP_SUMMARY")


def positive_int(value, where):
    if isinstance(value, bool):
        raise Failure(f"{where} must be a positive integer, got {value!r}.")
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.strip().isdigit() and int(value) >= 1:
        return int(value)
    raise Failure(f"{where} must be a positive integer, got {value!r}.")


def parse_ids(value, where):
    items = value.split(",") if isinstance(value, str) else value
    if isinstance(items, int) and not isinstance(items, bool):
        items = [items]
    if not isinstance(items, list):
        raise Failure(f"{where}.scenario_ids must be a list or a comma-separated string.")
    ids = [positive_int(i, f"{where}.scenario_ids") for i in items if str(i).strip()]
    if not ids:
        raise Failure(f"{where}.scenario_ids is empty.")
    return ids


def load_batch(cfg):
    if cfg.batch and cfg.batch_file:
        raise Failure("Set batch or batch_file, not both.")
    if cfg.batch_file:
        try:
            with open(cfg.batch_file) as f:
                text = f.read()
        except OSError as e:
            raise Failure(f"Cannot read batch_file {cfg.batch_file!r}: {e}") from None
    elif cfg.batch:
        text = cfg.batch
    else:
        raise Failure("Set batch (JSON or YAML) or batch_file.")
    try:
        data = json.loads(text)
    except ValueError:
        if yaml is None:
            raise Failure("batch is not valid JSON, and PyYAML is not installed to read it as YAML. "
                          "Use JSON, or run `pip install pyyaml` in an earlier step.") from None
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise Failure(f"batch is neither valid JSON nor valid YAML: {e}") from None
    if isinstance(data, dict) and set(data) == {"groups"}:
        data = data["groups"]
    if not isinstance(data, list) or not data:
        raise Failure("batch must be a non-empty list of groups (or {groups: [...]}).")
    return data


def provider_data(value, where):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as e:
            raise Failure(f"{where} is not valid JSON: {e}") from None
    if not isinstance(value, dict):
        raise Failure(f"{where} must be a JSON object.")
    return value


def build_side(raw, defaults, where, cfg, allowed=RUN_KEYS):
    """Validate one agent + scenario list (a single-agent group or one leg)."""
    if not isinstance(raw, dict):
        raise Failure(f"{where} must be a mapping with agent_id and scenario_ids.")
    unknown = set(raw) - allowed
    if unknown:
        raise Failure(f"{where} has unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}.")
    side = {**defaults, **raw}
    if "agent_id" not in side:
        raise Failure(f"{where}.agent_id is required.")
    if "scenario_ids" not in side:
        raise Failure(f"{where}.scenario_ids is required.")
    mode = str(side.get("execution_mode") or cfg.execution_mode)
    if mode not in ENDPOINTS:
        raise Failure(f"{where}.execution_mode must be one of {', '.join(ENDPOINTS)}, got {mode!r}.")
    out = {
        "agent_id": positive_int(side["agent_id"], f"{where}.agent_id"),
        "scenario_ids": parse_ids(side["scenario_ids"], where),
        "mode": mode,
        "extra": {},
    }
    for key, only, field in (("phone_number", "voice", "outbound_phone_number"),
                             ("websocket_url", "text", "websocket_url"),
                             ("livekit_data", "livekit_v2", "livekit_data"),
                             ("pipecat_data", "pipecat_v2", "pipecat_data")):
        if side.get(key) in (None, ""):
            continue
        if mode != only:
            raise Failure(f"{where}.{key} is only valid with execution_mode {only}.")
        value = side[key]
        out["extra"][field] = provider_data(value, f"{where}.{key}") if key.endswith("_data") else str(value)
    return out


def build_payload(side, scenario_ids, frequency, name, concurrency_limit):
    if side["mode"] in ("voice", "text"):
        payload = {"agent_id": side["agent_id"], "scenarios": list(scenario_ids)}
    else:
        payload = {"agent": side["agent_id"], "scenarios": [{"scenario": i} for i in scenario_ids]}
    payload.update(frequency=frequency, name=name, concurrency_limit=concurrency_limit, **side["extra"])
    return payload


class Launch:
    """One Cekura result started by the batch."""

    def __init__(self, group, leg, side, scenario_ids, frequency, slots, name):
        self.group = group
        self.leg = leg
        self.mode = side["mode"]
        self.endpoint = ENDPOINTS[side["mode"]]
        self.slots = slots
        self.name = name
        self.payload = build_payload(side, scenario_ids, frequency, name, slots)
        self.status = "queued"
        self.result_id = None
        self.result = None
        self.url = None
        self.error = ""
        self.poll_failures = 0

    @property
    def title(self):
        return f"{self.group} · {self.leg}" if self.leg else self.group

    @property
    def total(self):
        return int((self.result or {}).get("total_runs_count") or 0)

    @property
    def passed_runs(self):
        return int((self.result or {}).get("success_runs_count") or 0)

    @property
    def passed(self):
        return self.status == "completed" and self.total > 0 and self.passed_runs == self.total


class Unit:
    """Launches that start together: a single-agent group, or one set of legs."""

    def __init__(self, group, launches):
        self.group = group
        self.launches = launches
        self.slots = sum(launch.slots for launch in launches)


def plan(groups, cfg, concurrency):
    """Validate the batch and expand it into units, in start order."""
    default_frequency = positive_int(cfg.frequency, "frequency")
    units = []
    for index, group in enumerate(groups, 1):
        where = f"group {index}"
        if not isinstance(group, dict):
            raise Failure(f"{where} must be a mapping.")
        unknown = set(group) - GROUP_KEYS
        if unknown:
            raise Failure(f"{where} has unknown key(s) {sorted(unknown)}; allowed: {sorted(GROUP_KEYS)}.")
        name = str(group.get("name") or where)
        if group.get("name"):
            where = f"group {name!r}"
        frequency = positive_int(group.get("frequency", default_frequency), f"{where}.frequency")

        if "legs" not in group:
            side = build_side({k: group[k] for k in RUN_KEYS if k in group}, {}, where, cfg)
            slots = min(len(side["scenario_ids"]) * frequency, concurrency)
            units.append(Unit(name, [Launch(name, "", side, side["scenario_ids"], frequency, slots,
                                            f"{cfg.name} · {name}")]))
            continue

        if "scenario_ids" in group:
            raise Failure(f"{where}: put scenario_ids on each leg, not on the group.")
        raw_legs = group["legs"]
        if not isinstance(raw_legs, list) or len(raw_legs) < 2:
            raise Failure(f"{where}.legs must list at least 2 legs; for one agent, put agent_id and "
                          "scenario_ids on the group instead.")
        defaults = {k: group[k] for k in RUN_KEYS - {"scenario_ids"} if k in group}
        legs = []
        for n, raw in enumerate(raw_legs, 1):
            leg_name = str(raw.get("name") or f"leg {n}") if isinstance(raw, dict) else f"leg {n}"
            legs.append((leg_name, build_side(raw, defaults, f"{where}.legs[{n}]", cfg, LEG_KEYS)))
        names = [leg_name for leg_name, _ in legs]
        if len(set(names)) != len(names):
            raise Failure(f"{where}: leg names must be unique, got {names}.")
        counts = {leg_name: len(leg["scenario_ids"]) for leg_name, leg in legs}
        if len(set(counts.values())) != 1:
            raise Failure(
                f"{where}: legs have different scenario counts {counts}; legs are matched by position, "
                "so every leg needs the same number (repeat a scenario ID to reuse it).")
        if len(legs) > concurrency:
            raise Failure(f"{where} has {len(legs)} legs that run at the same time, which needs "
                          f"concurrency of at least {len(legs)}.")
        for i in range(next(iter(counts.values()))):
            for rep in range(1, frequency + 1):
                label = f"set {i + 1}" + (f" #{rep}" if frequency > 1 else "")
                units.append(Unit(name, [
                    Launch(name, f"{label} · {leg_name}", leg, [leg["scenario_ids"][i]], 1, 1,
                           f"{cfg.name} · {name} · {label} · {leg_name}")
                    for leg_name, leg in legs
                ]))
    return units


class Api:
    def __init__(self, cfg):
        self.cfg = cfg

    def call(self, method, path, payload=None, timeout=60):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"X-CEKURA-API-KEY": self.cfg.api_key}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.cfg.api_url + path, data, headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)


def http_error_body(e):
    try:
        return e.read().decode("utf-8", "replace")[:1000]
    except Exception:
        return ""


def parallel(fn, items, timeout):
    threads = [threading.Thread(target=fn, args=(item,), daemon=True) for item in items]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()[:300]


def run_reason(run):
    if run.get("status") != "completed":
        return run.get("error_message") or f"run ended {run.get('status')}"
    if run.get("success"):
        return ""
    names = []
    expected = run.get("expected_outcome")
    if isinstance(expected, dict) and isinstance(expected.get("score"), (int, float)) and expected["score"] < 100:
        names.append("expected outcome")
    for metric in (run.get("evaluation") or {}).get("metrics") or []:
        if (isinstance(metric, dict) and str(metric.get("type", "")).startswith("binary")
                and metric.get("score_normalized", metric.get("score")) in (0, False) and metric.get("name")):
            names.append(metric["name"])
    return "failed: " + ", ".join(names) if names else "failed its checks"


class Batch:
    def __init__(self, cfg, api, units, concurrency, sleep=time.sleep, clock=time.monotonic):
        self.cfg = cfg
        self.api = api
        self.units = units
        self.concurrency = concurrency
        self.timeout = positive_int(cfg.timeout, "timeout")
        self.sleep = sleep
        self.clock = clock
        self.pending = deque(units)
        self.active = []
        self.in_flight = 0
        self.started = clock()

    @property
    def launches(self):
        return [launch for unit in self.units for launch in unit.launches]

    # -- lifecycle -----------------------------------------------------------

    def run(self):
        deadline = self.started + self.timeout
        while self.pending or self.active:
            if self.clock() > deadline:
                self.stop(f"the {self.timeout}s timeout was reached", end_calls=True)
                raise Failure(f"Timed out after {self.timeout}s.")
            while self.pending and self.in_flight + self.pending[0].slots <= self.concurrency:
                self.start_unit(self.pending.popleft())
            self.poll_active()
            if self.pending or self.active:
                self.sleep(self.cfg.poll_interval)

    def start_unit(self, unit):
        for launch in unit.launches:
            if any(other.status in ("start failed", "not started") for other in unit.launches):
                launch.status = "not started"
                launch.error = "another leg in this set failed to start"
                continue
            self.start(launch)
        if any(launch.status == "start failed" for launch in unit.launches):
            for launch in unit.launches:
                if launch.result_id and launch in self.active:
                    launch.error = "ended: another leg in this set failed to start"
                    self.end_calls(launch)

    def start(self, launch):
        launch.status = "starting"
        try:
            started = self.api.call("POST", launch.endpoint, launch.payload, timeout=120)
        except urllib.error.HTTPError as e:
            launch.status, launch.error = "start failed", f"HTTP {e.code}: {http_error_body(e)}"
        except TRANSIENT as e:
            # Not retried: the POST may have created the result.
            launch.status = "start failed"
            launch.error = f"{type(e).__name__}: {e}; check Cekura for a result named {launch.name!r}"
        else:
            launch.result_id = started.get("id") if isinstance(started, dict) else None
            if launch.result_id:
                launch.status = "running"
                self.active.append(launch)
                self.in_flight += launch.slots
            else:
                launch.status = "start failed"
                launch.error = f"Cekura returned no result id: {json.dumps(started)[:300]}"
        if launch.result_id:
            print(f"▶ {launch.title}: result {launch.result_id} "
                  f"({launch.slots} call(s); {self.in_flight}/{self.concurrency} in flight)")
        else:
            print(f"✖ {launch.title}: could not start — {launch.error}")

    def poll_active(self):
        for launch in list(self.active):
            try:
                result = self.api.call("GET", f"/test_framework/v1/results/{launch.result_id}/", timeout=30)
            except (urllib.error.HTTPError,) + TRANSIENT as e:
                code = e.code if isinstance(e, urllib.error.HTTPError) else None
                launch.poll_failures += 1
                retryable = code is None or code in (408, 429) or code >= 500
                if not retryable or launch.poll_failures >= MAX_POLL_FAILURES:
                    self.stop(f"result {launch.result_id} could not be checked ({code or e})", end_calls=False)
                    raise Failure(f"Cannot check result {launch.result_id} ({code or e}).") from None
                print(f"  status check for result {launch.result_id} failed ({code or e}); "
                      f"retry {launch.poll_failures}/{MAX_POLL_FAILURES}")
                continue
            launch.poll_failures = 0
            launch.result = result
            if result.get("status") in TERMINAL:
                launch.status = result["status"]
                self.active.remove(launch)
                self.in_flight -= launch.slots
                print(f"■ {launch.title}: result {launch.result_id} {launch.status}, "
                      f"{launch.passed_runs}/{launch.total} passed")

    def end_calls(self, launch, timeout=5):
        try:
            self.api.call("POST", f"/test_framework/v1/results/{launch.result_id}/end_calls/", timeout=timeout)
            return True
        except Exception as e:
            print(f"Warning: could not end calls for result {launch.result_id} ({e})")
            return False

    def stop(self, reason, end_calls):
        """Stop early: skip queued groups and optionally end the running ones."""
        for unit in self.pending:
            for launch in unit.launches:
                launch.status, launch.error = "not started", f"not started: {reason}"
        self.pending.clear()
        for launch in self.active:
            launch.status = "stopped"
            launch.error = f"stopped: {reason}" + ("" if end_calls else "; its calls were left running")
        if end_calls and self.active:
            print(f"Ending {len(self.active)} active result(s)...")
            parallel(self.end_calls, list(self.active), 6)

    def cancel(self, signame):
        """Workflow cancelled: report what is known first, then end active calls."""
        reason = f"workflow cancelled ({signame})"
        for launch in self.launches:
            if launch.status == "starting":
                launch.status = "stopped"
                launch.error = f"cancelled while starting; check Cekura for a result named {launch.name!r}"
        active = list(self.active)
        for unit in self.pending:
            for launch in unit.launches:
                launch.status, launch.error = "not started", f"not started: {reason}"
        self.pending.clear()
        for launch in active:
            launch.status, launch.error = "stopped", f"stopped: {reason}"
        return active

    # -- reporting -----------------------------------------------------------

    def publish_links(self, timeout=15):
        expire_at = (datetime.datetime.now(datetime.timezone.utc)
                     + datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def publish(launch):
            try:
                out = self.api.call("POST",
                                    f"/test_framework/v1/results/{launch.result_id}/create_shareable_link_token/",
                                    {"expire_at": expire_at}, timeout=timeout)
                launch.url = out.get("shareable_link") or None
            except Exception as e:
                print(f"Warning: no shareable link for result {launch.result_id} ({e})")

        parallel(publish, [launch for launch in self.launches if launch.result_id], timeout + 2)

    def groups(self):
        order = []
        for launch in self.launches:
            if launch.group not in order:
                order.append(launch.group)
        return [(g, [launch for launch in self.launches if launch.group == g]) for g in order]

    def summary(self, headline=None):
        launches = self.launches
        total = sum(launch.total for launch in launches)
        passed = sum(launch.passed_runs for launch in launches)
        groups = self.groups()
        groups_passed = sum(all(launch.passed for launch in ls) for _, ls in groups)
        ok = groups_passed == len(groups)
        elapsed = int(self.clock() - self.started)
        lines = [
            "## Cekura batch results", "",
            headline or ("✅ All groups passed" if ok else "❌ Batch did not pass"), "",
            f"- Groups passed: {groups_passed}/{len(groups)}",
            f"- Runs passed: {passed}/{total}",
            f"- Concurrency: {self.concurrency} call(s)",
            f"- Duration: {elapsed // 60}m {elapsed % 60}s", "",
            "| Group | Leg | Result | Status | Passed |", "|---|---|---|---|---|",
        ]
        for group, ls in groups:
            for launch in ls:
                rid = launch.result_id or "—"
                ref = f"[{rid}]({launch.url})" if launch.url else str(rid)
                mark = "✅" if launch.passed else "❌"
                lines.append(f"| {cell(group)} | {cell(launch.leg or "—")} | {ref} | {mark} {cell(launch.status)} | "
                             f"{launch.passed_runs}/{launch.total} |")
        problems = []
        for launch in launches:
            if launch.error:
                problems.append(f"| {cell(launch.group)} | {cell(launch.leg or "—")} | — | — | {cell(launch.error)} |")
            runs = (launch.result or {}).get("runs") or {}
            runs = list(runs.values()) if isinstance(runs, dict) else list(runs)
            names = {s.get("id"): s.get("name") for s in (launch.result or {}).get("scenarios") or []
                     if isinstance(s, dict)}
            for r in runs:
                if not isinstance(r, dict) or (r.get("status") == "completed" and r.get("success")):
                    continue
                if r.get("status") not in TERMINAL and launch.status not in TERMINAL:
                    continue
                scenario = r.get("scenario")
                label = (scenario.get("name") if isinstance(scenario, dict) else None) or r.get("scenario_name") \
                    or names.get(scenario) or f"scenario {scenario}"
                problems.append(f"| {cell(launch.group)} | {cell(launch.leg or "—")} | {r.get('id')} | {cell(label)} | "
                                f"{cell(run_reason(r))} |")
        if problems:
            lines += ["", "### Did not pass", "", "| Group | Leg | Run | Scenario | Why |",
                      "|---|---|---|---|---|", *problems]
        return ok, total, passed, "\n".join(lines) + "\n"


class Reporter:
    def __init__(self, cfg):
        self.cfg = cfg

    def output(self, key, value):
        if self.cfg.output_path:
            with open(self.cfg.output_path, "a") as f:
                f.write(f"{key}={value}\n")

    def summary(self, text):
        if self.cfg.summary_path:
            with open(self.cfg.summary_path, "a") as f:
                f.write(text)

    def finish(self, batch, headline=None):
        ok, total, passed, text = batch.summary(headline)
        self.summary(text)
        self.output("passed", str(ok).lower())
        self.output("total_runs", total)
        self.output("passed_runs", passed)
        self.output("result_ids", json.dumps([launch.result_id for launch in batch.launches if launch.result_id]))
        print(text)
        return ok


def describe(units, concurrency):
    lines = [f"Batch plan: {len(units)} unit(s), concurrency {concurrency} call(s)"]
    for unit in units:
        for launch in unit.launches:
            ids = ",".join(str(s["scenario"] if isinstance(s, dict) else s) for s in launch.payload["scenarios"])
            lines.append(f"  {launch.title}: agent "
                         f"{launch.payload.get('agent_id', launch.payload.get('agent'))}, {launch.mode}, "
                         f"scenarios [{ids}] x{launch.payload['frequency']}, {launch.slots} call slot(s)")
    return "\n".join(lines)


def main():
    cfg = Config(os.environ)
    reporter = Reporter(cfg)
    batch = None

    # GitHub cancels a step with SIGINT, then SIGTERM 7.5s later, then SIGKILL.
    def on_cancel(signum, _frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        name = signal.Signals(signum).name
        print(f"\nCancellation received ({name}); ending active Cekura calls...")
        if batch is not None:
            active = batch.cancel(name)
            reporter.finish(batch, "⚠️ Workflow cancelled before the batch finished")
            parallel(batch.end_calls, active, 5)
            reporter.summary(f"\nAsked Cekura to end {len(active)} active result(s).\n")
        sys.exit(130 if signum == signal.SIGINT else 143)

    signal.signal(signal.SIGINT, on_cancel)
    signal.signal(signal.SIGTERM, on_cancel)

    try:
        concurrency = positive_int(cfg.concurrency, "concurrency")
        units = plan(load_batch(cfg), cfg, concurrency)
        print(describe(units, concurrency))
        if cfg.dry_run:
            reporter.summary("## Cekura batch plan\n\n```\n" + describe(units, concurrency) + "\n```\n")
            return 0
        if not cfg.api_key:
            raise Failure("api_key is empty. Is the secret set, and is this a fork pull request?")
        batch = Batch(cfg, Api(cfg), units, concurrency)
        try:
            batch.run()
        except Failure as e:
            if cfg.share_links:
                batch.publish_links()
            reporter.finish(batch, f"❌ Batch stopped early: {e}")
            raise
        if cfg.share_links:
            batch.publish_links()
        if not reporter.finish(batch):
            raise Failure("Some groups did not pass.")
        return 0
    except Failure as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Leave the result ids behind rather than a bare traceback; the runs
        # keep going and stay visible in Cekura.
        if batch is not None:
            reporter.finish(batch, f"❌ Stopped watching the batch: unexpected {type(e).__name__}")
        print(f"Error: unexpected {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
