import json
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import run_batch  # noqa: E402
from run_batch import Batch, Config, Failure, load_batch, plan  # noqa: E402


def config(**env):
    base = {"API_KEY": "key", "CONCURRENCY": "4", "NAME": "ci"}
    base.update(env)
    cfg = Config(base)
    cfg.poll_interval = 0
    return cfg


def plan_of(groups, concurrency=4, **env):
    cfg = config(BATCH=json.dumps(groups), **env)
    return plan(load_batch(cfg), cfg, concurrency)


class FakeApi:
    """Cekura stand-in: each result finishes after `polls_to_finish` status checks."""

    def __init__(self, polls_to_finish=2, outcome=None, fail_start=()):
        self.polls_to_finish = polls_to_finish
        self.outcome = outcome or (lambda payload: True)
        self.fail_start = fail_start
        self.results = {}
        self.started = []
        self.ended = []
        self.max_in_flight = 0

    def in_flight(self):
        return sum(r["payload"]["concurrency_limit"] for r in self.results.values() if r["status"] == "running")

    def call(self, method, path, payload=None, timeout=60):
        if method == "POST" and "/scenarios" in path:
            if payload["name"] in self.fail_start:
                raise urllib.error.HTTPError(path, 400, "bad", {}, None)
            rid = len(self.results) + 1
            self.results[rid] = {"payload": payload, "status": "running", "polls": 0}
            self.started.append(payload["name"])
            self.max_in_flight = max(self.max_in_flight, self.in_flight())
            return {"id": rid}
        rid = int(path.split("/")[4])
        r = self.results[rid]
        if path.endswith("/end_calls/"):
            self.ended.append(rid)
            r["status"] = "cancelled"
            return {}
        if path.endswith("/create_shareable_link_token/"):
            return {"shareable_link": f"https://share/{rid}"}
        if r["status"] == "running":
            r["polls"] += 1
            if r["polls"] >= self.polls_to_finish:
                r["status"] = "completed"
        n = len(r["payload"]["scenarios"]) * r["payload"]["frequency"]
        ok = self.outcome(r["payload"])
        done = r["status"] == "completed"
        return {
            "id": rid, "status": r["status"], "total_runs_count": n,
            "success_runs_count": n if done and ok else 0,
            "scenarios": [{"id": 7, "name": "Greeting"}],
            "runs": {str(rid): {"id": rid, "scenario": 7, "status": "completed" if done else "running",
                                "success": ok, "error_message": None}},
        }


class PlanTests(unittest.TestCase):
    def test_single_agent_group_is_one_result_capped_at_concurrency(self):
        units = plan_of([{"name": "inbound", "agent_id": 5, "scenario_ids": "1, 2,3", "frequency": 2}])
        self.assertEqual(len(units), 1)
        launch = units[0].launches[0]
        self.assertEqual(launch.payload, {"agent_id": 5, "scenarios": [1, 2, 3], "frequency": 2,
                                          "name": "ci · inbound", "concurrency_limit": 4})
        self.assertEqual(units[0].slots, 4)

    def test_legs_expand_by_position_and_frequency(self):
        units = plan_of([{"name": "transfer", "frequency": 2, "legs": [
            {"name": "caller", "agent_id": 1, "scenario_ids": [10, 10]},
            {"name": "target", "agent_id": 2, "scenario_ids": "20,21"}]}])
        self.assertEqual(len(units), 4)
        self.assertTrue(all(u.slots == 2 for u in units))
        sets = [[(l.payload["agent_id"], l.payload["scenarios"]) for l in u.launches] for u in units]
        self.assertEqual(sets, [[(1, [10]), (2, [20])]] * 2 + [[(1, [10]), (2, [21])]] * 2)
        self.assertEqual(units[1].launches[1].name, "ci · transfer · set 1 #2 · target")

    def test_three_legs_reserve_three_slots_and_default_names(self):
        units = plan_of([{"name": "conference", "agent_id": 1,
                          "legs": [{"scenario_ids": "1"}, {"scenario_ids": "2"}, {"scenario_ids": "3"}]}])
        self.assertEqual(units[0].slots, 3)
        self.assertEqual([l.leg for l in units[0].launches], ["set 1 · leg 1", "set 1 · leg 2", "set 1 · leg 3"])

    def test_group_level_agent_and_mode_are_leg_defaults(self):
        units = plan_of([{"agent_id": 9, "execution_mode": "pipecat_v2",
                          "pipecat_data": '{"pipecat_agent_name": "bot"}',
                          "legs": [{"scenario_ids": "1"}, {"scenario_ids": "2", "agent_id": 8}]}])
        first, second = (l.payload for l in units[0].launches)
        self.assertEqual(first["agent"], 9)
        self.assertEqual(second["agent"], 8)
        self.assertEqual(first["scenarios"], [{"scenario": 1}])
        self.assertEqual(first["pipecat_data"], {"pipecat_agent_name": "bot"})

    def test_rejects_bad_batches(self):
        cases = {
            "unknown key": [{"legs": [{"agetnt_id": 1, "scenario_ids": "1"},
                                      {"agent_id": 1, "scenario_ids": "2"}]}],
            "same number": [{"legs": [{"agent_id": 1, "scenario_ids": "1,1"},
                                      {"agent_id": 1, "scenario_ids": "2"}]}],
            "at least 2 legs": [{"legs": [{"agent_id": 1, "scenario_ids": "1"}]}],
            "unique": [{"agent_id": 1, "legs": [{"name": "a", "scenario_ids": "1"},
                                                {"name": "a", "scenario_ids": "2"}]}],
            "only valid with execution_mode voice": [{"agent_id": 1, "scenario_ids": "1", "execution_mode": "text",
                                                      "phone_number": "+1"}],
            "positive integer": [{"agent_id": "x", "scenario_ids": "1"}],
            "not on the group": [{"scenario_ids": "1", "legs": [{"agent_id": 1, "scenario_ids": "1"},
                                                                {"agent_id": 1, "scenario_ids": "2"}]}],
            "unknown key.*member": [{"member": {"agent_id": 1, "scenario_ids": "1"}}],
        }
        for message, groups in cases.items():
            with self.subTest(message):
                with self.assertRaisesRegex(Failure, message):
                    plan_of(groups)

    def test_legs_need_concurrency_for_every_leg(self):
        with self.assertRaisesRegex(Failure, "at least 2"):
            plan_of([{"agent_id": 1, "legs": [{"scenario_ids": "1"}, {"scenario_ids": "2"}]}], concurrency=1)

    @unittest.skipIf(run_batch.yaml is None, "PyYAML not installed")
    def test_yaml_batch(self):
        cfg = config(BATCH="groups:\n  - name: a\n    agent_id: 1\n    scenario_ids: 1,2\n")
        units = plan(load_batch(cfg), cfg, 4)
        self.assertEqual(units[0].launches[0].payload["scenarios"], [1, 2])


