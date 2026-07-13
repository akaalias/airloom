"""Shared headless `claude -p` invocation.

Both LLM surfaces of the loop (narrator, designer) are pure X->Y
transformations, so every call goes through the CLI's structured-output
mode (`--json-schema`): the reply is schema-validated JSON, which ends the
malformed-JSON note losses the free-text era suffered. The CLI's JSON
envelope also reports which model ACTUALLY served the call (`modelUsage`
keys are exact model ids) -- callers store and display that, since the
configured model is often empty (= CLI default) or an alias like "opus".
"""
from __future__ import annotations

import json
import subprocess


def ask_structured(prompt: str, schema: dict, model: str,
                   timeout_s: float) -> tuple[object, str | None, str]:
    """One headless claude call with schema-enforced output.

    Returns (data, exact_model, result_text):
      data         the schema-validated object, or None if the CLI did not
                   produce one (old CLI, refusal, error)
      exact_model  the exact model id(s) that served the call, from the
                   envelope's usage report (None if unavailable)
      result_text  the raw result string, kept so callers can fall back to
                   their legacy text parsing when data is None
    """
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--json-schema", json.dumps(schema)]
    if model:
        cmd += ["--model", model]
    run = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=timeout_s)
    envelope = json.loads(run.stdout)
    if not isinstance(envelope, dict):
        return None, None, ""
    exact = ", ".join((envelope.get("modelUsage") or {}).keys()) or None
    return (envelope.get("structured_output"), exact,
            envelope.get("result", "") or "")
