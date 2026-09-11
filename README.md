# Self-Healing CI Agent

A standalone, multi-agent system that watches other repos' CI pipelines for
real failures, diagnoses root cause with an LLM, and either fixes the safe
categories automatically (with a real governance gate) or hands a developer
a ready-made diagnosis for anything that requires understanding business
intent. It never guesses at application logic — that boundary is enforced
by design, not just by prompt.

This repo is the "brain"; the repos it watches (e.g. `SampleApp`) are the
"bodies." It never runs inside their pipelines — it polls them from the
outside via the GitHub API, on its own schedule.

## Architecture

```
Orchestrator (scheduled, every 15 min)
  └─ for each watched repo, for each new failed run:
       Triage Agent        -> classify root cause + confidence (Groq LLM)
       ├─ infra_flaky?     -> Notifier: flag as flaky, no code change
       └─ else:
            Remediation Agent -> propose a fix (dependency_issue only,
                                  never for app_bug)
            ├─ no fix proposed -> Notifier: diagnosis Issue
            └─ fix proposed:
                 Governance Agent -> approve/block against policy.yml
                 ├─ approved -> Notifier: open PR with the fix
                 └─ blocked  -> Notifier: diagnosis Issue
       Every decision, either way, is appended to audit/log.jsonl
```

| Agent | File | Job |
|---|---|---|
| Orchestrator | `agents/orchestrator.py` | Finds new failures, drives each through the pipeline |
| Triage | `agents/triage_agent.py` | Classifies: `infra_flaky` / `dependency_issue` / `app_bug`, with confidence |
| Remediation | `agents/remediation_agent.py` | Proposes a fix — only a confident, mechanical revert of a dependency-manifest file changed in the last commit; never generates code |
| Governance | `agents/governance_agent.py` | Approves/blocks a proposed fix against `config/policy.yml`; always logs why |
| Notifier | `agents/notifier_agent.py` | The only agent that talks to a watched repo — opens the PR, flags flaky, or posts a diagnosis Issue tagging the likely developer |

## Why application bugs are never auto-fixed

`dependency_issue` failures have an objectively correct fix: the dependency
manifest changed, the build broke, revert the manifest change. `app_bug`
failures don't — "the test expected 5 and got 6" doesn't tell you whether
the test or the code is wrong, only a human who knows the intended behavior
does. So `app_bug` never reaches the Remediation Agent with anything to
propose; it always goes straight to a diagnosis Issue instead.

## Governance

`config/policy.yml` is the single source of truth for what the Governance
Agent will allow:

- `enabled` — global kill switch.
- `repos.<owner>/<repo>.enabled` — per-repo kill switch (default deny — a
  repo not listed here is never auto-fixed).
- `auto_fix_categories` — allowlist of Triage categories eligible for
  auto-fix.
- `min_confidence` — Triage confidence floor; below it, always fall back to
  a diagnosis Issue regardless of category.
- `max_files_changed` — blast-radius limit on a proposed fix.

Every Governance check — approved or blocked — is written to
`audit/log.jsonl` with its reasoning, alongside every Triage classification
and Notifier action. That file is the full audit trail: what the agent saw,
what it decided, and why, for every run it ever processed.

## LLM provider

The Triage Agent calls whatever's configured in `config/llm.yml` — `lib/llm_client.py`
has no provider-specific code, it just speaks the OpenAI-compatible
chat-completions format that Groq, GitHub Models, OpenAI, and most other
providers all support. Switching providers or models is a one-line config
edit, not a code change:

```yaml
provider: groq
base_url: https://api.groq.com/openai/v1/chat/completions
model: llama-3.3-70b-versatile
api_key_env: GROQ_API_KEY
```

`api_key_env` names the environment variable the client reads the API key
from. `.github/workflows/watch.yml` already exposes `GROQ_API_KEY`,
`GITHUB_MODELS_TOKEN`, and `OPENAI_API_KEY` (each from a same-named repo
secret) — commented-out examples for both are in `config/llm.yml`, so
switching between those three is just uncommenting one block. Only a
provider not already listed there needs a new line added to the workflow's
`env:` block plus a matching secret.

## Setup

1. **Watched repos**: list them in `config/watched_repos.yml`.
2. **LLM API key**: `gh secret set GROQ_API_KEY` on this repo (free tier at
   [console.groq.com](https://console.groq.com)) — or whichever secret name
   matches `api_key_env` in `config/llm.yml` if you've switched providers.
3. **Watched-repo access**: create a fine-grained GitHub PAT scoped to
   exactly the repos in `watched_repos.yml`, with:
   - Contents: Read and write
   - Pull requests: Read and write
   - Issues: Read and write
   - Actions: Read-only

   Then `gh secret set WATCHED_REPOS_PAT` on this repo. This repo's own
   `GITHUB_TOKEN` is never used against watched repos — only to commit
   `state/` and `audit/` back to itself.

## Running it

It runs on its own every 15 minutes via `.github/workflows/watch.yml`. To
run it on demand: `gh workflow run watch.yml`.

To generate a real failure to watch for, trigger `SampleApp`'s own demo
scenario (see its README) — that produces a genuine failed run in a real
repo for this agent to discover and react to on its next poll.

## Backlog (deliberately deferred)

- **Triage eval set**: a small labeled set of sample failure logs with
  known-correct categories, to measure the Triage Agent's classification
  accuracy before trusting it further — not built yet.
- **Cross-run failure memory**: `state/` currently only dedupes
  already-processed runs. It doesn't yet track patterns over time (e.g. "this
  test has failed 5 times this month"), which would need a real persistence
  decision beyond a per-repo last-run-id file.
