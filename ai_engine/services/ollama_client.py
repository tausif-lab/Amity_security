"""
ai_engine/services/ollama_client.py

Handles all direct communication with the local Ollama server:
- normalize_config(): turns raw vendor config text into the canonical JSON schema
- reinforcement_prompt(): stricter retry prompt used when validation fails
- generate_remediation(): asks the LLM for CLI fix commands for a failed rule
"""

import json
import requests
from django.conf import settings

OLLAMA_URL = f"{settings.OLLAMA_BASE_URL}/api/generate"


def call_ollama(model: str, prompt: str, temperature: float = 0.0) -> dict:
    """Low-level call to Ollama's /api/generate with JSON-mode decoding."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "temperature": temperature,
        "format": "json",
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()

    raw = resp.json()["response"].strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return json.loads(raw.strip())


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
