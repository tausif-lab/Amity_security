"""Prompt building + Ollama call for the chatbot."""

import requests

from config import OLLAMA_MODEL, OLLAMA_TEMPERATURE, OLLAMA_URL


def call_ollama(system: str, prompt: str, temperature: float = None) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "temperature": temperature if temperature is not None else OLLAMA_TEMPERATURE,
    }
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["response"].strip()


def format_evidence(results: list, limit: int = 4) -> str:
    blocks = []
    for i, r in enumerate(results[:limit], 1):
        blocks.append(f"[{i}] ({r['source']})\n{r['content'][:1200]}")
    return "\n\n".join(blocks) if blocks else "(no knowledge base match)"


def answer_prompt(question: str, evidence: list) -> str:
    return f"""Answer the network configuration question using ONLY the reference material and configuration guide provided. Include the Juniper (Junos) equivalent commands in `set` format when they exist. If the material does not say, say so.

REFERENCE MATERIAL:
{format_evidence(evidence)}

QUESTION: {question}

ANSWER:"""


def answer_system() -> str:
    return ("You are a network config assistant specializing in Cisco IOS and Juniper Junos. "
            "Give concise, accurate answers with Junos set commands whenever applicable.")


def translate_prompt(config_text: str, evidence: list, already_translated: str = "") -> str:
    verified = f"\n(These lines are already verified - keep them exactly as-is:\n{already_translated})\n" if already_translated else ""
    return f"""Convert the Cisco IOS configuration below into Juniper Junos `set` commands.
{verified}
Use the reference material shown for the correct Junos statement syntax.
Output the COMPLETE translated config (every line). For lines you cannot confidently
map, put the original line's intent as a comment starting with `# UNMAPPED:`.

REFERENCE MATERIAL (Junos syntax examples):
{format_evidence(evidence)}

CISCO CONFIG:
```
{config_text}
```

JUNOS SET COMMANDS:"""


def translate_system() -> str:
    return ("You are a Cisco-to-Juniper config translator. Output ONLY Junos set commands "
            "one per line (or `# UNMAPPED: <line>` for lines you cannot map). "
            "No explanations, no markdown, no code fences.")