class BatchTests(unittest.TestCase):
    groups = [
        {"name": "inbound", "agent_id": 5, "scenario_ids": "1,2,3"},
        {"name": "transfer", "legs": [{"name": "caller", "agent_id": 1, "scenario_ids": "10,11"},
                                      {"name": "target", "agent_id": 2, "scenario_ids": "20,21"}]},
        {"name": "big", "agent_id": 6, "scenario_ids": "1,2,3,4,5,6"},
    ]

    def run_batch(self, api, concurrency=4, timeout="3600", groups=None):
        cfg = config(TIMEOUT=timeout)
        units = plan(groups or self.groups, cfg, concurrency)
        batch = Batch(cfg, api, units, concurrency, sleep=lambda _: None)
        return batch

    def test_never_exceeds_concurrency_and_starts_legs_together(self):
        api = FakeApi()
        batch = self.run_batch(api)
        batch.run()
        self.assertLessEqual(api.max_in_flight, 4)
        self.assertEqual(len(api.started), 6)
        caller = api.started.index("ci · transfer · set 1 · caller")
        self.assertEqual(api.started[caller + 1], "ci · transfer · set 1 · target")
        ok, total, passed, text = batch.summary()
        self.assertTrue(ok)
        self.assertEqual((total, passed), (3 + 4 + 6, 13))

    def test_failed_group_fails_batch_and_is_explained(self):
        api = FakeApi(outcome=lambda p: p["name"] != "ci · transfer · set 2 · target")
        batch = self.run_batch(api)
        batch.run()
        ok, total, passed, text = batch.summary()
        self.assertFalse(ok)
        self.assertIn("Groups passed: 2/3", text)
        self.assertIn("| transfer | set 2 · target |", text)
        self.assertIn("Greeting | failed its checks", text)

    def test_other_legs_are_ended_when_one_leg_fails_to_start(self):
        api = FakeApi(fail_start={"ci · transfer · set 1 · target"})
        batch = self.run_batch(api)
        batch.run()
        caller = api.started.index("ci · transfer · set 1 · caller") + 1
        self.assertIn(caller, api.ended)
        ok, _, _, text = batch.summary()
        self.assertFalse(ok)
        self.assertIn("start failed", text)

    def test_timeout_ends_active_results_and_skips_queued_groups(self):
        api = FakeApi(polls_to_finish=10 ** 6)
        clock = iter(range(0, 10 ** 6, 100))
        cfg = config(TIMEOUT="250")
        units = plan(self.groups, cfg, 4)
        batch = Batch(cfg, api, units, 4, sleep=lambda _: None, clock=lambda: next(clock))
        with self.assertRaisesRegex(Failure, "Timed out"):
            batch.run()
        self.assertEqual(sorted(api.ended), [1])
        self.assertEqual({l.status for l in batch.launches[1:]}, {"not started"})

    def test_cancel_reports_and_returns_active_results(self):
        api = FakeApi(polls_to_finish=10 ** 6)
        batch = self.run_batch(api)
        batch.start_unit(batch.pending.popleft())
        active = batch.cancel("SIGINT")
        self.assertEqual([l.result_id for l in active], [1])
        ok, _, _, text = batch.summary("cancelled")
        self.assertFalse(ok)
        self.assertIn("not started: workflow cancelled (SIGINT)", text)


if __name__ == "__main__":
    unittest.main()
