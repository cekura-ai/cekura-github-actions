#!/usr/bin/env python3
"""Run a committed Cekura Tests-as-Code suite and gate the job on the result.

Invoked by run-suite/action.yml; every input arrives as an environment
variable. Standard library only, so it runs on any GitHub-hosted runner.

The suite file never names an agent or a deployment. Both come from the
request: ``agent_id`` picks the Cekura agent, and ``pipecat_data`` /
``livekit_data`` point this one run at a preview deployment.
"""

import datetime
import http.client
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CHANNELS = ("voice", "text", "elevenlabs", "pipecat_v2", "livekit_v2")
# Backend TERMINAL_RESULT_STATUSES.
TERMINAL = {"completed", "failed", "timeout", "cancelled"}
POLL_INTERVAL = 30
POLL_RETRY_INTERVAL = 15
# ~90s of consecutive failures — enough to ride out a Cekura deploy — before
# giving up on a result that may still be running.
MAX_POLL_ATTEMPTS = 7
# Everything a dropped connection, a reset, a truncated body or a non-JSON
# answer (a proxy's maintenance page) can raise; HTTPError is handled first.
TRANSIENT = (urllib.error.URLError, OSError, http.client.HTTPException, ValueError)


class Config:
    def __init__(self, env):
        self.api_url = (env.get("API_URL") or "https://api.cekura.ai").rstrip("/")
        self.api_key = env.get("API_KEY", "")
        self.agent_id = env.get("AGENT_ID", "").strip()
        self.spec_path = env.get("SPEC", "").strip()
        self.channel = (env.get("EXECUTION_MODE") or "voice").strip()
        self.pipecat_data = env.get("PIPECAT_DATA", "").strip()
        self.livekit_data = env.get("LIVEKIT_DATA", "").strip()
        self.name = env.get("NAME", "").strip()
        self.frequency = env.get("FREQUENCY", "").strip()
        self.concurrency_limit = env.get("CONCURRENCY_LIMIT", "").strip()
        self.dry_run = env.get("DRY_RUN", "false").strip().lower() == "true"
        self.share_link = env.get("SHARE_LINK", "true").strip().lower() != "false"
        self.timeout = int(env.get("TIMEOUT") or "3600")
        self.output_path = env.get("GITHUB_OUTPUT")
        self.summary_path = env.get("GITHUB_STEP_SUMMARY")
        self.summary_file = os.path.join(env.get("RUNNER_TEMP") or ".", "cekura-summary.md")


class Failure(Exception):
    """A configuration or API error that ends the step with a message."""


def build_payload(cfg):
    """Validate the inputs and return the request body for run_scenarios_json."""
    if not cfg.api_key:
        raise Failure("api_key is empty. Is the secret set, and is this a fork pull request?")
    if not cfg.agent_id.isdigit():
        raise Failure(f"agent_id must be a numeric Cekura agent ID, got {cfg.agent_id!r}.")
    if cfg.channel not in CHANNELS:
        raise Failure(f"execution_mode must be one of {', '.join(CHANNELS)}, got {cfg.channel!r}.")

    try:
        with open(cfg.spec_path) as f:
            spec = json.load(f)
    except OSError as e:
        raise Failure(f"Cannot read spec {cfg.spec_path!r}: {e}") from None
    except json.JSONDecodeError as e:
        raise Failure(f"Spec {cfg.spec_path!r} is not valid JSON: {e}") from None
    if not isinstance(spec, dict) or not spec.get("scenarios"):
        raise Failure(f"Spec {cfg.spec_path!r} has no scenarios.")

    payload = {"agent_id": int(cfg.agent_id), "spec": spec, "channel": cfg.channel}
    for field, raw, channel in (
        ("pipecat_data", cfg.pipecat_data, "pipecat_v2"),
        ("livekit_data", cfg.livekit_data, "livekit_v2"),
    ):
        if not raw:
            continue
        if cfg.channel != channel:
            raise Failure(f"{field} is only valid with execution_mode: {channel}.")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as e:
            raise Failure(f"{field} is not valid JSON: {e}") from None
        if not isinstance(value, dict):
            raise Failure(f"{field} must be a JSON object.")
        payload[field] = value

    if cfg.name:
        payload["name"] = cfg.name
    for field, raw in (("frequency", cfg.frequency), ("concurrency_limit", cfg.concurrency_limit)):
        if raw:
            if not raw.isdigit() or int(raw) < 1:
                raise Failure(f"{field} must be a positive integer, got {raw!r}.")
            payload[field] = int(raw)
    return payload


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
        body = e.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        return json.dumps(json.loads(body), indent=2)[:4000]
    except ValueError:
        return body[:4000]


