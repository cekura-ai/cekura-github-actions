# Cekura GitHub Actions

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-blue?logo=github-actions)](https://github.com/cekura-ai/vocera-github-actions)
[![Documentation](https://img.shields.io/badge/Documentation-Available-green?logo=gitbook)](https://docs.cekura.ai/guides/github-actions-ci-cd)

Automate your agent testing by integrating Cekura with GitHub Actions. This repository provides a reusable workflow for running Cekura test scenarios in your CI/CD pipeline.

## Features

- **Reusable Workflow**: Simple integration using GitHub's reusable workflow pattern
- **Flexible Testing**: Support for scenario IDs, tags, or both
- **Multiple Triggers**: Manual runs, PR testing, scheduled runs, or push events
- **Phone Number Support**: Test outbound calling scenarios
- **Configurable**: Customize frequency, timeout, and API endpoint

## Quick Start

### 1. Set Up Repository Secrets & Variables

Go to your repository **Settings** → **Secrets and variables** → **Actions**:

**Add Secret:**
- `CEKURA_API_KEY` - Your Cekura API key

**Add Variables:**
- `AGENT_ID` - Your agent ID (required)
- `SCENARIO_IDS` - Comma-separated scenario IDs (e.g., `123,456,789`) OR
- `TAGS` - Comma-separated tags (e.g., `smoke-test,critical`)
- `PHONE_NUMBER` - (Optional) Outbound phone number for testing

### 2. Create Workflow File

Create `.github/workflows/test-agents.yml` in your repository:

```yaml
name: Agent Tests

on:
  push:
    branches: [main]
  pull_request:
    types:
      - opened

jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      tags: ${{ vars.TAGS }}
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

### 3. Trigger and Monitor

Make a change and raise a pull request. The workflow will run automatically, and you can monitor results on [dashboard.cekura.ai](https://dashboard.cekura.ai) in the Results section.

## Usage Examples

### Using Scenario IDs

```yaml
jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      scenario_ids: ${{ vars.SCENARIO_IDS }}
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

### Using Tags

```yaml
jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      tags: ${{ vars.TAGS }}
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

### Using Both Tags and Scenario IDs

```yaml
jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      tags: ${{ vars.TAGS }}
      scenario_ids: ${{ vars.SCENARIO_IDS }}
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

### Testing with Phone Numbers

```yaml
jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      scenario_ids: ${{ vars.SCENARIO_IDS }}
      phone_number: ${{ vars.PHONE_NUMBER }}
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

### Manual Trigger

```yaml
name: Agent Tests

on:
  workflow_dispatch:

jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      tags: ${{ vars.TAGS }}
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

Then trigger from the Actions tab → Run workflow button.

### Scheduled Testing

```yaml
name: Nightly Tests

on:
  schedule:
    - cron: '0 2 * * *'  # Run at 2 AM daily

jobs:
  test:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.AGENT_ID }}
      tags: 'regression'
    secrets:
      CEKURA_API_KEY: ${{ secrets.CEKURA_API_KEY }}
```

### Environment-Specific Testing

```yaml
jobs:
  test-staging:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.STAGING_AGENT_ID }}
      tags: 'smoke-test'
      api_url: 'https://staging-api.cekura.ai'
    secrets:
      CEKURA_API_KEY: ${{ secrets.STAGING_API_KEY }}

  test-production:
    uses: cekura-ai/vocera-github-actions/.github/workflows/cekura_run_tests.yml@main
    with:
      agent_id: ${{ vars.PROD_AGENT_ID }}
      tags: 'smoke-test'
    secrets:
      CEKURA_API_KEY: ${{ secrets.PROD_API_KEY }}
```

## Workflow Inputs

The reusable workflow accepts these inputs:

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `agent_id` | Agent ID to test | Yes | - |
| `scenario_ids` | Comma-separated scenario IDs (e.g., `123,456,789`) | No* | - |
| `tags` | Comma-separated tags (e.g., `smoke-test,critical`) | No* | - |
| `phone_number` | Outbound phone number for testing | No | - |
| `api_url` | Cekura API URL | No | `https://api.cekura.ai` |
| `frequency` | Run each scenario N times | No | `1` |
| `timeout` | Timeout in seconds | No | `3600` |

*Either `scenario_ids` or `tags` must be provided (or both)

## Files in This Repository

| File | Description |
|------|-------------|
| `.github/workflows/cekura_run_tests.yml` | Reusable workflow for running Cekura tests |
| `run_scenarios.py` | Python script (legacy, kept for backward compatibility) |
| `requirements.txt` | Python dependencies (legacy) |
| `action.yml` | Composite action metadata |
| `README.md` | This file |

## Complete Documentation

For a comprehensive guide on GitHub Actions with Cekura, including:
- Step-by-step setup tutorial
- GitHub secrets and variables configuration
- Advanced patterns and best practices
- Complete troubleshooting guide

Visit our documentation: **[GitHub Actions Tutorial](https://docs.cekura.ai/guides/github-actions-ci-cd)**

## License

This project is licensed under the MIT License.

---

© 2024 Cekura AI. All rights reserved.
