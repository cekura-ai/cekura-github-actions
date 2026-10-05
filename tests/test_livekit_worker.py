"""livekit/worker.py against real containers (skipped without Docker)."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "livekit", "worker.py")
IMAGE = "busybox:1.36"


def docker_ok():
    if not shutil.which("docker"):
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return subprocess.run(["docker", "pull", "-q", IMAGE], capture_output=True).returncode == 0


@unittest.skipUnless(docker_ok(), "needs Docker")
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.container = f"cekura-test-{uuid.uuid4().hex[:8]}"
        self.addCleanup(subprocess.run, ["docker", "rm", "-f", self.container], capture_output=True)
        self.output = os.path.join(self.tmp.name, "out")

    def run_cmd(self, command, **env):
        full = {
            "PATH": os.environ["PATH"], "GITHUB_OUTPUT": self.output, "RUNNER_TEMP": self.tmp.name,
            "IMAGE": IMAGE, "CONTAINER": self.container, "AGENT_NAME_BASE": "bot", "PR_NUMBER": "7",
            "LIVEKIT_URL": "wss://ci.livekit.cloud", "LIVEKIT_API_KEY": "APIk",
            "LIVEKIT_API_SECRET": "s3cret", "READY_TIMEOUT": "30", **env,
        }
        return subprocess.run([sys.executable, SCRIPT, command], env=full,
                              capture_output=True, text=True, timeout=120)

    def test_worker_gets_the_pr_agent_name_and_credentials(self):
        proc = self.run_cmd(
            "start",
            COMMAND="sh -c 'env | sort; echo \"INFO livekit.agents registered worker {\\\"agent_name\\\": \\\"bot-pr-7\\\", \\\"id\\\": \\\"AW_1\\\"}\"; sleep 60'",
            WORKER_ENV="# provider keys\nOPENAI_API_KEY=sk-1\n\nDEEPGRAM_API_KEY=dg=2",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        logs = subprocess.run(["docker", "logs", self.container], capture_output=True, text=True).stdout
        self.assertIn("registered with LiveKit as bot-pr-7", proc.stdout)
        for line in ("LIVEKIT_AGENT_NAME_OVERRIDE=bot-pr-7", "LIVEKIT_AGENT_NAME=bot-pr-7",
                     "LIVEKIT_URL=wss://ci.livekit.cloud",
                     "LIVEKIT_API_SECRET=s3cret", "OPENAI_API_KEY=sk-1", "DEEPGRAM_API_KEY=dg=2"):
            self.assertIn(line, logs)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "cekura-livekit-worker.env")))

        stop = self.run_cmd("stop")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertIn("LiveKit worker logs", stop.stdout)
        inspect = subprocess.run(["docker", "inspect", self.container], capture_output=True)
        self.assertNotEqual(inspect.returncode, 0)

    def test_worker_that_exits_before_registering_fails_with_its_logs(self):
        proc = self.run_cmd("start", COMMAND="sh -c 'echo ImportError: no module named agents; exit 3'")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("exited (code 3)", proc.stderr)
        self.assertIn("ImportError", proc.stdout)

    def test_custom_agent_name_env_and_reserved_keys(self):
        proc = self.run_cmd("start", AGENT_NAME_ENV="AGENT_NAME",
                            COMMAND="sh -c 'echo name=$AGENT_NAME; echo \"registered worker {\\\"agent_name\\\": \\\"$AGENT_NAME\\\"}\"; sleep 60'")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("name=bot-pr-7",
                      subprocess.run(["docker", "logs", self.container], capture_output=True, text=True).stdout)
        bad = self.run_cmd("start", WORKER_ENV="LIVEKIT_URL=wss://other")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("livekit_* inputs", bad.stderr)

    def registers_as(self, agent_name):
        payload = '{\\"agent_name\\": \\"%s\\", \\"id\\": \\"AW_1\\"}' % agent_name
        return self.run_cmd("start", COMMAND=f"sh -c 'echo \"registered worker {payload}\"; sleep 60'")

    def assert_stopped(self):
        inspect = subprocess.run(["docker", "inspect", self.container], capture_output=True)
        self.assertNotEqual(inspect.returncode, 0, "the worker container should have been removed")

    def test_worker_registered_under_another_name_is_stopped(self):
        proc = self.registers_as("meridian-support")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("registered as 'meridian-support', not 'bot-pr-7'", proc.stderr)
        self.assert_stopped()

    def test_node_worker_is_checked_by_its_camel_case_name(self):
        # @livekit/agents logs pino JSON: "agentName" beside "agentNameIsEnv".
        good = self.run_cmd("start", COMMAND="sh -c 'echo \"{\\\"agentNameIsEnv\\\":true,\\\"agentName\\\":\\\"bot-pr-7\\\",\\\"msg\\\":\\\"registered worker\\\"}\"; sleep 60'")
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn("registered with LiveKit as bot-pr-7", good.stdout)
        bad = self.run_cmd("start", COMMAND="sh -c 'echo \"{\\\"agentNameIsEnv\\\":false,\\\"agentName\\\":\\\"support\\\",\\\"msg\\\":\\\"registered worker\\\"}\"; sleep 60'")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("registered as 'support'", bad.stderr)

    def test_worker_with_no_agent_name_is_stopped(self):
        proc = self.registers_as("")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("dispatch it to every new room", proc.stderr)
        self.assert_stopped()

    def test_worker_without_a_reported_name_is_stopped(self):
        proc = self.run_cmd("start", COMMAND="sh -c 'echo registered worker; sleep 60'")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not say which agent name", proc.stderr)
        self.assert_stopped()

    def test_unverified_name_can_be_allowed_explicitly(self):
        proc = self.run_cmd("start", COMMAND="sh -c 'echo registered worker; sleep 60'",
                            ALLOW_UNVERIFIED="true")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::", proc.stdout)

    def test_env_cannot_override_the_agent_name(self):
        proc = self.run_cmd("start", WORKER_ENV="LIVEKIT_AGENT_NAME=production")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("LIVEKIT_AGENT_NAME", proc.stderr)
        bad = self.run_cmd("start", AGENT_NAME_ENV="LIVEKIT_URL")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("agent_name_env", bad.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "cekura-livekit-worker.env")))

    def test_missing_livekit_secret_is_named(self):
        proc = self.run_cmd("start", LIVEKIT_API_SECRET="")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("livekit_api_secret is empty", proc.stderr)

    def test_stop_without_a_container_is_a_no_op(self):
        proc = self.run_cmd("stop")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nothing to stop", proc.stdout)


if __name__ == "__main__":
    unittest.main()
