# Quickstart: LiveKit + Cekura CI/CD

Automated voice agent testing on every PR for LiveKit-based agents. Setup takes ~10 minutes.

## What you'll get

- Every PR runs Cekura's AI testing agents against your LiveKit staging deployment
- Results posted as a PR comment, PR blocked if evals fail
- Works with any deployment platform (Railway, Fly, AWS, etc.)

---

## Prerequisites

- A [LiveKit Cloud](https://livekit.io) project
- A [Cekura](https://api.cekura.ai) account
- A deployed staging LiveKit agent (your agent process must be running and connected to LiveKit before evals run)

---

## Step 1: Set up Cekura (one-time)

1. Go to [api.cekura.ai](https://api.cekura.ai) → **New Project**
2. Create an agent: **Agents** → **Add Agent** → Select **LiveKit** as connection type
3. Enter your LiveKit server URL (`wss://your-app.livekit.cloud`)
4. Note your **Agent ID** (e.g., `42`)
5. Create scenarios: **Scenarios** → **Generate Scenarios**
6. Note your **Scenario IDs** (e.g., `1234,1235,1236`)
7. Get your **API key**: Settings → API Keys

---

## Step 2: Add GitHub secrets

| Secret name | Value |
|---|---|
| `CEKURA_API_KEY` | Your Cekura API key |

---

## Step 3: Add the workflow file

Your workflow has two parts: deploy your LiveKit agent (using whatever you already use), then run Cekura evals.

Create `.github/workflows/cekura-eval.yml`:

```yaml
name: Cekura Evals

on:
  pull_request:
    branches: [main]

jobs:
  # Deploy your LiveKit agent using your existing deployment process
  # This is an example — replace with your actual deploy steps
  deploy:
    runs-on: ubuntu-latest
    outputs:
      livekit_url: ${{ steps.get-url.outputs.url }}
    steps:
      - uses: actions/checkout@v4

      - name: Deploy LiveKit agent
        run: |
          # Your deployment steps here
          # e.g., deploy to Railway, Fly, ECS, etc.
          echo "Deployed!"

      - name: Get LiveKit server URL
        id: get-url
        run: |
          # This is typically a static URL from your LiveKit Cloud project
          echo "url=wss://your-app.livekit.cloud" >> $GITHUB_OUTPUT

  # Run Cekura evals against the deployed agent
  eval:
    needs: deploy
    uses: cekura-ai/cekura-github-actions/.github/workflows/livekit-eval.yml@v2
    with:
      livekit_agent_url: ${{ needs.deploy.outputs.livekit_url }}
      cekura_agent_id: "42"           # from Step 1
      scenario_ids: "1234,1235,1236"   # from Step 1
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

---

## Static staging URL (simplest case)

If you have a persistent staging environment, you don't need the deploy job at all:

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/livekit-eval.yml@v2
    with:
      livekit_agent_url: "wss://staging.your-app.livekit.cloud"
      cekura_agent_id: "42"
      scenario_ids: "1234,1235,1236"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

---

## Step 4: Enable branch protection (optional)

In your repo: **Settings → Branches → Add rule** for your main branch:
- Check **Require status checks to pass before merging**
- Add `eval / check` to required checks

---

## Text transport (non-voice testing)

For text-only agent testing over LiveKit data channels:

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/livekit-eval.yml@v2
    with:
      livekit_agent_url: "wss://your-app.livekit.cloud"
      transport: text
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```
