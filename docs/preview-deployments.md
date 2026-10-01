# Test a pull request on a preview deployment

Add a label to a pull request, and the workflow deploys **that pull request's
bot** to your own Pipecat Cloud org or LiveKit project under a name of its own,
runs your committed `cekura.tests.json` against it, comments the result, and
removes it. Your production agent is never deployed over, dialled, or deleted.

Everything runs on your infrastructure with your keys. Cekura provides only the
simulated caller.

| Piece | What it does |
|---|---|
| `cekura-ai/cekura-github-actions/run-suite` | Runs a committed suite file through Tests as Code and fails the job unless every run passes |
| `cekura-ai/cekura-github-actions/pipecat/deploy-preview` | Deploys this checkout to Pipecat Cloud as `<base>-pr-<number>` and waits until that revision is serving |
| `cekura-ai/cekura-github-actions/pipecat/delete-preview` | Deletes `<base>-pr-<number>` (never `<base>`) |
| `cekura-ai/cekura-github-actions/livekit/start-worker` | Builds this checkout and runs the LiveKit worker inside the job, registered as `<base>-pr-<number>` |
| `cekura-ai/cekura-github-actions/livekit/stop-worker` | Prints the worker's logs and removes it |

The root action, `cekura-ai/cekura-github-actions`, is unchanged: it still runs
saved scenarios by ID or tag.

## How a run reaches the preview

The suite file never names an agent or a deployment. The request does:

- `agent_id` picks the Cekura agent, with its metrics and saved credentials.
- `pipecat_data.pipecat_agent_name` (Pipecat) or `livekit_data.agent_name`
  (LiveKit) points this one run at the preview.

Cekura starts the preview's sessions with the credentials saved on the Cekura
agent. So the preview must live where those credentials reach:

- **Pipecat:** the Pipecat key saved on the Cekura agent belongs to the same
  Pipecat Cloud org the preview deploys into.
- **LiveKit:** the LiveKit credentials saved on the Cekura agent are for the
  same LiveKit project the worker registers with.

If your previews live somewhere else — a separate staging org or project —
create a Cekura agent with that org's or project's credentials and use its ID.

## When it runs

On the label only. Every run places real calls, so a push does not re-run it:
remove and re-add the label to test a new commit. The comment names the commit
it tested.

A label-only workflow should not be a required status check: a pull request
nobody labelled would wait forever, and a push after a run leaves the new
commit without one.

Create the label once: `gh label create cekura-test`.

## Pipecat Cloud

You provide:

| Name | Kind | What it is |
|---|---|---|
| `PIPECAT_CLOUD_API_KEY` | secret | A **private** Pipecat Cloud key; deploys and deletes the preview |
| `CEKURA_API_KEY` | secret | Your Cekura API key |
| `CEKURA_AGENT_ID` | variable | Cekura agent whose saved Pipecat key is for the same org |
| a secret set | Pipecat Cloud | The bot's runtime secrets. A CI-only set keeps production keys out of previews |

