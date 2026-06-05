# Quickstart: Pipecat Cloud + Cekura CI/CD

Automated voice agent testing on every PR. Setup takes ~10 minutes.

## What you'll get

- Every PR automatically deploys a fresh copy of your agent to Pipecat Cloud
- Cekura's AI testing agents call your agent and run your scenarios
- Results posted as a PR comment, PR blocked if evals fail
- Staging agent deleted when the PR closes

---

## Prerequisites

- A [Pipecat Cloud](https://pipecat.daily.co) account
- A [Cekura](https://api.cekura.ai) account
- Your agent in a GitHub repo with a Dockerfile

---

## Step 1: Set up Pipecat Cloud (one-time)

### 1a. Create an image pull secret

Pipecat Cloud needs a credential to pull your Docker image from GitHub Container Registry (GHCR):

1. Go to Pipecat Cloud dashboard → **Secrets** → **Image Pull Secrets**
2. Create a new secret with:
   - Name: `my-agent-pull-secret` (remember this)
   - Registry: `ghcr.io`
   - Username: your GitHub username
   - Password: a [GitHub Personal Access Token](https://github.com/settings/tokens) with `read:packages` scope

### 1b. Create a secret set

Your agent needs environment variables (LLM API keys, STT keys, etc.) at runtime:

1. Go to Pipecat Cloud dashboard → **Secrets** → **Secret Sets**
2. Create a new secret set named `my-agent-secrets` (remember this)
3. Add all env vars your agent needs (e.g., `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, etc.)

---

## Step 2: Set up Cekura (one-time)

1. Go to [api.cekura.ai](https://api.cekura.ai) → **New Project**
2. Create an agent: **Agents** → **Add Agent** → Select **Pipecat** as connection type
3. Note your **Agent ID** (e.g., `42`)
4. Create scenarios: **Scenarios** → **Generate Scenarios** (or create manually)
5. Note your **Scenario IDs** (e.g., `1234,1235,1236`)
6. Get your **API key**: Settings → API Keys

---

## Step 3: Add GitHub secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `CEKURA_API_KEY` | Your Cekura API key |
| `PIPECAT_API_KEY` | Your Pipecat Cloud API key |

---

## Step 4: Add the workflow files

Create `.github/workflows/cekura-eval.yml`:

```yaml
name: Cekura Evals

on:
  pull_request:
    branches: [main]

jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/pipecat-eval.yml@v2
    with:
      agent_name: my-voice-agent                    # your agent slug
      pipecat_secret_set: my-agent-secrets          # from Step 1b
      pipecat_pull_secret: my-agent-pull-secret     # from Step 1a
      cekura_agent_id: "42"                          # from Step 2
      scenario_ids: "1234,1235,1236"                 # from Step 2
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
      PIPECAT_API_KEY: ${{ secrets.PIPECAT_API_KEY }}
```

Create `.github/workflows/cekura-cleanup.yml`:

```yaml
name: Cleanup PR agent

on:
  pull_request:
    types: [closed]

jobs:
  cleanup:
    uses: cekura-ai/cekura-github-actions/.github/workflows/pipecat-cleanup.yml@v2
    with:
      agent_name: my-voice-agent    # same value as above
    secrets:
      PIPECAT_API_KEY: ${{ secrets.PIPECAT_API_KEY }}
```

---

## Step 5: Enable branch protection (optional but recommended)

In your repo: **Settings → Branches → Add rule** for your main branch:
- Check **Require status checks to pass before merging**
- Add `eval / check` to required checks

PRs with failing evals will be blocked automatically.

---

## What happens on each PR

1. GitHub Actions builds your Docker image and pushes to GHCR as `my-voice-agent-pr-42`
2. The image is deployed to Pipecat Cloud as a temporary service
3. Cekura's testing agents call your deployed agent and run your scenarios
4. Results are posted as a PR comment (updates on each new push)
5. The workflow fails if any scenario fails (blocking merge)
6. When the PR closes, the temporary Pipecat Cloud service is deleted

---

## Optional: Add observability

For call transcripts, audio recordings, and traces in your Cekura dashboard, add these env vars to your Pipecat Cloud secret set:

```
CEKURA_MONITORING_API_KEY=<your-cekura-api-key>
CEKURA_MONITORING_AGENT_ID=<your-cekura-agent-id>
```

And in your agent code, initialize the Cekura tracer:
```python
from cekura import init_cekura_tracer
init_cekura_tracer()
```

---

## SIP transport (Twilio)

If your agent uses SIP instead of WebRTC, skip the Pipecat Cloud deploy step and pass your SIP endpoint:

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/pipecat-eval.yml@v2
    with:
      agent_name: my-sip-agent
      transport: sip
      agent_url: "sip:+12345678901@sip.twilio.com"   # your SIP URI
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

## WebSocket transport

For agents using WebSocket transport:

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/pipecat-eval.yml@v2
    with:
      agent_name: my-ws-agent
      transport: websocket
      agent_url: "wss://staging.my-agent.example.com"
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```
