# Quick Start Guide

Get the Network Security Compliance platform running in under 5 minutes.

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] Python 3.8+ installed
- [ ] PostgreSQL 18 installed and running
- [ ] Ollama installed and running
- [ ] Virtual environment created (`.venv`)

## 1-Minute Setup

### Step 1: Start Everything

**Windows (CMD):**
```cmd
start.bat
```

**Windows (PowerShell):**
```powershell
.\start.ps1
```

That's it! The script will:
1. Activate virtual environment
2. Start Django backend
3. Open frontend in your browser

## Manual Setup (5 minutes)

### Step 1: Activate Virtual Environment

**PowerShell:**
```powershell
.\.venv\Scripts\Activate.ps1
```

**CMD:**
```cmd
.venv\Scripts\activate.bat
```

### Step 2: Database Setup (First Time Only)

```bash
# Create databases in PostgreSQL
psql -U postgres -c "CREATE DATABASE Security_Compliance;"
psql -U postgres -c "CREATE DATABASE rag_chatbot;"

# Enable pgvector
psql -U postgres -d rag_chatbot -c "CREATE EXTENSION vector;"

# Run migrations
python manage.py migrate
```

### Step 3: Index RAG Knowledge Base (Optional)

```bash
cd rag
python index.py --wipe
cd ..
```

### Step 4: Start Backend

```bash
python manage.py runserver
```

Keep this terminal open!

### Step 5: Open Frontend

**Option A:** Direct file
```bash
start frontend\index.html
```

**Option B:** Test backend first
```bash
start frontend\test.html
```

## Test the System

### Quick Test

1. Open `frontend/index.html`
2. Select "Cisco" vendor
3. Click "Choose file" → select `sample_config.txt`
4. Click "Analyze Configuration"
5. View results and download PDF

### API Test

```bash
curl -X POST "http://127.0.0.1:8000/api/uploads/" ^
  -F "config=@sample_config.txt" ^
  -F "vendor=cisco"
```

## Common Issues & Fixes

### Issue: "Cannot connect to backend"

**Fix:**
```bash
# Check if Django is running
curl http://127.0.0.1:8000

# If not, start it
python manage.py runserver
```

### Issue: "Ollama connection error"

**Fix:**
```bash
# Check if Ollama is running
ollama list

# If not, start it
ollama serve

# Pull required model
ollama pull qwen2.5:3b
```

### Issue: "Database connection error"

**Fix:**
```powershell
# Check PostgreSQL status
Get-Service postgresql*

# If not running, start it
Start-Service postgresql-x64-18
```

### Issue: "CORS error in browser"

**Fix:**
1. Check `config/settings.py` has:
```python
CORS_ALLOW_ALL_ORIGINS = True
```

2. Restart Django:
```bash
python manage.py runserver
```

### Issue: "Module not found"

**Fix:**
```bash
# Install dependencies
pip install -r requirements.txt
```

## URLs & Ports

| Service | URL |
|---------|-----|
| Frontend | `file:///path/to/frontend/index.html` |
| Backend API | `http://127.0.0.1:8000` |
| Django Admin | `http://127.0.0.1:8000/admin` |
| Ollama | `http://localhost:11434` |
| PostgreSQL | `localhost:5432` |

## Sample Files

Try these included sample configurations:

1. **Cisco IOS:** `sample_config.txt`
   - Tests: SSH, NTP, SNMP, logging
   - Expected: Some failures (HTTP enabled, weak SNMP)

2. **Juniper Junos:** `sample_config_juniper.txt`
   - Tests: SSH, telnet, authentication
   - Expected: Mixed results

## Next Steps

### Explore Features

1. **Upload Multiple Configs:**
   - Upload both Cisco and Juniper files
   - Get combined PDF report

2. **Try RAG Chatbot:**
   ```bash
   cd rag
   python rag_chatbot.py
   ```
   Ask: "What is the Junos equivalent of ip ssh timeout?"

3. **Translate Configs:**
   ```bash
   cd rag
   python rag_chatbot.py "hostname Router-01
   ip ssh version 2"
   ```

### Customize

1. **Add New Rules:**
   - Edit `compliance/data/cis_rules.json`
   - Add your own compliance requirements

2. **Change Colors:**
   - Edit `frontend/style.css`
   - Modify CSS variables in `:root`

3. **Use Different LLM:**
   - Pull different Ollama model
   - Update `ai_engine/schemas/llm_instructions.json`

## Getting Help

### Check Logs

**Django:**
```bash
# In the terminal running Django, errors appear here
```

**Browser Console:**
```
F12 → Console tab
```

### Run Tests

**Backend Connection:**
```bash
start frontend\test.html
```

**Django Tests:**
```bash
python manage.py test
```

### View Database

```bash
# Connect to PostgreSQL
psql -U postgres -d Security_Compliance

# List uploads
SELECT id, vendor, status FROM core_deviceupload;
```

## Performance Tips

1. **First Upload is Slow:** LLM needs to load the model (wait ~30 seconds)
2. **Speed Up Analysis:** Use smaller Ollama model (qwen2.5:1.5b)
3. **Reduce Memory:** Close unused applications

## Architecture Overview

```
Browser (Frontend)
    ↓ HTTP
Django REST API
    ↓
AI Engine (Ollama) → Normalize Config
    ↓
Validator → Reinforce if needed
    ↓
Compliance Engine → CIS/NIST Rules
    ↓
Report Generator → JSON + PDF
```

## What's Happening Behind the Scenes?

1. **Upload:** File sent to `/api/uploads/`
2. **Normalize:** Ollama converts vendor config → JSON
3. **Validate:** Check schema compliance
4. **Reinforce:** If errors, retry with corrections
5. **Check:** Evaluate against CIS/NIST rules
6. **Report:** Generate results + PDF
7. **Display:** Show in browser

## Ready to Use!

Your platform is now ready. Upload a config file and see the magic happen! 🚀

For detailed documentation, see:
- `README.md` - Full documentation
- `frontend/README.md` - Frontend details
- `rag/` - RAG system docs
