"""Triage Agent: classifies a CI failure's root cause using whatever LLM
is configured in config/llm.yml.

Only ever produces a classification — it never decides what to do about it.
Remediation/Governance/Notifier decide that downstream.
"""
from lib.llm_client import chat_json

MAX_LOG_CHARS = 8000

SYSTEM_PROMPT = """You are a CI/CD failure triage assistant. You will be given \
the tail of a CI job log from a failed run. Classify the root cause into \
exactly one category:

- "infra_flaky": the failure is timing-, concurrency-, or environment- \
dependent (a race condition, a tight latency assertion, a transient network \
error, a runner hiccup) rather than a real logic error. Not something to fix \
by editing code.
- "dependency_issue": the build failed to resolve or use a dependency \
(missing artifact, bad/incompatible version, lockfile drift).
- "app_bug": a test failed because of a real logic error in application \
code — a genuine mismatch between expected and actual behavior on a fixed \
input. This requires understanding business intent, so it is NEVER something \
this system fixes automatically; it only diagnoses it clearly for a human.

Respond with ONLY a JSON object, no prose, matching this exact shape:
{
  "category": "infra_flaky" | "dependency_issue" | "app_bug",
  "confidence": <float 0-1, how sure you are of this classification>,
  "root_cause": "<two or three sentence explanation a developer could act on \
immediately, citing the specific test/file/error from the log>"
}
"""


def classify(log_text: str) -> dict:
    result = chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Build log tail:\n\n{log_text[-MAX_LOG_CHARS:]}",
    )
    result.setdefault("category", "app_bug")
    result.setdefault("confidence", 0.0)
    result.setdefault("root_cause", "")
    return result
