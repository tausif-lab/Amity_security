
# Network Security Compliance Automation

Analyze Cisco IOS and Juniper Junos network-device configurations against CIS and NIST-oriented rules. The application uses Ollama to normalize configurations, evaluates them with deterministic rules, produces JSON/PDF reports, and includes a RAG-assisted **bidirectional** Cisco ↔ Juniper translation service with a human-in-the-loop learning cycle.

## Translation directions

| Source | Target | Output |
|---|---|---|
| Cisco IOS | Juniper Junos | Junos `set` commands |
| Juniper Junos | Cisco IOS | Cisco IOS block configuration |

Select the direction in the frontend, or call the API:

```powershell
curl.exe -X POST "http://127.0.0.1:8001/api/translate/upload?source_vendor=juniper&target_vendor=cisco" -F "file=@sample_config_juniper.txt"
```

## Components

| Component | Purpose | Address |
|---|---|---|
| Django API | Uploads, normalization, compliance reports, remediation | `http://127.0.0.1:8000` |
| FastAPI RAG service | Translation and RAG chat endpoints | `http://127.0.0.1:8001` |
| Frontend | Browser interface | `frontend/index.html` |
| PostgreSQL with pgvector | Application data and RAG embeddings | `localhost:5432` |
| Ollama | Local language-model inference | `http://localhost:11434` |

## Prerequisites

Install the following before starting:

- Python 3.10 or later (Python 3.11 is recommended)
- PostgreSQL with the `pgvector` extension installed
- Ollama
- Git, if you are cloning the repository

Verify the command-line tools are available:

```powershell
python --version
psql --version
ollama --version
```

## Complete Windows Setup

The commands below are written for PowerShell and must be run from the project root.

### 1. Get the project

If you do not already have the project locally:

```powershell
git clone https://github.com/prinshu756/SIH26
cd Backend_copy
```

Otherwise, open PowerShell in the existing project directory.

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation for the current session, run this once and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Upgrade the package installer and install every Python dependency:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure PostgreSQL and pgvector

Start PostgreSQL, then create the Django database and enable pgvector. Replace `postgres` with your PostgreSQL superuser if necessary.

```powershell
psql -U postgres -d postgres -c "CREATE DATABASE \"Security_Compliance\";"
psql -U postgres -d Security_Compliance -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

The RAG service creates its `rag_chatbot` database, extension, table, and vector index automatically when you run its indexer. If your PostgreSQL account cannot create databases, create it manually instead:

```powershell
psql -U postgres -d postgres -c "CREATE DATABASE rag_chatbot;"
psql -U postgres -d rag_chatbot -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 4. Set database credentials

The checked-in settings currently contain local PostgreSQL connection values. Before running the application, update the password and any other connection fields in these files to match your PostgreSQL installation:

- `config/settings.py` for the Django database
- `rag/config.py` for the RAG database

The RAG service also accepts these environment variables, which can be set for the current PowerShell session:

```powershell
$env:RAG_DB_HOST = "localhost"
$env:RAG_DB_PORT = "5432"
$env:RAG_DB_USER = "postgres"
$env:RAG_DB_PASSWORD = "your_postgres_password"
$env:RAG_DB_NAME = "rag_chatbot"
```

Do not commit credentials to source control. A future deployment should move the Django database configuration out of `config/settings.py` and into environment variables.

### 5. Install and start Ollama