```yaml
name: Cekura voice tests

on:
  pull_request:
    types: [labeled, closed]

permissions:
  contents: read
  pull-requests: write

env:
  AGENT_NAME_BASE: my-bot

jobs:
  preview:
    if: >-
      github.event.action == 'labeled' &&
      github.event.label.name == 'cekura-test' &&
      github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    timeout-minutes: 45
    concurrency:
      group: cekura-preview-${{ github.event.pull_request.number }}
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}

      - id: preview
        uses: cekura-ai/cekura-github-actions/pipecat/deploy-preview@v1.3.0
        with:
          api_key: ${{ secrets.PIPECAT_CLOUD_API_KEY }}
          agent_name_base: ${{ env.AGENT_NAME_BASE }}
          secret_set: my-bot-ci
          spec: cekura.tests.json

      - id: cekura
        uses: cekura-ai/cekura-github-actions/run-suite@v1.3.0
        with:
          api_key: ${{ secrets.CEKURA_API_KEY }}
          agent_id: ${{ vars.CEKURA_AGENT_ID }}
          spec: cekura.tests.json
          execution_mode: pipecat_v2
          pipecat_data: '{"pipecat_agent_name": "${{ steps.preview.outputs.agent_name }}"}'
          name: PR ${{ github.event.pull_request.number }} @ ${{ github.event.pull_request.head.sha }}

      - name: Comment the result on the pull request
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
          SUMMARY_FILE: ${{ steps.cekura.outputs.summary_file }}
        run: |
          {
            if [ -n "$SUMMARY_FILE" ] && [ -f "$SUMMARY_FILE" ]; then
              cat "$SUMMARY_FILE"
            else
              echo "❌ No result: the run stopped before the suite started — see the workflow run."
            fi
            echo
            echo "<sub>Tested commit ${{ github.event.pull_request.head.sha }}</sub>"
          } > comment.md
          gh pr comment ${{ github.event.pull_request.number }} --repo ${{ github.repository }} --body-file comment.md

      - if: always()
        uses: cekura-ai/cekura-github-actions/pipecat/delete-preview@v1.3.0
        with:
          api_key: ${{ secrets.PIPECAT_CLOUD_API_KEY }}
          agent_name_base: ${{ env.AGENT_NAME_BASE }}

  # Removes a preview a cancelled or crashed run left behind. Same group as
  # the preview job, so closing mid-run waits instead of deleting under it.
  delete-on-close:
    if: >-
      github.event.action == 'closed' &&
      github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    concurrency:
      group: cekura-preview-${{ github.event.pull_request.number }}
      cancel-in-progress: false
    steps:
      - uses: cekura-ai/cekura-github-actions/pipecat/delete-preview@v1.3.0
        with:
          api_key: ${{ secrets.PIPECAT_CLOUD_API_KEY }}
          agent_name_base: ${{ env.AGENT_NAME_BASE }}
```

`deploy-preview` builds the image in Pipecat Cloud from the checkout by default
(`cloud_build`, `build_context`, `dockerfile`). To deploy an image you built
yourself, pass `image` and `image_credentials` instead.

It warms one agent per call the suite places at once (from `spec`), up to 50,
and waits until all of them are up, so no call waits on a cold start. It then
waits `settle_seconds` more (default 180) before the suite dials, because a
revision that has only just come up can still turn its first sessions away;
set it to `0` to skip. Those
agents are billed by Pipecat Cloud for as long as the preview exists — minutes,
normally. Set `max_agents` (and `min_agents`) to keep a large suite within your
plan. Ready means the revision this deploy asked
for is reconciled and serving — not just that the agent exists, which an update
would satisfy while the old revision still answers. A revision that keeps
restarting fails the step with its crash reason.

## LiveKit

The worker runs inside the job. LiveKit workers connect out to the server, so
it registers with your project exactly as a deployed one would; there is no
deployment to clean up, and no LiveKit plan quota is used.

It is named through `LIVEKIT_AGENT_NAME_OVERRIDE`, which livekit-agents **1.6+**
applies over any name set in code, and `LIVEKIT_AGENT_NAME`. The action reads
the worker's own registration log line and stops it unless it registered as
exactly `<base>-pr-<number>`. A worker with no name would be dispatched to
every new room in the project, and one with production's name would join
production's pool; neither gets to take a call. A worker whose registration
line does not show its name is stopped too, unless you set
`allow_unverified_agent_name` (livekit-agents older than 1.6 that read
`agent_name` from `LIVEKIT_AGENT_NAME` themselves).

The reverse matters as well: **if production registers with no agent name**
(automatic dispatch), it joins every new room in its project — including the
rooms Cekura creates for the preview. Use a LiveKit project for CI that
production does not run in, or give production an explicit name.

You provide:

| Name | Kind | What it is |
|---|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | secrets | The project the worker registers with. A CI-only project is recommended |
| provider keys | secrets | Passed to the worker through `env` |
| `CEKURA_API_KEY` | secret | Your Cekura API key |
| `CEKURA_AGENT_ID` | variable | Cekura agent whose saved LiveKit credentials are for the same project |

