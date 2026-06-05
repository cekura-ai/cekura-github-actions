# Cekura GitHub Actions

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-blue?logo=github-actions)](https://github.com/cekura-ai/cekura-github-actions)
[![Documentation](https://img.shields.io/badge/Documentation-Available-green?logo=gitbook)](https://docs.cekura.ai/documentation/guides/github-actions-ci-cd)

Automated voice agent CI/CD for Pipecat, LiveKit, and any other voice agent stack. Cekura's testing agents connect to your agent, run your scenarios, and block PR merges if anything fails.

## v2: Full CI/CD with deploy + eval (new)

v2 adds reusable workflows that handle the full lifecycle: build → deploy → eval → PR comment → cleanup. Pick your path:

| Path | Workflow | What it does |
|---|---|---|
| **Pipecat Cloud** | `pipecat-eval.yml` | Builds Docker image, deploys to Pipecat Cloud, runs evals, cleans up |
| **LiveKit** | `livekit-eval.yml` | Runs evals against your deployed LiveKit agent |
| **Custom / Any stack** | `eval.yml` | Runs evals for any already-deployed agent (SIP, WebSocket, VAPI, Retell, ElevenLabs, text) |

### Pipecat Cloud (10-minute setup)

```yaml
# .github/workflows/cekura-eval.yml
name: Cekura Evals
on:
  pull_request:
    branches: [main]
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/pipecat-eval.yml@v2
    with:
      agent_name: my-voice-agent
      pipecat_secret_set: my-agent-secrets        # pre-created in Pipecat Cloud
      pipecat_pull_secret: my-agent-pull-secret   # pre-created in Pipecat Cloud
      cekura_agent_id: "42"
      scenario_ids: "1234,1235,1236"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
      PIPECAT_API_KEY: ${{ secrets.PIPECAT_API_KEY }}
```

Add the cleanup workflow to delete the PR agent when the PR closes:

```yaml
# .github/workflows/cekura-cleanup.yml
name: Cleanup PR agent
on:
  pull_request:
    types: [closed]
jobs:
  cleanup:
    uses: cekura-ai/cekura-github-actions/.github/workflows/pipecat-cleanup.yml@v2
    with:
      agent_name: my-voice-agent
    secrets:
      PIPECAT_API_KEY: ${{ secrets.PIPECAT_API_KEY }}
```

See [docs/quickstart-pipecat.md](docs/quickstart-pipecat.md) for the full setup guide.

### LiveKit

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/livekit-eval.yml@v2
    with:
      livekit_agent_url: "wss://my-app.livekit.cloud"
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

See [docs/quickstart-livekit.md](docs/quickstart-livekit.md) for the full setup guide.

### Custom stack (WebSocket, SIP, VAPI, Retell, ElevenLabs, text)

```yaml
jobs:
  eval:
    uses: cekura-ai/cekura-github-actions/.github/workflows/eval.yml@v2
    with:
      cekura_agent_id: "42"
      scenario_ids: "1234,1235"
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

See [docs/quickstart-custom.md](docs/quickstart-custom.md) for the full setup guide.

---

## v1: Run evals against an already-deployed agent (original)

The original composite action — triggers scenarios for an agent that's already deployed and waits for results.

## Quick Start (v1)

### 1. Set Up Repository Secrets

Go to your repository **Settings** → **Secrets and variables** → **Actions** and add:

**Secret:**
- `CEKURA_API_KEY` - Your Cekura API key from [dashboard.cekura.ai](https://dashboard.cekura.ai)

**Variables** (optional, can also be hardcoded in workflow):
- `AGENT_ID` - Your agent ID
- `SCENARIO_IDS` - Comma-separated scenario IDs (e.g., `123,456,789`) OR
- `TAGS` - Comma-separated tags (e.g., `smoke-test,critical`)

### 2. Create Workflow File

Create `.github/workflows/test-agents.yml` in your repository:

```yaml
name: Agent Tests

on:
  workflow_dispatch:
    inputs:
      agent_id:
        description: 'The agent identifier'
        required: false
        type: string
      scenario_ids:
        description: 'Comma-separated scenario IDs (e.g., "123,456,789")'
        required: false
        type: string
      api_url:
        description: 'Custom Cekura API endpoint'
        required: false
        type: string
        default: 'https://api.cekura.ai'

  push:
    branches: [main]
  pull_request:

jobs:
  run-simulation-tests:
    runs-on: ubuntu-latest
    steps:
      - name: Cekura Run Tests
        uses: cekura-ai/cekura-github-actions@v1.0.0
        with:
          agent_id: ${{ inputs.agent_id || vars.AGENT_ID }}
          scenario_ids: ${{ inputs.scenario_ids || vars.SCENARIO_IDS }}
          api_url: ${{ inputs.api_url || vars.API_URL }}
          api_key: ${{ secrets.CEKURA_API_KEY }}
```

### 3. Push and Run

Commit and push your workflow file. The action will run automatically on the next push or pull request.

## Usage Examples

### Using Scenario IDs

Test specific scenarios by their IDs:

```yaml
- name: Run Cekura Tests
  uses: cekura-ai/cekura-github-actions@v1.0.0
  with:
    agent_id: ${{ vars.AGENT_ID }}
    scenario_ids: ${{ vars.SCENARIO_IDS }}
    api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Using Tags

Test all scenarios with specific tags:

```yaml
- name: Run Cekura Tests
  uses: cekura-ai/cekura-github-actions@v1.0.0
  with:
    agent_id: ${{ vars.AGENT_ID }}
    tags: ${{ vars.TAGS }}
    api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Using Both Tags and Scenario IDs

Combine both approaches:

```yaml
- name: Run Cekura Tests
  uses: cekura-ai/cekura-github-actions@v1.0.0
  with:
    agent_id: ${{ vars.AGENT_ID }}
    scenario_ids: ${{ vars.SCENARIO_IDS }}
    tags: ${{ vars.TAGS }}
    api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Testing with Phone Numbers

When testing agents that make outbound calls:

```yaml
- name: Run Cekura Tests
  uses: cekura-ai/cekura-github-actions@v1.0.0
  with:
    agent_id: ${{ vars.AGENT_ID }}
    scenario_ids: ${{ vars.SCENARIO_IDS }}
    phone_number: ${{ vars.PHONE_NUMBER }}
    api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Manual Trigger

Allow manual workflow runs from the Actions tab:

```yaml
name: Manual Tests

on:
  workflow_dispatch:
    inputs:
      agent_id:
        description: 'The agent identifier'
        required: false
        type: string
      scenario_ids:
        description: 'Comma-separated scenario IDs (e.g., "123,456,789")'
        required: false
        type: string

jobs:
  run-simulation-tests:
    runs-on: ubuntu-latest
    steps:
      - name: Run Cekura Tests
        uses: cekura-ai/cekura-github-actions@v1.0.0
        with:
          agent_id: ${{ inputs.agent_id || vars.AGENT_ID }}
          scenario_ids: ${{ inputs.scenario_ids || vars.SCENARIO_IDS }}
          api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Scheduled Testing

Run tests automatically on a schedule:

```yaml
name: Nightly Tests

on:
  schedule:
    - cron: '0 2 * * *'  # Run at 2 AM daily

jobs:
  run-simulation-tests:
    runs-on: ubuntu-latest
    steps:
      - name: Run Cekura Tests
        uses: cekura-ai/cekura-github-actions@v1.0.0
        with:
          agent_id: ${{ vars.AGENT_ID }}
          tags: 'regression'
          api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Environment-Specific Testing

Test multiple environments in the same workflow:

```yaml
jobs:
  staging-tests:
    runs-on: ubuntu-latest
    steps:
      - name: Test Staging
        uses: cekura-ai/cekura-github-actions@v1.0.0
        with:
          agent_id: ${{ vars.STAGING_AGENT_ID }}
          tags: 'smoke-test'
          api_url: 'https://staging-api.cekura.ai'
          api_key: ${{ secrets.STAGING_API_KEY }}

  production-tests:
    runs-on: ubuntu-latest
    needs: staging-tests
    steps:
      - name: Test Production
        uses: cekura-ai/cekura-github-actions@v1.0.0
        with:
          agent_id: ${{ vars.PROD_AGENT_ID }}
          tags: 'smoke-test'
          api_key: ${{ secrets.PROD_API_KEY }}
```

## Inputs

All inputs for the action:

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `agent_id` | Agent ID to test | Yes | - |
| `api_key` | Cekura API Key | Yes | - |
| `scenario_ids` | Comma-separated scenario IDs (e.g., `123,456,789`) | No* | - |
| `tags` | Comma-separated tags (e.g., `smoke-test,critical`) | No* | - |
| `phone_number` | Outbound phone number for testing | No | - |
| `api_url` | Cekura API URL | No | `https://api.cekura.ai` |
| `frequency` | Run each scenario N times | No | `1` |
| `timeout` | Timeout in seconds | No | `3600` |

*Either `scenario_ids` or `tags` must be provided (or both)

## How It Works

The action uses standard tools pre-installed on GitHub runners:
- `curl` for API communication
- `bash` for script orchestration
- `python3` for JSON parsing

No additional dependencies or setup steps required - it works out of the box on `ubuntu-latest` runners.

### Workflow Behavior

- **Success**: If all test runs pass (failed count = 0), the workflow exits successfully ✅
- **Failure**: If any test runs fail (failed count > 0), the workflow exits with an error ❌

This ensures your CI/CD pipeline correctly reflects the state of your agent tests.

## Complete Documentation

For a comprehensive guide including:
- Step-by-step setup tutorial with screenshots
- GitHub secrets and variables configuration
- Advanced patterns and best practices
- Complete troubleshooting guide

Visit: **[GitHub Actions Tutorial](https://docs.cekura.ai/documentation/guides/github-actions-ci-cd)**

## Support

- **Documentation**: [docs.cekura.ai](https://docs.cekura.ai/documentation/guides/github-actions-ci-cd)
- **Dashboard**: [dashboard.cekura.ai](https://dashboard.cekura.ai)
- **Issues**: [GitHub Issues](https://github.com/cekura-ai/cekura-github-actions/issues)

## License

MIT License

---

© 2024 Cekura AI. All rights reserved.
