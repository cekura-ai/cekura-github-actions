"""run-suite/run_suite.py against a fake Cekura API on localhost."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "run-suite", "run_suite.py")

SPEC = {
    "version": "1",
    "scenarios": [
        {"key": "greet", "name": "Greets", "instructions": "Say hi", "expected_outcome": "Greets"},
    ],
}


def run_entry(rid, name, status="completed", success=True, **extra):
    return {"id": rid, "scenario": {"id": rid, "name": name}, "status": status,
            "success": success, **extra}


class FakeCekura:
    """Records requests and answers from a scripted list of result payloads."""

    def __init__(self, results=None, start_status=200, dry_run_body=None, dry_run_status=200):
        self.requests = []
        self.results = list(results or [])
        self.start_status = start_status
        self.dry_run_status = dry_run_status
        # Raw answers served to GET before the scripted results, e.g. a broken
        # body or a dropped connection.
        self.glitches = []
        self.dry_run_body = dry_run_body or {"dry_run": True, "valid": True,
                                             "plan": {"scenario_count": 1, "total_runs": 1}}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"null")
                fake.requests.append(("POST", self.path, body, self.headers.get("X-CEKURA-API-KEY")))
                if self.path.endswith("validate_scenarios_json/"):
                    return self._send(fake.dry_run_status, fake.dry_run_body)
                if self.path.endswith("run_scenarios_json/"):
                    if fake.start_status != 200:
                        return self._send(fake.start_status, {"spec": ["bad"]})
                    return self._send(200, {"id": 77, "runs": [{"id": 1}]})
                if self.path.endswith("create_shareable_link_token/"):
                    return self._send(200, {"shareable_link": "https://dash/share/result/77/t"})
                if self.path.endswith("end_calls/"):
                    return self._send(200, {})
                self._send(404, {})

            def do_GET(self):
                fake.requests.append(("GET", self.path, None, None))
                if fake.glitches:
                    glitch = fake.glitches.pop(0)
                    if glitch == "drop":
                        self.close_connection = True
                        self.connection.shutdown(2)
                        return
                    data = glitch.encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if fake.results:
                    body = fake.results.pop(0) if len(fake.results) > 1 else fake.results[0]
                    return self._send(200, body)
                self._send(200, {"status": "running"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self):
        return [p for _, p, _, _ in self.requests]


class RunSuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.spec_path = os.path.join(self.tmp.name, "cekura.tests.json")
        with open(self.spec_path, "w") as f:
            json.dump(SPEC, f)
        self.output = os.path.join(self.tmp.name, "output")
        self.summary = os.path.join(self.tmp.name, "summary")

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, fake, **overrides):
        env = {
            "PATH": os.environ["PATH"],
            "API_URL": fake.url, "API_KEY": "k", "AGENT_ID": "42", "SPEC": self.spec_path,
            "EXECUTION_MODE": "pipecat_v2",
            "PIPECAT_DATA": '{"pipecat_agent_name": "bot-pr-7"}',
            "DRY_RUN": "false", "TIMEOUT": "60", "NAME": "pr-7",
            "GITHUB_OUTPUT": self.output, "GITHUB_STEP_SUMMARY": self.summary,
            "RUNNER_TEMP": self.tmp.name,
        }
        env.update(overrides)
        return env

    def run_script(self, fake, **overrides):
        return subprocess.run([sys.executable, SCRIPT], env=self.env(fake, **overrides),
                              capture_output=True, text=True, timeout=60)

    def outputs(self):
        with open(self.output) as f:
            return dict(line.split("=", 1) for line in f.read().splitlines())

    def summary_text(self):
        with open(self.summary) as f:
            return f.read()

    def start_body(self, fake):
        return next(b for m, p, b, _ in fake.requests if p.endswith("run_scenarios_json/"))

    def test_all_runs_passing_passes_and_sends_the_preview_override(self):
        fake = FakeCekura([{"status": "completed", "total_runs_count": 1, "success_runs_count": 1,
                            "runs": {"1": run_entry(1, "Greets")}}])
        self.addCleanup(fake.close)
        proc = self.run_script(fake)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        body = self.start_body(fake)
        self.assertEqual(body["agent_id"], 42)
        self.assertEqual(body["channel"], "pipecat_v2")
        self.assertEqual(body["pipecat_data"], {"pipecat_agent_name": "bot-pr-7"})
        self.assertEqual(body["spec"], SPEC)
        self.assertEqual(body["name"], "pr-7")
        out = self.outputs()
        self.assertEqual(out["result_id"], "77")
        self.assertEqual(out["passed"], "true")
        self.assertEqual(out["result_url"], "https://dash/share/result/77/t")
        self.assertIn("| Greets | ✅ pass |", self.summary_text())
        self.assertTrue(os.path.exists(out["summary_file"]))

    def test_completed_with_a_failed_run_fails_and_names_it(self):
        fake = FakeCekura([{"status": "completed", "total_runs_count": 2, "success_runs_count": 1,
                            "runs": {"1": run_entry(1, "Greets"),
                                     "2": run_entry(2, "Hangs up", success=False,
                                                    expected_outcome={"score": 0})}}])
        self.addCleanup(fake.close)
        proc = self.run_script(fake)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("1 of 2 run(s) did not pass", proc.stderr)
        self.assertEqual(self.outputs()["passed"], "false")
        self.assertIn("| Hangs up | ❌ fail | failed: expected outcome |", self.summary_text())

    def test_errored_run_is_not_counted_as_passed(self):
        fake = FakeCekura([{"status": "failed", "total_runs_count": 1, "success_runs_count": 0,
                            "runs": {"1": run_entry(1, "Greets", status="failed", success=None,
                                                    error_message="Failed to create Pipecat session")}}])
        self.addCleanup(fake.close)
        proc = self.run_script(fake)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Failed to create Pipecat session", self.summary_text())

    def test_dry_run_validates_without_starting_calls(self):
        fake = FakeCekura()
        self.addCleanup(fake.close)
        proc = self.run_script(fake, DRY_RUN="true")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # validate_scenarios_json: a dry run of run_scenarios_json would also
        # demand the balance for the calls it does not place.
        self.assertEqual(fake.paths(), ["/test_framework/v1/scenarios/validate_scenarios_json/"])
        self.assertEqual(self.outputs()["valid"], "true")

    def test_dry_run_rejection_fails_with_the_api_error(self):
        fake = FakeCekura(dry_run_body={"valid": False, "plan": {}})
        self.addCleanup(fake.close)
        proc = self.run_script(fake, DRY_RUN="true")
        self.assertEqual(proc.returncode, 1)

    def test_dry_run_rejection_logs_the_field_errors(self):
        fake = FakeCekura(dry_run_status=400, dry_run_body={"scenarios[0].metrics[0]": ["not enabled"]})
        self.addCleanup(fake.close)
        proc = self.run_script(fake, DRY_RUN="true")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not enabled", proc.stderr)

    def test_polling_rides_out_a_broken_body_and_a_dropped_connection(self):
        fake = FakeCekura([{"status": "completed", "total_runs_count": 1, "success_runs_count": 1,
                            "runs": {"1": run_entry(1, "Greets")}}])
        fake.glitches = ["<html>maintenance</html>", "drop"]
        self.addCleanup(fake.close)
        env = self.env(fake)
        proc = subprocess.run([sys.executable, "-c", (
            "import runpy, sys; sys.argv=['run_suite.py'];"
            "import importlib.util as u; s=u.spec_from_file_location('rs', %r); m=u.module_from_spec(s);"
            "s.loader.exec_module(m); m.POLL_RETRY_INTERVAL=0; sys.exit(m.main())") % SCRIPT],
            env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.outputs()["passed"], "true")
        self.assertIn("retry 2/", proc.stdout)

    def test_share_link_can_be_turned_off(self):
        fake = FakeCekura([{"status": "completed", "total_runs_count": 1, "success_runs_count": 1,
                            "runs": {"1": run_entry(1, "Greets")}}])
        self.addCleanup(fake.close)
        proc = self.run_script(fake, SHARE_LINK="false")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("create_shareable_link_token", " ".join(fake.paths()))
        self.assertNotIn("result_url", self.outputs())

    def test_provider_data_on_the_wrong_channel_is_refused_before_any_request(self):
        fake = FakeCekura()
        self.addCleanup(fake.close)
        proc = self.run_script(fake, EXECUTION_MODE="livekit_v2")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("pipecat_data is only valid with execution_mode: pipecat_v2", proc.stderr)
        self.assertEqual(fake.requests, [])

    def test_start_rejection_surfaces_the_body(self):
        fake = FakeCekura(start_status=400)
        self.addCleanup(fake.close)
        proc = self.run_script(fake)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("HTTP 400", proc.stderr)
        self.assertIn('"bad"', proc.stderr)

    def test_runs_outside_github_actions(self):
        """GitLab and local shells run the same script with no GITHUB_* variables."""
        fake = FakeCekura([{"status": "completed", "total_runs_count": 1, "success_runs_count": 1,
                            "runs": {"1": run_entry(1, "Greets")}}])
        self.addCleanup(fake.close)
        env = self.env(fake)
        for key in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
            env.pop(key)
        proc = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1/1 run(s) passed", proc.stdout)
        with open(os.path.join(self.tmp.name, "cekura-summary.md")) as f:
            self.assertIn("| Greets | ✅ pass |", f.read())

    def test_cancellation_ends_the_active_calls(self):
        fake = FakeCekura([{"status": "running"}])
        self.addCleanup(fake.close)
        proc = subprocess.Popen([sys.executable, SCRIPT], env=self.env(fake),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 20
        while time.time() < deadline and not any(p.startswith("/test_framework/v1/results/77/")
                                                  for p in fake.paths()):
            time.sleep(0.1)
        proc.send_signal(signal.SIGINT)
        proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 130)
        self.assertIn("/test_framework/v1/results/77/end_calls/", fake.paths())
        self.assertIn("Workflow cancelled", self.summary_text())
        self.assertEqual(self.outputs()["result_id"], "77")


if __name__ == "__main__":
    unittest.main()
