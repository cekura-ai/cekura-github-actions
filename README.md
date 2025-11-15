# Cekura GitHub Actions

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-blue?logo=github-actions)](https://github.com/cekura-ai/cekura-github-actions)
[![Documentation](https://img.shields.io/badge/Documentation-Available-green?logo=gitbook)](https://docs.cekura.ai/documentation/guides/github-actions-ci-cd)

Automate your agent testing by integrating Cekura with GitHub Actions. This action runs Cekura test scenarios directly in your CI/CD pipeline with zero dependencies.

## What This Action Does

This GitHub Action allows you to test your Cekura agents automatically:
- Triggers tests on your Cekura agents via API
- Monitors test execution in real-time
- Reports detailed results in your GitHub Actions logs
- **No dependencies required** - uses standard tools (curl, bash, python3) available on GitHub runners

## Quick Start

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
name: Test Agents

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run Cekura Tests
        uses: cekura-ai/cekura-github-actions@main
        with:
          agent_id: ${{ vars.AGENT_ID }}
          tags: ${{ vars.TAGS }}
          api_key: ${{ secrets.CEKURA_API_KEY }}
```

### 3. Push and Run

Commit and push your workflow file. The action will run automatically on the next push or pull request.

## Usage Examples

### Using Scenario IDs

Test specific scenarios by their IDs:

```yaml
steps:
  - name: Run Cekura Tests
    uses: cekura-ai/cekura-github-actions@main
    with:
      agent_id: 'your-agent-id'
      scenario_ids: '123,456,789'
      api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Using Tags

Test all scenarios with specific tags:

```yaml
steps:
  - name: Run Cekura Tests
    uses: cekura-ai/cekura-github-actions@main
    with:
      agent_id: 'your-agent-id'
      tags: 'smoke-test,critical'
      api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Using Both Tags and Scenario IDs

Combine both approaches:

```yaml
steps:
  - name: Run Cekura Tests
    uses: cekura-ai/cekura-github-actions@main
    with:
      agent_id: 'your-agent-id'
      scenario_ids: '123,456'
      tags: 'smoke-test'
      api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Testing with Phone Numbers

When testing agents that make outbound calls:

```yaml
steps:
  - name: Run Cekura Tests
    uses: cekura-ai/cekura-github-actions@main
    with:
      agent_id: 'your-agent-id'
      scenario_ids: '123,456'
      phone_number: '+1234567890'
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
        description: 'Agent ID'
        required: true
      scenario_ids:
        description: 'Scenario IDs (comma-separated)'
        required: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run Cekura Tests
        uses: cekura-ai/cekura-github-actions@main
        with:
          agent_id: ${{ github.event.inputs.agent_id }}
          scenario_ids: ${{ github.event.inputs.scenario_ids }}
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
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run Cekura Tests
        uses: cekura-ai/cekura-github-actions@main
        with:
          agent_id: ${{ vars.AGENT_ID }}
          tags: 'regression'
          api_key: ${{ secrets.CEKURA_API_KEY }}
```

### Environment-Specific Testing

Test multiple environments in the same workflow:

```yaml
jobs:
  test-staging:
    runs-on: ubuntu-latest
    steps:
      - name: Test Staging
        uses: cekura-ai/cekura-github-actions@main
        with:
          agent_id: ${{ vars.STAGING_AGENT_ID }}
          tags: 'smoke-test'
          api_url: 'https://staging-api.cekura.ai'
          api_key: ${{ secrets.STAGING_API_KEY }}

  test-production:
    runs-on: ubuntu-latest
    needs: test-staging
    steps:
      - name: Test Production
        uses: cekura-ai/cekura-github-actions@main
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
