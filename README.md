# Cekura GitHub Actions - Scenario Runner

Run automated test scenarios against Cekura agents directly from your GitHub workflows. This repository provides reusable workflows and examples for integrating Cekura scenario testing into your CI/CD pipeline.

## Features

- **Multiple Trigger Types**: Manual runs, automatic PR testing, or label-based triggers
- **Flexible Configuration**: Use workflow inputs or repository secrets
- **Easy Integration**: Simple Python script with minimal dependencies
- **Workflow Examples**: Ready-to-use templates for common use cases

## Quick Start

### 1. Set Up Repository Secrets

Go to your repository **Settings** → **Secrets and variables** → **Actions** and add:

| Secret Name | Description | Required |
|------------|-------------|----------|
| `API_BASE_URL` | Your Cekura API base URL | Yes |
| `API_KEY` | Your Cekura API key | Yes |
| `AGENT_ID` | Default agent ID (optional if using manual trigger) | No |
| `SCENARIOS` | Default scenario IDs, comma-separated (optional) | No |

### 2. Copy Files to Your Repository

Copy the following files from this repository to yours:

```bash
# Copy the Python script
curl -o run_scenarios.py https://raw.githubusercontent.com/cekura-ai/vocera-github-actions/main/run_scenarios.py

# Copy requirements
curl -o requirements.txt https://raw.githubusercontent.com/cekura-ai/vocera-github-actions/main/requirements.txt

# Create workflows directory
mkdir -p .github/workflows

# Copy workflow examples
curl -o .github/workflows/run-scenarios.yml https://raw.githubusercontent.com/cekura-ai/vocera-github-actions/main/.github/workflows/run-scenarios.yml
```

## Usage Examples

### Method 1: Manual Trigger

Run scenarios on-demand from the GitHub Actions UI.

The `run-scenarios.yml` workflow in this repo supports manual triggering. To use it:

1. Go to **Actions** → **Run Scenarios** → **Run workflow**
2. Enter your agent ID and scenario IDs
3. Click **Run workflow**

### Method 2: Automatic on Pull Request

Automatically run scenarios when PRs are opened or updated.

The `run-scenarios.yml` workflow automatically runs on PR events. Make sure you have `AGENT_ID` and `SCENARIOS` configured in your repository secrets.

```yaml
# Triggers automatically on:
# - PR opened
# - PR synchronized (new commits)
# - PR reopened
```

### Method 3: Label-Based Trigger

Run scenarios by adding a label to a PR.

Simply add the label `run-scenarios` to any PR, and the workflow will trigger automatically.

```yaml
# The workflow detects when a label is added
# Just add 'run-scenarios' label to your PR
```

### Method 4: Post-Deployment Testing

Run scenarios after deploying your application.

See `.github/workflows/deploy.yml` for an example:

```yaml
name: Deploy and Test

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - name: Deploy
      run: ./deploy.sh

  run-scenarios:
    needs: deploy
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.x'
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Run scenarios
      env:
        API_BASE_URL: ${{ secrets.API_BASE_URL }}
        API_KEY: ${{ secrets.API_KEY }}
        AGENT_ID: ${{ secrets.AGENT_ID }}
        SCENARIOS: ${{ secrets.SCENARIOS }}
        FREQUENCY: "1"
        TIMEOUT: "1800"
      run: python run_scenarios.py
```

## Configuration

### Environment Variables

The `run_scenarios.py` script uses the following environment variables:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `API_BASE_URL` | Cekura API base URL | Yes | - |
| `API_KEY` | Cekura API key for authentication | Yes | - |
| `AGENT_ID` | Agent ID to run scenarios against | Yes | - |
| `SCENARIOS` | Comma-separated scenario IDs | Yes | - |
| `FREQUENCY` | Number of times to run each scenario | No | 1 |
| `TIMEOUT` | Timeout in seconds | No | 3600 |
| `POLL_INTERVAL` | Polling interval in seconds | No | 30 |

### Workflow Inputs vs Secrets

The main workflow supports both manual inputs and secrets:

- **Manual inputs** (workflow_dispatch): Used when running manually from GitHub UI
- **Repository secrets**: Used for automatic triggers (PR, labels, scheduled runs)
- **Fallback**: Manual inputs take precedence over secrets

## Advanced Usage

### Using in Other Repositories

You can reference the Python script from this repository:

```yaml
- name: Download and run scenarios
  env:
    API_BASE_URL: ${{ secrets.API_BASE_URL }}
    API_KEY: ${{ secrets.API_KEY }}
    AGENT_ID: "your-agent-id"
    SCENARIOS: "123,456,789"
  run: |
    curl -o run_scenarios.py https://raw.githubusercontent.com/cekura-ai/vocera-github-actions/main/run_scenarios.py
    pip install requests
    python run_scenarios.py
```

### Customizing Triggers

Modify the `on:` section in your workflow to customize triggers:

```yaml
on:
  # Run on schedule (nightly at 2 AM)
  schedule:
    - cron: '0 2 * * *'

  # Run on specific branches
  push:
    branches:
      - main
      - staging

  # Run on release
  release:
    types: [created]
```

### Multiple Agents or Scenario Sets

Create separate workflow files for different test suites:

```yaml
# .github/workflows/smoke-tests.yml
name: Smoke Tests
env:
  AGENT_ID: "smoke-test-agent"
  SCENARIOS: "1,2,3"

# .github/workflows/regression-tests.yml
name: Regression Tests
env:
  AGENT_ID: "regression-agent"
  SCENARIOS: "10,20,30,40,50"
```

## Files in This Repository

| File | Description |
|------|-------------|
| `run_scenarios.py` | Python script that runs Cekura scenarios |
| `requirements.txt` | Python dependencies |
| `.github/workflows/run-scenarios.yml` | Main workflow supporting multiple triggers |
| `.github/workflows/deploy.yml` | Example deployment workflow with scenario testing |
| `action.yml` | Composite action metadata |
| `README.md` | This file |

## Troubleshooting

### Workflow Not Triggering

- Ensure workflow file is in `.github/workflows/` directory
- Check YAML syntax is correct
- Verify trigger conditions match your event
- For label triggers, ensure the label name matches exactly

### Authentication Errors

- Verify `API_BASE_URL` and `API_KEY` secrets are set correctly
- Check secret names are exactly as specified (case-sensitive)
- Ensure API key has necessary permissions

### Scenarios Failing

- Check scenario IDs are correct and comma-separated
- Verify agent ID exists and is accessible
- Review workflow logs for detailed error messages
- Ensure timeout is sufficient for your scenarios

### Permission Denied

Add permissions to your workflow if needed:

```yaml
permissions:
  contents: read
  pull-requests: write  # For PR comments
```

## Complete Documentation

For a comprehensive guide on GitHub Actions CI/CD with Cekura, including:
- Detailed workflow setup instructions
- GitHub secrets configuration
- Advanced patterns and best practices
- Complete troubleshooting guide

Visit our documentation: [GitHub Actions CI/CD Guide](https://docs.cekura.ai)

## Support

- **Documentation**: https://docs.cekura.ai
- **Issues**: Open an issue in this repository
- **Email**: support@cekura.ai

## License

This project is licensed under the MIT License.

---

© 2024 Cekura AI. All rights reserved.