```yaml
name: Cekura voice tests

on:
  pull_request:
    types: [labeled]

permissions:
  contents: read
  pull-requests: write

jobs:
  preview:
    if: >-
      github.event.label.name == 'cekura-test' &&
      github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    timeout-minutes: 45
    # Two overlapping runs would register two workers under one name.
    concurrency:
      group: cekura-preview-${{ github.event.pull_request.number }}
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}

      - id: worker
        uses: cekura-ai/cekura-github-actions/livekit/start-worker@v1.3.0
        with:
          livekit_url: ${{ secrets.LIVEKIT_URL }}
          livekit_api_key: ${{ secrets.LIVEKIT_API_KEY }}
          livekit_api_secret: ${{ secrets.LIVEKIT_API_SECRET }}
          agent_name_base: my-agent
          env: |
            DEEPGRAM_API_KEY=${{ secrets.DEEPGRAM_API_KEY }}
            OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}

      - id: cekura
        uses: cekura-ai/cekura-github-actions/run-suite@v1.3.0
        with:
          api_key: ${{ secrets.CEKURA_API_KEY }}
          agent_id: ${{ vars.CEKURA_AGENT_ID }}
          spec: cekura.tests.json
          execution_mode: livekit_v2
          livekit_data: '{"agent_name": "${{ steps.worker.outputs.agent_name }}"}'
          # One runner serves every call.
          concurrency_limit: 3

      - name: Comment the result on the pull request
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
          SUMMARY_FILE: ${{ steps.cekura.outputs.summary_file }}
        run: |
          {
            if [ -n "$SUMMARY_FILE" ] && [ -f "$SUMMARY_FILE" ]; then
              cat "$SUMMARY_FILE"
            else
              echo "❌ No result: the run stopped before the suite started — see the workflow run."
            fi
            echo
            echo "<sub>Tested commit ${{ github.event.pull_request.head.sha }}</sub>"
          } > comment.md
          gh pr comment ${{ github.event.pull_request.number }} --repo ${{ github.repository }} --body-file comment.md

      - if: always()
        uses: cekura-ai/cekura-github-actions/livekit/stop-worker@v1.3.0
```

The image's `CMD` should start the worker in production mode
(`python agent.py start`); override it with `command`. Bake model files into
the image (`RUN python -m livekit.agents download-files`) so a worker never
downloads them mid-call. One runner hosts every call, so keep
`concurrency_limit` within what it can serve.

## run-suite inputs

| Input | Description | Default |
|---|---|---|
| `api_key` | Cekura API key | required |
| `agent_id` | Cekura agent ID | required |
| `spec` | Suite file | `cekura.tests.json` |
| `execution_mode` | `voice`, `text`, `elevenlabs`, `pipecat_v2` or `livekit_v2` | `voice` |
| `pipecat_data` | JSON: `pipecat_agent_name`, `config`, `room_properties` | — |
| `livekit_data` | JSON: `agent_name`, `url`, `config` | — |
| `dry_run` | Validate and price only (`validate_scenarios_json`); no calls, no credit | `false` |
| `name` | Name for the run in Cekura | — |
| `frequency` | Multiply every case's frequency | — |
| `concurrency_limit` | Maximum calls in flight | — |
| `share_link` | Create a 7-day shareable results link | `true` |
| `api_url` | Cekura API URL | `https://api.cekura.ai` |
| `timeout` | Seconds to wait for the suite | `3600` |

`share_link` (default `true`) creates `result_url`, a link anyone can open for 7
days — transcripts and recordings included. On a public repository, set it to
`false`: the pull request comment would publish it.

Outputs: `result_id`, `result_url` (shareable, 7 days), `passed`, `total_runs`,
`success_runs`, `valid` (dry runs), and `summary_file` — the per-case table as
Markdown, for a pull request comment.

It passes only when the result is `completed` and every run passed: a result is
`completed` once any run completed, even if others failed or errored. If the
job is cancelled or times out mid-suite, it asks Cekura to end the calls still
in progress.
