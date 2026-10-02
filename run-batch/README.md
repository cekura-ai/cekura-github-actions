# Cekura Batch Run

Run many agent/scenario groups from one step, with one `concurrency` limit for the whole batch. A group can also have several legs that must run at the same time, each as its own Cekura result, such as the caller and the transfer target of a warm transfer, or the parties of a 3-way call. You no longer need GitHub matrices or separate jobs per batch to stay under your Cekura concurrency.

```yaml
- uses: cekura-ai/cekura-github-actions/run-batch@v1.2.3
  with:
    api_key: ${{ secrets.CEKURA_API_KEY }}
    concurrency: ${{ inputs.concurrency || 10 }}
    frequency: ${{ inputs.frequency || 1 }}
    batch: |
      - name: inbound-smoke
        agent_id: 123
        scenario_ids: 1001,1002,1003

      - name: warm-transfer
        legs:
          - name: caller
            agent_id: 456
            scenario_ids: 2001,2001
          - name: transfer-target
            agent_id: 123
            scenario_ids: 3001,3002
```

`batch` accepts JSON or YAML. YAML needs PyYAML in the runner's `python3`. If it is missing, add `pip install pyyaml` in an earlier step, or write the batch as JSON. You can also put the batch in a file and pass `batch_file: .github/cekura-batch.yml`.

## Groups

Each group is one of two kinds.

**Single agent.** Use `agent_id` and `scenario_ids` on the group. All of its scenarios run as **one** Cekura result. A group of N scenarios at frequency F needs N × F calls. The group reserves `min(N × F, concurrency)` call slots, and Cekura is told to run no more than that many at once (`concurrency_limit`).

**Legs (calls that run together).** Use `legs`, a list of two or more legs, each with its own `agent_id` and `scenario_ids`. The lists are matched by position: scenario *i* of every leg forms set *i*, and every leg needs the same number of scenarios. To reuse a scenario across sets, repeat its ID, as in `2001,2001` above.
- Each set starts one Cekura result per leg, together, each in its own context.
- A set reserves one call slot per leg, so a two-leg set reserves 2.
- `frequency` repeats each set; it does not set the frequency inside each result.
- A leg's optional `name` labels it in the job summary and the result names (default `leg 1`, `leg 2`, …). Names must be unique within the group.

Group keys:

| Key | Description |
|---|---|
| `name` | Label in the job summary and in the Cekura result names |
| `agent_id`, `scenario_ids` | Agent ID and scenario IDs, as a comma-separated string or a list |
| `legs` | Two or more legs that run at the same time. Each leg takes `name` plus the keys below, except `frequency` |
| `frequency` | Overrides the action's `frequency` for this group |
| `execution_mode` | `voice`, `text`, `livekit_v2` or `pipecat_v2`. Defaults to the action's `execution_mode` |
| `phone_number` (voice), `websocket_url` (text), `livekit_data` / `pipecat_data` | Same as the main action |

Keys set on a group with legs, such as `agent_id` and `execution_mode`, are defaults for every leg. Unknown keys are rejected, so a typo like `agetnt_id` fails the step before any call is placed.

## Scheduling

Groups start in the order they are listed. The next group starts only when its call slots fit in what is left of `concurrency`, so the calls in flight never exceed it. Slots are freed as each result finishes. Use `dry_run: true` to print the plan without placing any calls.

Keep `concurrency` at or below your organization's Cekura concurrency limit, minus any other runs (schedules, other workflows) that share it. Above that limit Cekura queues the extra results, so calls wait in the queue and the legs of a set may not start at the same time.

## Results and failure

- **Pass:** the step passes only when every result is `completed` and every run in it passed.
- **Job summary:** it has one row per result (group, call, linked result, status, passed/total), plus a table of the runs that did not pass and why.
- **Leg start failure:** if one leg of a set fails to start, the calls of the set's other legs are ended.
- **`timeout` reached:** the action ends the active results' calls, skips the groups that have not started, and fails.
- **Workflow cancelled or job `timeout-minutes` reached:** the action writes the summary, then asks Cekura to end every active result's calls.

## Inputs

| Input | Description | Required | Default |
|---|---|---|---|
| `api_key` | Cekura API key | Yes | - |
| `concurrency` | Maximum calls in flight across the batch. A set of legs counts as one call per leg | Yes | - |
| `batch` | Groups, as JSON or YAML | One of `batch` / `batch_file` | - |
| `batch_file` | Path to a JSON or YAML file with the groups | One of `batch` / `batch_file` | - |
| `frequency` | Default runs per scenario, or repeats per set of legs | No | `1` |
| `execution_mode` | Default execution mode | No | `voice` |
| `name` | Prefix for the Cekura result names | No | `GitHub run <run id>` |
| `timeout` | Timeout in seconds for the whole batch | No | `3600` |
| `share_links` | Link each result in the summary through a 7-day shareable link | No | `true` |
| `dry_run` | Validate and print the plan only | No | `false` |
| `api_url` | Cekura API URL | No | `https://api.cekura.ai` |

Outputs: `passed` (`true`/`false`), `total_runs`, `passed_runs`, and `result_ids` (a JSON list).
