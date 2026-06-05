# Quickstart: Custom Stack + Cekura CI/CD

For voice agents NOT using Pipecat Cloud or LiveKit — custom WebSocket servers, SIP/telephony, VAPI, Retell, ElevenLabs, or any other provider.

## Supported connection types

| `connection_type` in Cekura | Transport | When to use |
|---|---|---|
| `pipecat` | Pipecat Cloud WebRTC | [See pipecat quickstart](./quickstart-pipecat.md) |
| `livekit` | LiveKit WebRTC | [See livekit quickstart](./quickstart-livekit.md) |
| `websocket` | WebSocket | Custom WebSocket server |
| `sip` | SIP/Telephony | Twilio, Vonage, or any SIP endpoint |
| `vapi` | VAPI WebRTC | VAPI-hosted agents |
| `retell` | Retell WebRTC | Retell-hosted agents |
| `elevenlabs` | ElevenLabs | ElevenLabs Conversational AI |
| `text` | Text | Non-voice testing |

---

## How it works

The `eval.yml` generic workflow handles any connection type. You:
1. Deploy your agent using your existing process
2. Call `eval.yml` with `cekura_agent_id` + `scenario_ids`

The connection type is configured on the Cekura agent (one-time in the Cekura dashboard). The workflow just runs the scenarios.

---

## Setup

### 1. Create your agent in Cekura

1. Go to [api.cekura.ai](https://api.cekura.ai) → **New Project**
2. **Agents** → **Add Agent** → Select your connection type (WebSocket, SIP, VAPI, etc.)
3. Enter your agent's endpoint URL / phone number / API details
4. Note your **Agent ID**
5. Create scenarios → note **Scenario IDs**
6. Get your **API key**

### 2. Add GitHub secret

| Secret name | Value |
|---|---|
| `CEKURA_API_KEY` | Your Cekura API key |

---

## WebSocket agent

```yaml
# .github/workflows/cekura-eval.yml
name: Cekura Evals

on:
  pull_request:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy my WebSocket agent
        run: |
          # Your deploy logic — Railway, Fly, ECS, etc.

  eval:
    needs: deploy
    uses: cekura-ai/cekura-github-actions/.github/workflows/eval.yml@v2
    with:
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

---

## SIP / Telephony agent

The Cekura agent in your dashboard must have the SIP phone number configured. Once set, running evals is simple:

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/eval.yml@v2
    with:
      cekura_agent_id: "42"      # SIP number is configured on this agent in Cekura
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

---

## VAPI / Retell / ElevenLabs

The connection details (VAPI agent ID, Retell API key, ElevenLabs agent ID) are configured on the Cekura agent. The workflow is identical:

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/eval.yml@v2
    with:
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
      frequency: "3"              # run each scenario 3 times
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

---

## Using standalone composite actions

For maximum control, use the composite actions directly in your own workflow instead of the reusable workflows:

```yaml
jobs:
  my-custom-flow:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Build and push to GHCR
      - uses: cekura-ai/cekura-github-actions/actions/build-and-push-ghcr@v2
        id: build
        with:
          agent_name: my-agent
          pr_number: ${{ github.event.pull_request.number }}
          sha: ${{ github.sha }}
          ghcr_token: ${{ github.token }}

      # Deploy to Pipecat Cloud
      - uses: cekura-ai/cekura-github-actions/actions/deploy-pipecat@v2
        id: deploy
        with:
          api_key: ${{ secrets.PIPECAT_API_KEY }}
          agent_name: my-agent
          image_uri: ${{ steps.build.outputs.image_uri }}
          pr_number: ${{ github.event.pull_request.number }}
          secret_set: my-agent-secrets
          pull_secret: my-agent-pull-secret

      # Run Cekura scenarios (using the root action)
      - uses: cekura-ai/cekura-github-actions@v2
        with:
          agent_id: "42"
          scenario_ids: "1234,1235"
          api_key: ${{ secrets.CEKURA_API_KEY }}
```
