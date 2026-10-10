"""
ai_engine/services/ollama_client.py
Handles all direct communication with the local Ollama server:
- normalize_config(): turns raw vendor config text into the canonical JSON schema
- reinforcement_prompt(): stricter retry prompt used when validation fails
- generate_remediation(): asks the LLM for CLI fix commands for a failed rule
"""

import json
import os

import requests
from django.conf import settings

OLLAMA_URL = f"{settings.OLLAMA_BASE_URL}/api/generate"

# Local CPU inference is slow: qwen2.5:3b produces roughly 8-10 tokens/second,
# and a full normalized-config response is ~900 tokens, i.e. well over a minute.
# The previous fixed 120s timeout aborted valid responses mid-generation, so the
# timeout is generous and the generation length is explicitly bounded.
DEFAULT_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "900"))
# Enough for the normalized schema plus the audit block; stops runaway output.
DEFAULT_NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "1400"))
DEFAULT_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))


class OllamaUnavailable(RuntimeError):
    """Raised when Ollama cannot serve a request at all (down, or model absent)."""


def _raise_for_ollama(resp, model: str) -> None:
    """Turn an HTTP-level failure into a message a human can act on."""
    if resp.status_code == 404:
        raise OllamaUnavailable(
            f"Ollama has no model named '{model}'. Run `ollama pull {model}`, "
            f"or set the model in ai_engine/schemas/llm_instructions.json."
        )
    resp.raise_for_status()

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _parse_json_lenient(raw: str):
    """Parse JSON, tolerating a response truncated by the token budget.

    A truncated object is repaired by closing any still-open brackets, which
    recovers every complete top-level key instead of discarding the answer.
    """
    raw = _strip_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Find the outermost object and try progressively earlier closing points.
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    last_complete = None
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                last_complete = index
    if last_complete:
        try:
            return json.loads(raw[start:last_complete + 1])
        except json.JSONDecodeError:
            pass

    # Still unbalanced: close the open containers and retry.
    closers = []
    depth = 0
    in_string = False
    escaped = False
    for char in raw[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "[":
            depth += 1
        elif char in "}]":
            depth -= 1
        elif char == "," and depth > 0:
            closers = []
    while depth > 0:
        closers.append("}" if depth > 0 else "]")
        depth -= 1
    try:
        return json.loads(raw[start:] + "".join(reversed(closers)))
    except json.JSONDecodeError:
        return None


def _looks_like_schema_echo(data) -> bool:
    """Small models sometimes copy the schema back instead of filling it in."""
    return (isinstance(data, dict)
            and "properties" in data and "$schema" in data)


def call_ollama(model: str, prompt: str, temperature: float = 0.0) -> dict:
    """Low-level call to Ollama's /api/generate with JSON-mode decoding.

    Retries once with an explicit correction nudge when the model returns
    unparseable JSON, because a single bad generation must not fail an upload.
    """
    result = _call_ollama_once(model, prompt, temperature)
    if result is not None:
        return result

    nudge = (
        f"{prompt}\n\n"
        "IMPORTANT: your previous reply was not valid JSON, or it repeated the "
        "schema definition back. Reply with ONE JSON object that FILLS IN the "
        "schema fields with values extracted from the configuration above. Do "
        "not output the schema, type keywords, or $schema. No prose, no fences."
    )
    result = _call_ollama_once(model, nudge, temperature)
    if result is None:
        raise OllamaUnavailable(
            f"Model '{model}' did not return usable JSON after a retry."
        )
    return result


def _call_ollama_once(model: str, prompt: str, temperature: float):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "temperature": temperature,
        "format": "json",
        "options": {
            "num_predict": DEFAULT_NUM_PREDICT,
            "num_ctx": DEFAULT_NUM_CTX,
        },
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.Timeout:
        return None
    except requests.RequestException as exc:
        raise OllamaUnavailable(
            f"Cannot reach Ollama at {settings.OLLAMA_BASE_URL}: {exc}. "
            f"Is `ollama serve` running?"
        ) from exc

    if resp.status_code == 404:
        raise OllamaUnavailable(
            f"Ollama has no model named '{model}'. Run `ollama pull {model}`, "
            f"or change the model in ai_engine/schemas/llm_instructions.json."
        )
    resp.raise_for_status()

    data = _parse_json_lenient(resp.json().get("response", ""))
    if data is None or _looks_like_schema_echo(data):
        return None
    return data


def normalize_config(config_text: str, instructions: dict, schema: dict, memory_context: str = "") -> dict:
    """Sends raw config + schema to Ollama, returns normalized baseline JSON."""
    prompt = (
        f"{instructions['system_prompt']}\n\n"
        f"Output schema (must match exactly):\n{json.dumps(schema, indent=2)}\n\n"
        f"Previously reviewed command memory (use approved mappings when they match; "
        f"guidance is not evidence to invent settings):\n{memory_context}\n\n"
        f"Configuration:\n```\n{config_text}\n```\n\n"
        "The following is required audit metadata and is the only allowed exception to the schema: "
        "add `_normalization_assessment`, an array with one object for every command "
        "you could not map with high confidence: {command, proposed_meaning, confidence}. "
        "confidence is a number from 0 to 1. Do not include commands that are certain. "
        "Output ONLY valid JSON."
        "\n\nCRITICAL: Reply with ONE JSON object that FILLS IN the schema fields with "
        "values read from the configuration. Do NOT repeat the schema definition, do NOT "
        "output \"$schema\", \"type\", or \"properties\" keys, and do NOT add commentary."
    )
    return call_ollama(instructions["model"], prompt, instructions.get("temperature", 0))

def reinforcement_prompt(config_text: str, errors: list, instructions: dict, schema: dict) -> dict:
    """Stricter corrective retry when normalize_config() output fails validation."""
    prompt = f"""
You are given a set of rules for parsing configuration input.
You MUST follow these rules exactly and in order. If the rules are not followed,
the output will be rejected.

ERRORS FOUND IN YOUR PREVIOUS OUTPUT:
{json.dumps(errors, indent=2)}

You MUST output a corrected JSON that strictly matches this schema:
{json.dumps(schema, indent=2)}

Raw configuration to re-parse:
{config_text}

Output ONLY valid JSON. No other text. Fix ALL errors listed above.
Reply with ONE JSON object that FILLS IN the schema fields. Do not output the
schema definition itself, and do not use "type"/"properties"/"$schema" keys.
"""
    return call_ollama(instructions["model"], prompt, instructions.get("temperature", 0))

def generate_remediation(vendor: str, os_version: str, failed_rule: dict, instructions: dict) -> list:
    """Asks the LLM for exact CLI commands to fix one failed compliance rule."""
    prompt = f"""
Vendor: {vendor}
OS Version: {os_version}
Failed Rule: {failed_rule['rule_id']} - {failed_rule['name']}
Severity: {failed_rule['severity']}
Expected: {failed_rule['field']} should be {failed_rule['expected']} (Operator: {failed_rule['operator']})
Current value: {failed_rule.get('actual', 'Not found')}

Generate the EXACT CLI commands to fix this issue on a {vendor} device.
Return only JSON with a "commands" array (list of strings).
"""
    result = call_ollama(instructions["model"], prompt, 0)
    return result.get("commands", [])
