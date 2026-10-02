# Cekura Batch Run

Run many agent/scenario groups from one step, with one `concurrency` limit for the whole batch. It also supports member/contact pairs for 3-way calls. You no longer need GitHub matrices or separate jobs per batch to stay under your Cekura concurrency.

```yaml
- uses: cekura-ai/cekura-github-actions/run-batch@v1.3.0
  with:
    api_key: ${{ secrets.CEKURA_API_KEY }}
    concurrency: ${{ inputs.concurrency || 10 }}
    frequency: ${{ inputs.frequency || 1 }}
    batch: |
      - name: inbound-smoke
        agent_id: 123
        scenario_ids: 1001,1002,1003

      - name: attendant-transfer
        member:
          agent_id: 456
          scenario_ids: 2001,2001
        contact:
          agent_id: 123
          scenario_ids: 3001,3002
```

`batch` accepts JSON or YAML. YAML needs PyYAML in the runner's `python3`. If it is missing, add `pip install pyyaml` in an earlier step, or write the batch as JSON. You can also put the batch in a file and pass `batch_file: .github/cekura-batch.yml`.

## Groups

Each group is one of two kinds.

**Single agent.** Use `agent_id` and `scenario_ids` on the group, or a group with only `member` or only `contact`. All of its scenarios run as **one** Cekura result. A group of N scenarios at frequency F needs N × F calls. The group reserves `min(N × F, concurrency)` call slots, and Cekura is told to run no more than that many at once (`concurrency_limit`).

**Member/contact pair (3-way calls).** Use both `member` and `contact`. The two lists are matched by position: member scenario *i* runs with contact scenario *i*. To reuse one member scenario against several contacts, repeat its ID, as in `2001,2001` above.
- Each pair starts its member result and its contact result together, each in its own context.
- A pair reserves 2 call slots.
- `frequency` repeats each pair; it does not set the frequency inside each result.

Group keys:

| Key | Description |
|---|---|
| `name` | Label in the job summary and in the Cekura result names |
| `agent_id`, `scenario_ids` | Agent ID and scenario IDs, as a comma-separated string or a list |
| `member`, `contact` | Sides of a pair. Each side takes the side keys below |
| `frequency` | Overrides the action's `frequency` for this group |
| `execution_mode` | `voice`, `text`, `livekit_v2` or `pipecat_v2`. Defaults to the action's `execution_mode` |
| `phone_number` (voice), `websocket_url` (text), `livekit_data` / `pipecat_data` | Same as the main action |

Keys set on a pair group, such as `agent_id` and `execution_mode`, are defaults for both sides. Unknown keys are rejected, so a typo like `agetnt_id` fails the step before any call is placed.

## Scheduling

Groups start in the order they are listed. The next group starts only when its call slots fit in what is left of `concurrency`, so the calls in flight never exceed it. Slots are freed as each result finishes. Use `dry_run: true` to print the plan without placing any calls.

## Results and failure

- **Pass:** the step passes only when every result is `completed` and every run in it passed.
- **Job summary:** it has one row per result (group, call, linked result, status, passed/total), plus a table of the runs that did not pass and why.
- **Pair start failure:** if one side of a pair fails to start, the other side's calls are ended.
- **`timeout` reached:** the action ends the active results' calls, skips the groups that have not started, and fails.
- **Workflow cancelled or job `timeout-minutes` reached:** the action writes the summary, then asks Cekura to end every active result's calls.

## Inputs

| Input | Description | Required | Default |
|---|---|---|---|
| `api_key` | Cekura API key | Yes | - |
| `concurrency` | Maximum calls in flight across the batch. A pair counts as 2 | Yes | - |
| `batch` | Groups, as JSON or YAML | One of `batch` / `batch_file` | - |
| `batch_file` | Path to a JSON or YAML file with the groups | One of `batch` / `batch_file` | - |
| `frequency` | Default runs per scenario, or repeats per pair | No | `1` |
| `execution_mode` | Default execution mode | No | `voice` |
| `name` | Prefix for the Cekura result names | No | `GitHub run <run id>` |
| `timeout` | Timeout in seconds for the whole batch | No | `3600` |
| `share_links` | Link each result in the summary through a 7-day shareable link | No | `true` |
| `dry_run` | Validate and print the plan only | No | `false` |
| `api_url` | Cekura API URL | No | `https://api.cekura.ai` |

Outputs: `passed` (`true`/`false`), `total_runs`, `passed_runs`, and `result_ids` (a JSON list).