class Reporter:
    """Writes outputs, the job summary, and the summary file for a PR comment."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.lines = []

    def output(self, key, value):
        if self.cfg.output_path:
            with open(self.cfg.output_path, "a") as f:
                f.write(f"{key}={value}\n")

    def add(self, *lines):
        self.lines.extend(lines)

    def flush(self):
        text = "\n".join(self.lines) + "\n"
        if self.cfg.summary_path:
            with open(self.cfg.summary_path, "a") as f:
                f.write(text)
        with open(self.cfg.summary_file, "w") as f:
            f.write(text)
        self.output("summary_file", self.cfg.summary_file)
        self.lines = []


def run_label(run):
    scenario = run.get("scenario")
    if isinstance(scenario, dict):
        return scenario.get("name") or f"scenario {scenario.get('id')}"
    return f"scenario {scenario}" if scenario else f"run {run.get('id')}"


def failing_metrics(run):
    """Binary metrics that scored 0. Run.success is the verdict; this only explains it."""
    names = []
    expected = run.get("expected_outcome")
    if isinstance(expected, dict) and isinstance(expected.get("score"), (int, float)) \
            and expected["score"] < 100:
        names.append("expected outcome")
    for metric in (run.get("evaluation") or {}).get("metrics") or []:
        if (isinstance(metric, dict) and str(metric.get("type", "")).startswith("binary")
                and metric.get("score_normalized") == 0 and metric.get("name")):
            names.append(metric["name"])
    return names


def run_reason(run):
    if run.get("status") != "completed":
        return (run.get("error_message") or f"run ended {run.get('status')}").strip()
    if run.get("success"):
        return ""
    names = failing_metrics(run)
    return "failed: " + ", ".join(names) if names else "failed its checks"


def dry_run(cfg, api, reporter, payload):
    # validate_scenarios_json runs the same checks as a dry run of
    # run_scenarios_json, except the balance check: validating costs nothing,
    # so an organization low on credit can still check its suite.
    try:
        out = api.call("POST", "/test_framework/v1/scenarios/validate_scenarios_json/", payload)
    except urllib.error.HTTPError as e:
        body = http_error_body(e)
        reporter.add("## Cekura suite validation", "", f"❌ Rejected (HTTP {e.code})", "",
                     "```json", body, "```")
        reporter.flush()
        raise Failure(f"Cekura rejected the suite (HTTP {e.code}):\n{body}") from None
    except TRANSIENT as e:
        raise Failure(f"Cannot reach Cekura at {cfg.api_url}: {type(e).__name__}: {e}") from None

    plan = out.get("plan") or {}
    print(json.dumps(plan, indent=2))
    valid = out.get("valid") is True
    reporter.output("valid", str(valid).lower())
    reporter.add(
        "## Cekura suite validation", "",
        "✅ Valid — no calls placed" if valid else "❌ Not valid", "",
        f"- Channel: `{plan.get('channel', cfg.channel)}`",
        f"- Cases: {plan.get('scenario_count', '?')}, runs: {plan.get('total_runs', '?')}",
        f"- Estimated cost: {plan.get('estimated_cost', '?')}",
    )
    reporter.flush()
    if not valid:
        raise Failure("Cekura did not accept the suite as valid.")


class Run:
    """One live suite run: start, poll, gate. Ends active calls if cancelled."""

    def __init__(self, cfg, api, reporter):
        self.cfg = cfg
        self.api = api
        self.reporter = reporter
        self.result_id = None
        self.result_url = None
        self.finished = False

    def start(self, payload):
        try:
            started = self.api.call("POST", "/test_framework/v1/scenarios/run_scenarios_json/",
                                    payload, timeout=120)
        except urllib.error.HTTPError as e:
            raise Failure(f"Failed to start the suite (HTTP {e.code}):\n{http_error_body(e)}") from None
        except TRANSIENT as e:
            # Not retried: the POST may have created the run, and a second one
            # would place every call twice.
            raise Failure(f"Starting the suite failed ({type(e).__name__}: {e}); check Cekura "
                          "for a run with this name before re-running.") from None
        self.result_id = started.get("id") if isinstance(started, dict) else None
        if not self.result_id:
            raise Failure(f"Cekura returned no result id: {json.dumps(started)[:1000]}")
        # Set immediately, so later steps can report the result even if
        # polling fails or the runner stops.
        self.reporter.output("result_id", self.result_id)
        print(f"Result {self.result_id}: {len(started.get('runs') or [])} run(s) queued")

    def poll(self):
        deadline = time.time() + self.cfg.timeout
        failures = 0
        started = time.time()
        while True:
            if time.time() > deadline:
                self.stop_unfinished("❌ Timed out before the suite finished", end_calls=True)
                raise Failure(f"Timed out after {self.cfg.timeout}s waiting for result {self.result_id}.")
            try:
                result = self.api.call("GET", f"/test_framework/v1/results/{self.result_id}/", timeout=30)
            except (urllib.error.HTTPError,) + TRANSIENT as e:
                code = e.code if isinstance(e, urllib.error.HTTPError) else None
                retryable = code is None or code in (408, 429) or code >= 500
                failures += 1
                if retryable and failures < MAX_POLL_ATTEMPTS:
                    print(f"  status check failed ({code or e}); retry {failures}/{MAX_POLL_ATTEMPTS}")
                    time.sleep(POLL_RETRY_INTERVAL)
                    continue
                # Leave the runs going: they finish normally and stay visible.
                self.stop_unfinished("❌ Stopped watching before the suite finished", end_calls=False)
                raise Failure(f"Cannot check result {self.result_id} ({code or e}).") from None
            failures = 0
            status = result.get("status", "")
            print(f"  [{int(time.time() - started)}s] status: {status}")
            if status in TERMINAL:
                self.finished = True
                return result
            time.sleep(POLL_INTERVAL)

    def gate(self, result):
        """Pass only when the result completed and every run passed.

        A result is `completed` once any run completed, even if others failed
        their checks or errored, so the status alone is not a pass.
        """
        status = result.get("status")
        total = int(result.get("total_runs_count") or 0)
        passed = int(result.get("success_runs_count") or 0)
        ok = status == "completed" and total > 0 and passed == total

        self.reporter.output("passed", str(ok).lower())
        self.reporter.output("total_runs", total)
        self.reporter.output("success_runs", passed)
        if self.cfg.share_link:
            self.publish_link(15)

        runs = result.get("runs") or {}
        runs = list(runs.values()) if isinstance(runs, dict) else list(runs)
        runs.sort(key=lambda r: run_label(r))
        self.reporter.add(
            "## Cekura suite results", "",
            f"{'✅ All runs passed' if ok else '❌ Suite did not pass'} — "
            f"{passed}/{total} passed (result status `{status}`)", "",
        )
        if self.cfg.name:
            self.reporter.add(f"Run: `{self.cfg.name}`", "")
        if runs:
            self.reporter.add("| Case | Result | Why |", "|---|---|---|")
            for r in runs:
                mark = "✅ pass" if r.get("status") == "completed" and r.get("success") else "❌ " + (
                    "fail" if r.get("status") == "completed" else str(r.get("status")))
                reason = run_reason(r).replace("|", "\\|").replace("\n", " ")[:300]
                self.reporter.add(f"| {run_label(r)} | {mark} | {reason} |")
            self.reporter.add("")
        if self.result_url:
            self.reporter.add(f"[📊 Full results in Cekura]({self.result_url})")
        self.reporter.flush()

        for r in runs:
            if not (r.get("status") == "completed" and r.get("success")):
                print(f"NOT PASSED: {run_label(r)} — {run_reason(r)}")
        print(f"{passed}/{total} run(s) passed; result status {status}")
        if not ok:
            raise Failure(f"{total - passed} of {total} run(s) did not pass.")

    def publish_link(self, timeout):
        if not self.result_id or self.result_url:
            return
        expire_at = (datetime.datetime.now(datetime.timezone.utc)
                     + datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            out = self.api.call("POST",
                                f"/test_framework/v1/results/{self.result_id}/create_shareable_link_token/",
                                {"expire_at": expire_at}, timeout=timeout)
        except Exception as e:
            print(f"Warning: could not create a shareable results link ({e})")
            return
        self.result_url = out.get("shareable_link") or None
        if self.result_url:
            self.reporter.output("result_url", self.result_url)
            print(f"📊 Results: {self.result_url}")

    def end_calls(self):
        try:
            self.api.call("POST", f"/test_framework/v1/results/{self.result_id}/end_calls/", timeout=5)
            return "Asked Cekura to end the active calls."
        except Exception as e:
            return f"Could not end the active calls ({e}); end them from the dashboard."

    def stop_unfinished(self, headline, end_calls, link_timeout=15):
        if not self.result_id or self.finished:
            return
        self.finished = True
        # Write the result id first so it survives a kill.
        self.reporter.add("## Cekura suite results", "", headline, "", f"- Result ID: {self.result_id}")
        self.reporter.add("- " + (self.end_calls() if end_calls else
                                  "The runs were left going; open the results to see how they finish."))
        if self.cfg.share_link:
            self.publish_link(link_timeout)
        if self.result_url:
            self.reporter.add("", f"[📊 Full results in Cekura]({self.result_url})")
        self.reporter.flush()


def main():
    cfg = Config(os.environ)
    api = Api(cfg)
    reporter = Reporter(cfg)
    run = Run(cfg, api, reporter)

    # GitHub cancels a step with SIGINT, then SIGTERM 7.5s later, then
    # SIGKILL. end_calls (<=5s) plus the link (<=2s) fit in that window.
    def on_cancel(signum, _frame):
        # GitHub follows SIGINT with SIGTERM 7.5s later; let this handler finish
        # ending the calls instead of being re-entered and cut short.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print(f"\nCancellation received ({signal.Signals(signum).name}); ending active Cekura calls...")
        run.stop_unfinished("⚠️ Workflow cancelled before the suite finished", end_calls=True,
                            link_timeout=2)
        sys.exit(130 if signum == signal.SIGINT else 143)

    signal.signal(signal.SIGINT, on_cancel)
    signal.signal(signal.SIGTERM, on_cancel)

    try:
        payload = build_payload(cfg)
        target = payload.get("pipecat_data") or payload.get("livekit_data") or "agent's saved connection"
        print(f"Cekura suite {cfg.spec_path}: agent {cfg.agent_id}, channel {cfg.channel}, "
              f"target {json.dumps(target) if isinstance(target, dict) else target}")
        if cfg.dry_run:
            dry_run(cfg, api, reporter, payload)
            return 0
        run.start(payload)
        run.gate(run.poll())
        return 0
    except Failure as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Whatever went wrong, leave the result id and link behind rather than a
        # bare traceback; the runs keep going and stay visible in Cekura.
        run.stop_unfinished("❌ Stopped watching before the suite finished", end_calls=False)
        print(f"Error: unexpected {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
