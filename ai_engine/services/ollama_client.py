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

from .fact_extractor import PLACEHOLDERS

OLLAMA_URL = f"{settings.OLLAMA_BASE_URL}/api/generate"

# Local CPU inference is slow: qwen2.5:3b produces roughly 8-10 tokens/second,
# and a full normalized-config response is ~900 tokens, i.e. well over a minute.
# The previous fixed 120s timeout aborted valid responses mid-generation, so the
# timeout is generous and the generation length is explicitly bounded.
DEFAULT_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "900"))
# Enough for the normalized schema plus the audit block; stops runaway output.
DEFAULT_NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "1400"))
DEFAULT_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

# Dual-call confidence check (slide 3/4). Small models cannot reliably self-rate
# their own confidence, so normalization is sampled twice and only auto-accepted
# when both calls agree on the security-relevant fields. This costs a second
# inference on every cache miss, so it is switchable for live demos.
DUAL_CHECK_ENABLED = os.environ.get("OLLAMA_DUAL_CHECK", "1").lower() not in ("0", "false", "no")


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


def _build_normalize_prompt(config_text: str, instructions: dict, schema: dict,
                           memory_context: str) -> str:
    return (
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


def normalize_config(config_text: str, instructions: dict, schema: dict, memory_context: str = "") -> dict:
    """Sends raw config + schema to Ollama, returns normalized baseline JSON."""
    prompt = _build_normalize_prompt(config_text, instructions, schema, memory_context)
    return call_ollama(instructions["model"], prompt, instructions.get("temperature", 0))


# ---- dual-call agreement -------------------------------------------------------

# Only the security-relevant leaves are compared. Comparing audit metadata or
# prose would report disagreement that changes nothing, and would push every
# upload to human review for no benefit.
_AGREEMENT_KEYS = (
    "hostname", "os_version", "banners.motd", "banners.login",
    "management.ssh_version", "management.telnet_enabled",
    "management.http_enabled", "management.https_enabled",
    "management.snmp.version", "management.snmp.community_strings",
    "authentication.aaa_methods", "authentication.password_encryption",
    "logging.remote_servers", "logging.local_buffered",
    "ntp.servers", "ntp.authenticated",
    "routing.protocols", "routing.authentication.ospf", "routing.authentication.bgp",
)


def _dig(data, dotted):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if isinstance(cur, list):
        # Server/interface lists are unordered facts. Comparing them by position
        # would report a disagreement whenever the two calls happened to emit
        # the same values in a different order, sending every such upload to
        # human review for a non-issue.
        return tuple(sorted(cur, key=lambda item: str(item)))
    # Compare placeholder strings the way sanitize() will treat them downstream:
    # 'Unknown', 'unknown' and null all become None, so they are not evidence
    # of a disagreement and must not push an upload into human review.
    if isinstance(cur, str) and cur.strip().lower() in PLACEHOLDERS:
        return None
    return cur


def _normalize_call(prompt: str, instructions: dict) -> dict:
    """A second sample of the SAME prompt at a non-zero temperature.

    Reusing the identical prompt is deliberate. An earlier version used a
    shortened second prompt, which made the two calls unequal in strength rather
    than independent: the weakened call under-produced and returned None almost
    everywhere, so the check disagreed on nearly every field and flagged every
    upload for review. Sampling the same prompt twice measures real decoding
    variance, which is the thing worth checking.
    """
    return call_ollama(instructions["model"], prompt, 0.2)


def compare_agreements(first: dict, second: dict) -> list[dict]:
    """Fields where the two calls disagree. An empty list means they agree."""
    disagreements = []
    for key in _AGREEMENT_KEYS:
        a, b = _dig(first, key), _dig(second, key)
        if a != b:
            disagreements.append({"field": key, "call_a": a, "call_b": b})
    return disagreements


def normalize_config_checked(config_text: str, instructions: dict, schema: dict,
                             memory_context: str = "") -> tuple[dict, str, list]:
    """Normalize once, then confirm with a second independent call.

    Returns (baseline, status, disagreements) where status is one of:
      "agreed"  - both calls matched, auto-accepted
      "diverged" - fields differed; call A is kept and the contested fields are
                   recorded so the deterministic layer and human review can settle them
      "single"  - dual check disabled or unavailable, single call accepted
    """
    first = normalize_config(config_text, instructions, schema, memory_context)
    if not DUAL_CHECK_ENABLED:
        return first, "single", []

    try:
        second = _normalize_call(
            _build_normalize_prompt(config_text, instructions, schema, memory_context),
            instructions)
    except OllamaUnavailable:
        return first, "single", []

    if not isinstance(second, dict):
        return first, "single", []

    disagreements = compare_agreements(first, second)
    if not disagreements:
        return first, "agreed", []

    # Call A is kept. The disagreements are returned rather than injected into
    # the assessment here, because the caller knows which fields the
    # deterministic layer and the mapping database will settle on their own -
    # only the ones nothing else can resolve deserve a human.
    return first, "diverged", disagreements

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
