"""pipecat/preview.py: naming, scaling, readiness and delete."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "pipecat", "preview.py")
spec = importlib.util.spec_from_file_location("preview", SCRIPT)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def agent(desired="d2", reconciled="d2", available=True, ready=True, replicas=1, health=None,
          revision="d2", phase="Ready", errors=None):
    return {"desiredDeploymentId": desired, "reconciledDeploymentId": reconciled,
            "available": available, "ready": ready, "errors": errors or [],
            "currentRevision": {"deploymentID": revision, "phase": phase, "readyReplicas": replicas,
                                "health": health or {}}}


class FakePipecat:
    def __init__(self, agents=None, delete_status=200):
        self.agents = list(agents or [])
        self.delete_status = delete_status
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.requests.append(("GET", self.path, self.headers.get("Authorization")))
                body = fake.agents.pop(0) if len(fake.agents) > 1 else fake.agents[0]
                self._send(200, body)

            def do_DELETE(self):
                fake.requests.append(("DELETE", self.path, self.headers.get("Authorization")))
                self._send(fake.delete_status, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = os.path.join(self.tmp.name, "out")

    def run_cmd(self, command, **env):
        full = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": self.output, **env}
        return subprocess.run([sys.executable, SCRIPT, command], env=full,
                              capture_output=True, text=True, timeout=60)

    def outputs(self):
        with open(self.output) as f:
            return dict(line.split("=", 1) for line in f.read().splitlines())

    def write_spec(self, scenarios, defaults=None):
        path = os.path.join(self.tmp.name, "cekura.tests.json")
        with open(path, "w") as f:
            json.dump({"version": "1", "defaults": defaults or {}, "scenarios": scenarios}, f)
        return path

    def test_name_is_always_pr_scoped(self):
        self.assertEqual(preview.preview_name("dental-bot", "42"), "dental-bot-pr-42")
        for base, pr in (("Dental_Bot", "42"), ("-bot", "42"), ("bot", ""), ("bot", "abc")):
            with self.assertRaises(preview.Failure):
                preview.preview_name(base, pr)
        with self.assertRaisesRegex(preview.Failure, "longer than 63"):
            preview.preview_name("b" * 60, "1234")
        # Pipecat Cloud caps serviceName at 54.
        self.assertEqual(len(preview.pipecat_name("b" * 47, "123")), 54)
        with self.assertRaisesRegex(preview.Failure, "longer than 54"):
            preview.pipecat_name("b" * 48, "123")

    def test_plan_warms_one_agent_per_suite_call(self):
        spec_path = self.write_spec([{"name": "a"}, {"name": "b", "frequency": 3}], {"frequency": 2})
        proc = self.run_cmd("plan", AGENT_NAME_BASE="bot", PR_NUMBER="7", SPEC=spec_path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.outputs(), {"agent_name": "bot-pr-7", "min_agents": "5", "max_agents": "5"})

    def test_plan_caps_at_fifty_and_honours_explicit_scaling(self):
        spec_path = self.write_spec([{"name": "a", "frequency": 80}])
        self.run_cmd("plan", AGENT_NAME_BASE="bot", PR_NUMBER="7", SPEC=spec_path)
        self.assertEqual(self.outputs()["max_agents"], "50")
        os.remove(self.output)
        self.run_cmd("plan", AGENT_NAME_BASE="bot", PR_NUMBER="7", SPEC=spec_path,
                     MIN_AGENTS="0", MAX_AGENTS="3")
        self.assertEqual(self.outputs()["min_agents"], "0")
        self.assertEqual(self.outputs()["max_agents"], "3")

    def test_old_revision_serving_is_not_ready(self):
        ok, why = preview.readiness(agent(desired="new", reconciled="old"), 1)
        self.assertFalse(ok)
        self.assertIn("operator", why)
        self.assertFalse(preview.readiness(agent(replicas=0), 1)[0])
        self.assertFalse(preview.readiness(agent(ready=False), 1)[0])
        self.assertTrue(preview.readiness(agent(), 1)[0])

    def test_ready_waits_for_every_warm_agent(self):
        self.assertFalse(preview.readiness(agent(replicas=3), 9)[0])
        self.assertTrue(preview.readiness(agent(replicas=9), 9)[0])
        # Scale to zero: Pipecat reports ready with no replicas.
        self.assertTrue(preview.readiness(agent(replicas=0), 0)[0])

    def test_crash_check_ignores_the_previous_revision(self):
        crashing = {"restartCount": 9, "headline": "ImportError"}
        self.assertIsNone(preview.crash_reason(
            agent(desired="new", reconciled="old", revision="old", ready=False, replicas=0, health=crashing), 1))
        self.assertIsNone(preview.crash_reason(
            agent(revision="old", ready=False, replicas=0, health=crashing), 1))
        self.assertIn("ImportError", preview.crash_reason(
            agent(ready=False, replicas=0, health=crashing), 1))
        # Restarts are summed over replicas: 9 across 5 warm agents is not a loop.
        self.assertIsNone(preview.crash_reason(agent(ready=False, replicas=0, health=crashing), 5))
        self.assertIsNone(preview.crash_reason(agent(replicas=2, health=crashing), 1))

    def test_deployment_errors_fail_at_once(self):
        fake = FakePipecat([agent(ready=False, errors=[{"code": "IMAGE_PULL", "message": "denied"}])])
        self.addCleanup(fake.close)
        proc = self.run_cmd("wait-ready", PIPECAT_API_URL=fake.url, PIPECAT_API_KEY="pk",
                            AGENT_NAME="bot-pr-7", WAIT_TIMEOUT="60", MIN_AGENTS="1")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("failed to deploy: IMAGE_PULL: denied", proc.stderr)

    def test_wait_ready_polls_until_the_new_revision_serves(self):
        fake = FakePipecat([agent(desired="new", reconciled="old"), agent(replicas=0), agent()])
        self.addCleanup(fake.close)
        preview_time_sleep = preview.time.sleep
        self.addCleanup(setattr, preview.time, "sleep", preview_time_sleep)
        preview.time.sleep = lambda _s: None
        env = {"PIPECAT_API_URL": fake.url, "PIPECAT_API_KEY": "pk", "AGENT_NAME": "bot-pr-7",
               "WAIT_TIMEOUT": "60"}
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.update(env)
        preview.wait_ready()
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual(fake.requests[0], ("GET", "/v1/agents/bot-pr-7", "Bearer pk"))

    def test_crash_loop_fails_fast_with_the_reason(self):
        fake = FakePipecat([agent(ready=False, replicas=0, health={"restartCount": 4, "headline": "ImportError"})])
        self.addCleanup(fake.close)
        proc = self.run_cmd("wait-ready", PIPECAT_API_URL=fake.url, PIPECAT_API_KEY="pk",
                            AGENT_NAME="bot-pr-7", WAIT_TIMEOUT="60")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("crash-looping: ImportError (4 restarts)", proc.stderr)

    def test_delete_targets_only_the_preview_and_tolerates_404(self):
        fake = FakePipecat(delete_status=404)
        self.addCleanup(fake.close)
        proc = self.run_cmd("delete", PIPECAT_API_URL=fake.url, PIPECAT_API_KEY="pk",
                            AGENT_NAME_BASE="bot", PR_NUMBER="7")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(fake.requests, [("DELETE", "/v1/agents/bot-pr-7", "Bearer pk")])
        self.assertEqual(self.outputs()["deleted"], "false")

    def test_delete_refuses_an_empty_key(self):
        proc = self.run_cmd("delete", PIPECAT_API_URL="http://127.0.0.1:9", PIPECAT_API_KEY="",
                            AGENT_NAME_BASE="bot", PR_NUMBER="7")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("fork pull request", proc.stderr)

    def test_delete_error_fails(self):
        fake = FakePipecat(delete_status=403)
        self.addCleanup(fake.close)
        proc = self.run_cmd("delete", PIPECAT_API_URL=fake.url, PIPECAT_API_KEY="pk",
                            AGENT_NAME_BASE="bot", PR_NUMBER="7")
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