Install Ollama from [ollama.com](https://ollama.com), then download the model used by the Django normalizer:

```powershell
ollama pull qwen2.5:3b
```

The RAG service defaults to a different model. To use the same downloaded model for both services, set this before starting the RAG service:

```powershell
$env:OLLAMA_MODEL = "qwen2.5:3b"
```

Start Ollama if it is not already running:

```powershell
ollama serve
```

Keep this terminal open. On many Windows installations Ollama starts as a background application, in which case `ollama serve` is not needed. Confirm that the model is available:

```powershell
ollama list
```

### 6. Run Django migrations

Open a new PowerShell terminal at the project root, activate the virtual environment, and run:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py check
```

### 7. Build the RAG knowledge-base index

This is required for RAG questions and recommended before using config translation. From the project root:

```powershell
.\.venv\Scripts\Activate.ps1
Set-Location rag
python index.py --wipe
Set-Location ..
```

The first run may download the `all-MiniLM-L6-v2` embedding model if it is not already cached and may take several minutes.

### 8. Start the application services

Use separate terminals for each service. Activate `.venv` in each terminal.

Terminal 1, Django analysis API:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver 127.0.0.1:8000
```

Terminal 2, FastAPI translation/RAG API:

```powershell
.\.venv\Scripts\Activate.ps1
Set-Location rag
python main.py
```

Terminal 3 is optional if Ollama is not already running:

```powershell
ollama serve
```

### 9. Open the frontend

Open `frontend/index.html` in a browser:

```powershell
Start-Process .\frontend\index.html
```

The frontend expects Django on port 8000 and FastAPI on port 8001. You can also check the service endpoints directly:

```powershell
Invoke-WebRequest http://127.0.0.1:8001/api/health
Invoke-WebRequest http://127.0.0.1:8000/api/uploads/
```

The upload URL accepts POST requests; a GET response such as `405 Method Not Allowed` confirms that Django is reachable.

## Using the Application

### Analyze a configuration

1. Open `frontend/index.html`.
2. Select Cisco or Juniper.
3. Choose a configuration file.
4. Select **Analyze Configuration**.
5. Review the compliance findings and download the PDF report if needed.

Included test inputs:

- `sample_config.txt` for Cisco IOS
- `sample_config_juniper.txt` for Juniper Junos

The first analysis can take longer while Ollama loads the model.

### Translate between Cisco and Juniper

Start both Django and the RAG service, then use the translation section of the
frontend. Pick a **Source Vendor** and a **Target Vendor**:

- **Cisco IOS → Junos** produces Junos `set` commands.
- **Junos → Cisco IOS** produces a Cisco IOS block configuration
  (`interface ...` / indented commands, dotted subnet masks).

Translation runs through deterministic mappings, stored mappings, RAG evidence,
and an LLM fallback for lines with no verified equivalent. Lines that cannot be
translated safely (notably credentials) are emitted as `# UNMAPPED:` markers
rather than guessed, so review the generated commands before applying them to
any device.

### Use the RAG chatbot from the terminal

```powershell
Set-Location rag
python rag_chatbot.py
```

For a one-time question:

```powershell
python rag_chatbot.py "What is the Junos equivalent of ip ssh timeout?"
```

## API Examples

### Upload and analyze one configuration

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/uploads/" `
  -F "config=@sample_config.txt" `
  -F "vendor=cisco"
```

Save the returned `id` and use it in the endpoints below.

### Retrieve an upload

```powershell
curl.exe "http://127.0.0.1:8000/api/uploads/<upload_id>/"
```

### Download a combined PDF report

```powershell
curl.exe "http://127.0.0.1:8000/api/uploads/report/pdf/?ids=<upload_id>" --output report.pdf
```

### Translate through FastAPI

```powershell
curl.exe -X POST "http://127.0.0.1:8001/api/translate" `
  -H "Content-Type: application/json" `
  -d '{"source_vendor":"cisco","target_vendor":"junos","config_text":"hostname Router-01\nip ssh version 2"}'
```

## Testing

With PostgreSQL and Ollama available, run the Django tests from the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py test
```

Or run every suite in the repository (Django + bidirectional translator):

```powershell
python run_tests.py
```

## Troubleshooting

| Problem | Check or fix |
|---|---|
| `ModuleNotFoundError` | Activate `.venv`, then rerun `python -m pip install -r requirements.txt`. |
| `UndefinedValueError` on `manage.py` | Supabase settings are optional locally; `config/settings.py` supplies defaults. If you set them, add `SUPABASE_URL` / `SUPABASE_ANON_KEY` to a `.env` file. |
| Database connection failed | Confirm PostgreSQL is running, credentials match the two config files, and `Security_Compliance` exists. |
| `extension "vector" is not available` | Install pgvector for your PostgreSQL version, then rerun `CREATE EXTENSION vector;`. |
| `type "vector" does not exist` when testing | The `core.0001a_enable_pgvector` migration creates the extension. Run `python manage.py migrate`. |
| Ollama connection failed | Run `ollama serve`, confirm `ollama list` shows `qwen2.5:3b`, and verify port 11434 is free. |
| `Ollama has no model named ...` | The configured model is not pulled. Either `ollama pull <model>` or set `OLLAMA_MODEL` to an installed model. |
| Upload is slow on first run | Local CPU inference generates ~900 tokens; expect 30-90s. `OLLAMA_TIMEOUT` (default 900s) and `OLLAMA_NUM_PREDICT` tune this. |
| RAG indexer cannot create a database | Create `rag_chatbot` manually with a PostgreSQL superuser or grant `CREATEDB` to the RAG database role. |
| Translation does not work in the frontend | Ensure Django is on port 8000 and `python main.py` is running from the `rag` directory on port 8001. |
| Browser blocks a local file request | Serve `frontend` through a local web server or open the supplied `frontend/index.html`; Django and FastAPI are configured for development CORS access. |

## Project Layout

```text
ai_engine/       Ollama normalization and validation
compliance/      CIS/NIST rule data and remediation logic
config/          Django configuration
core/            Django models and API endpoints
frontend/        HTML, CSS, and JavaScript interface
rag/             RAG indexing, chat, and bidirectional Cisco <-> Juniper translation
requirements.txt Python dependencies
run_tests.py     Runs the Django and translator test suites together
```

### Translator package layout

```text
rag/translator/
  cisco_parser.py    Cisco IOS text -> Cisco AST
  juniper_parser.py   Junos `set`/`delete` text -> Junos AST
  ir.py               Cisco AST  -> DeviceIR (shared IR model)
  juniper_ir.py       Junos AST  -> DeviceIR   (same IR)
  mappings.py         DeviceIR -> Junos plan steps
  cisco_mappings.py   DeviceIR -> Cisco IOS plan steps
  generator.py        plan steps -> Junos `set` commands
  cisco_generator.py  plan steps -> Cisco IOS config
  planner.py          orchestration, memory, RAG evidence, LLM fallback
  validation.py       syntax + semantic + consistency checks
  confidence.py       per-construct and aggregate scoring
  verify.py           generate -> validate -> critique loop
```

## Security Note

This project is configured for local development. Do not expose either API directly to an untrusted network. Replace development settings, hard-coded secrets/credentials, permissive CORS, and unauthenticated API access before deploying it.
=======
# Network Security Compliance

To run the project you have to follow some steps

**AI-assisted configuration analysis, compliance reporting, and Cisco-to-Junos translation.**

Analyze network configurations against CIS and NIST rules, translate vendor syntax with a RAG pipeline, and improve future results with human-verified mappings.

Apply the migrations

</div>

Run the Django server (ai_engine + compliance, port 8000)

## What This Does

and now test the upload

```curl.exe -X POST "http://127.0.0.1:8000/api/uploads/" -F "config=@sample_config.txt" -F "vendor=cisco"```
or
```curl -X POST "http://127.0.0.1:8000/api/uploads/" -F "config=@sample_config.txt" -F "vendor=cisco"```

and you will get the response

```python view_report.py (id of the response)```

---

# RAG (bidirectional vendor translation) with normalized output

The `rag/` folder is a standalone FastAPI service (port 8001) that:

- asks for the source vendor and target vendor first (`GET /api/vendors`)
- translates **Cisco IOS -> Junos** *and* **Junos -> Cisco IOS** into the
  target platform's native syntax (deterministic pipeline + RAG evidence +
  Ollama fallback)
- writes the full RAG response to `rag\normalised_{target}.json`
- writes a copy to `ai_engine\normalised_{target}.json`
- writes the schema baseline (ai_engine format) to
  `ai_engine\normalised_{target}_baseline.json`
- writes the translated configuration to
  `ai_engine\{source}_to_{target}.txt`
- hands the translated config to Django's upload pipeline, so ai_engine LLM
  normalizes it, validates it, and runs the compliance engine

Both directions share one vendor-neutral IR, so only the parser, the mapping
catalog and the generator differ:

```text
Cisco IOS text -> cisco_parser    \
                                  ->  DeviceIR  ->  build_plan(target)  ->  generator
Junos text     -> juniper_parser  /                                  \
                                                                        v
                                                          Junos `set` commands
                                                            or Cisco IOS blocks
```

### Vendor support

| Source | Target | Output |
|---|---|---|
| `cisco` / `ios` | `junos` / `juniper` | Junos `set` commands |
| `juniper` / `junos` | `cisco` / `ios` | Cisco IOS block config |
| same vendor | same vendor | passthrough (no conversion) |

Credentials (`secret`, `password`, `key-string`, `encrypted-password`) are
**never** translated automatically, and the value is redacted from the output:
a hash from one platform silently fails to authenticate on the other. Such
lines are emitted as `# UNMAPPED:` markers for a human to recreate.

## 1. Start the RAG API

``` python rag/main.py        ```

## 2. Check everything is working

```python workflow.py --check```

This checks RAG API, Django, Ollama and Postgres/pgvector and prints the
vector store chunk count.

## 3. Run the whole workflow (one command)

```python workflow.py --config D:\Security_Compilence\sample_config.txt --source cisco --target junos```

It uploads the config to the RAG, prints the translated commands + confidence +
unresolved lines, shows where the normalized files were saved, and calls the
ai_engine upload endpoint so the compliance report is generated.

Omit flags to be prompted interactively.


Interactive chatbot:

```python rag_chatbot.py```

paste a Cisco config block -> get Junos set commands
ask a question -> retrieval + Ollama answer
:help for commands, :quit to exit
