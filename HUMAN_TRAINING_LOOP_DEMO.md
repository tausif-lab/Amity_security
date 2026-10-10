# Human training-loop demo

This demo makes the learning loop observable without changing a real device configuration. It intentionally has exactly one non-standard `demo-policy` command. On the first upload, the report has one `Unknown` entry and one human-intervention item.

After a reviewer approves the one mapping below, the command embedding is stored in `core_normalizationmemory`. Uploading the same file again finds the approved vector before the LLM is asked to normalize. The saved mapping is applied deterministically, so all eight included CIS checks pass.

## Setup

Use Windows PowerShell from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
ollama pull qwen2.5:3b
python manage.py runserver
```

PostgreSQL must be running and the `Security_Compliance` database must exist with the pgvector extension:

```powershell
psql -U postgres -d Security_Compliance -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## First upload

In a second PowerShell window, upload the demo file:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/uploads/ -F "config=@demo_human_training_loop.txt" -F "vendor=cisco"
```

Read the returned `normalization_review` list and use its `memory_id` values. If the selected Ollama model does not emit an assessment for a `demo-policy` command, create its review record through Django admin first; the prompt requests these assessments, but an LLM cannot be made perfectly deterministic.

## Human approval

Approve the one pending review. Replace `<id>` with its `memory_id`.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/normalization-reviews/<id>/ -H "Content-Type: application/json" -d '{"decision":"approve","normalized_path":"management.ssh_version","normalized_value":2}'
```

In the frontend field, enter exactly:

```text
management.ssh_version = 2
```

## Second upload: learned result

Upload exactly the same file again. The response includes `memory_matches` with approved semantic matches and the report summary should show `passed: 8`, `failed: 0`, `unknown: 0`.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/uploads/ -F "config=@demo_human_training_loop.txt" -F "vendor=cisco"
```
