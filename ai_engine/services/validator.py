"""
ai_engine/services/validator.py

Basic structural validation of the LLM's normalized output before it's
trusted by the compliance engine. Kept deterministic (no LLM calls here).
"""


def validate_normalized_json(data: dict, schema: dict):
    """Returns (is_valid, list_of_error_strings)."""
    errors = []

    required_fields = ["vendor", "hostname"]
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: '{field}'")

    if "properties" in schema:
        for prop, details in schema["properties"].items():
            if details.get("required") and prop not in data:
                errors.append(f"Missing schema property: '{prop}'")

    return len(errors) == 0, errors