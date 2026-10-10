# Launch Checklist

Use this checklist to verify your Network Security Compliance platform is ready to use.

## Pre-Launch Checks

### ✅ Environment Setup

- [ ] Python 3.8+ installed
  ```bash
  python --version
  ```

- [ ] Virtual environment exists
  ```bash
  dir .venv
  ```

- [ ] PostgreSQL 18 running
  ```bash
  Get-Service postgresql*
  ```

- [ ] Ollama installed and running
  ```bash
  ollama list
  ```

### ✅ Database Configuration

- [ ] Security_Compliance database exists
  ```bash
  psql -U postgres -l | findstr Security_Compliance
  ```

- [ ] rag_chatbot database exists
  ```bash
  psql -U postgres -l | findstr rag_chatbot
  ```

- [ ] pgvector extension enabled
  ```bash
  psql -U postgres -d rag_chatbot -c "\dx vector"
  ```

### ✅ Dependencies Installed

- [ ] Django installed
  ```bash
  python -c "import django; print(django.get_version())"
  ```

- [ ] Django REST Framework installed
  ```bash
  python -c "import rest_framework; print('OK')"
  ```

- [ ] ReportLab installed (for PDF)
  ```bash
  python -c "import reportlab; print('OK')"
  ```

- [ ] psycopg2 installed
  ```bash
  python -c "import psycopg2; print('OK')"
  ```

- [ ] sentence-transformers installed
  ```bash
  python -c "import sentence_transformers; print('OK')"
  ```

### ✅ Ollama Model

- [ ] Model downloaded
  ```bash
  ollama list
  # Should show: qwen2.5:3b or similar
  ```

- [ ] Model responds
  ```bash
  ollama run qwen2.5:3b "test"
  ```

## Backend Launch

### ✅ Migrations

- [ ] Migrations applied
  ```bash
  python manage.py migrate
  ```

- [ ] No pending migrations
  ```bash
  python manage.py showmigrations
  # All should have [X]
  ```

### ✅ Django Server

- [ ] Server starts without errors
  ```bash
  python manage.py runserver
  ```

- [ ] Server accessible
  ```bash
  curl http://127.0.0.1:8000
  # Should not error
  ```

- [ ] API endpoint responds
  ```bash
  curl http://127.0.0.1:8000/api/uploads/
  # Should return 405 Method Not Allowed (expected)
  ```

### ✅ CORS Configuration

- [ ] CORS middleware in MIDDLEWARE list
  - Open `config/settings.py`
  - Verify `'corsheaders.middleware.CorsMiddleware'` is present

- [ ] CORS_ALLOW_ALL_ORIGINS set to True
  - Check `config/settings.py`
  - Should have `CORS_ALLOW_ALL_ORIGINS = True`

## Frontend Launch

### ✅ Files Exist

- [ ] index.html exists
  ```bash
  dir frontend\index.html
  ```

- [ ] style.css exists
  ```bash
  dir frontend\style.css
  ```

- [ ] script.js exists
  ```bash
  dir frontend\script.js
  ```

- [ ] test.html exists
  ```bash
  dir frontend\test.html
  ```

### ✅ Configuration

- [ ] API_BASE_URL correct in script.js
  - Open `frontend/script.js`
  - Should be: `const API_BASE_URL = 'http://127.0.0.1:8000/api';`

### ✅ Browser Test

- [ ] Frontend opens in browser
  ```bash
  start frontend\index.html
  ```

- [ ] No console errors (F12)
  - Press F12 in browser
  - Check Console tab
  - Should be clean

- [ ] Test page works
  ```bash
  start frontend\test.html
  ```

- [ ] Backend connection succeeds
  - Test page should show "✅ Backend is running"

## Functional Tests

### ✅ Upload Flow (Cisco)

- [ ] Select "Cisco" vendor
- [ ] Choose `sample_config.txt`
- [ ] Click "Analyze Configuration"
- [ ] Status shows "Analyzing configuration..."
- [ ] Results appear after ~30 seconds
- [ ] Summary shows numbers (8 total, 4 passed, 3 failed)
- [ ] Baseline data displays
- [ ] Compliance rules show with colors
- [ ] PDF download button appears

### ✅ Upload Flow (Juniper)

- [ ] Select "Juniper" vendor
- [ ] Choose `sample_config_juniper.txt`
- [ ] Click "Analyze Configuration"
- [ ] Results appear
- [ ] Summary displays correctly

### ✅ PDF Download

- [ ] Click "Download PDF" button
- [ ] Status shows "Generating PDF..."
- [ ] PDF file downloads
- [ ] Filename is `compliance-report-{id}.pdf`
- [ ] PDF opens and displays correctly
- [ ] Contains all compliance data

### ✅ Error Handling

- [ ] Upload without selecting vendor → Error message
- [ ] Upload without file → Error message
- [ ] Upload empty file → Error message
- [ ] Backend down → Clear error message

## API Tests

### ✅ Direct API Testing

- [ ] Test upload via curl
  ```bash
  curl -X POST "http://127.0.0.1:8000/api/uploads/" ^
    -F "config=@sample_config.txt" ^
    -F "vendor=cisco"
  ```
  - Should return JSON with status "done" or "review"

- [ ] Test retrieve upload
  ```bash
  curl "http://127.0.0.1:8000/api/uploads/{id}/"
  ```
  - Replace {id} with actual upload ID
  - Should return full report JSON

- [ ] Test PDF download
  ```bash
  curl -X GET "http://127.0.0.1:8000/api/uploads/report/pdf/?ids={id}" ^
    --output test-report.pdf
  ```
  - Should create test-report.pdf file

### ✅ View Report Script

- [ ] Test view_report.py
  ```bash
  python view_report.py {upload_id}
  ```
  - Should display formatted report in terminal

## RAG System Tests (Optional)

### ✅ Knowledge Base

- [ ] Index knowledge base
  ```bash
  cd rag
  python index.py --wipe
  ```
  - Should index PDF/DOCX files
  - Should show chunk counts

### ✅ RAG Chatbot

- [ ] Interactive mode works
  ```bash
  cd rag
  python rag_chatbot.py
  ```
  - Type: "what is ssh timeout?"
  - Should return answer with sources

- [ ] One-shot query works
  ```bash
  cd rag
  python rag_chatbot.py "Junos ssh version"
  ```
  - Should return relevant answer

- [ ] Config translation works
  ```bash
  cd rag
  python rag_chatbot.py "hostname Router-01
  ip ssh version 2"
  ```
  - Should return Junos set commands

## Performance Checks

### ✅ Response Times

- [ ] Upload completes in < 60 seconds (first time)
- [ ] Upload completes in < 30 seconds (subsequent)
- [ ] Results display in < 1 second
- [ ] PDF generates in < 5 seconds

### ✅ Resource Usage

- [ ] Django process < 500MB RAM
- [ ] Ollama process < 4GB RAM
- [ ] PostgreSQL < 1GB RAM
- [ ] Browser tab < 200MB RAM

## Browser Compatibility

Test in each browser:

- [ ] Chrome
  - Upload works
  - Results display correctly
  - PDF downloads

- [ ] Firefox
  - Upload works
  - Results display correctly
  - PDF downloads

- [ ] Edge
  - Upload works
  - Results display correctly
  - PDF downloads

## Startup Scripts

### ✅ Batch Script

- [ ] start.bat runs without errors
  ```bash
  start.bat
  ```
  - Django starts in new window
  - Frontend opens in browser

### ✅ PowerShell Script

- [ ] start.ps1 runs without errors
  ```powershell
  .\start.ps1
  ```
  - Shows status messages
  - Opens frontend

## Documentation

### ✅ Files Complete

- [ ] README.md updated with frontend info
- [ ] QUICKSTART.md provides 5-min setup
- [ ] frontend/README.md explains setup
- [ ] frontend/DESIGN.md documents design
- [ ] IMPLEMENTATION_SUMMARY.md complete
- [ ] LAUNCH_CHECKLIST.md (this file) complete

## Final Verification

### ✅ End-to-End Test

Complete workflow from start to finish:

1. [ ] Run startup script
2. [ ] Open frontend
3. [ ] Upload Cisco config
4. [ ] View results
5. [ ] Download PDF
6. [ ] Upload Juniper config
7. [ ] View results
8. [ ] Download combined PDF (both uploads)
9. [ ] Verify all data correct

### ✅ Clean Shutdown

- [ ] Stop Django (Ctrl+C)
- [ ] Close browser
- [ ] Stop Ollama if needed
- [ ] No error messages

## Troubleshooting Reference

### Problem: Backend won't start

**Solution:**
```bash
# Check if port 8000 is in use
netstat -ano | findstr :8000

# Kill process if needed
taskkill /PID {pid} /F

# Restart
python manage.py runserver
```

### Problem: Frontend can't connect

**Solution:**
1. Check CORS in settings.py
2. Verify API_BASE_URL in script.js
3. Test with test.html
4. Check browser console for errors

### Problem: Ollama timeout

**Solution:**
```bash
# Restart Ollama
ollama serve

# Test model
ollama run qwen2.5:3b "test"

# Check model list
ollama list
```

### Problem: PDF generation fails

**Solution:**
```bash
# Install reportlab
pip install reportlab

# Check imports in views.py
python -c "from reportlab.lib.pagesizes import letter"
```

## Success Criteria

✅ **All checks passed** = Ready for production use!

If any check fails:
1. Review error messages
2. Consult QUICKSTART.md
3. Check relevant documentation
4. Run test.html for diagnostics

## Next Steps After Launch

- [ ] Test with real configuration files
- [ ] Customize compliance rules
- [ ] Add additional frameworks (if needed)
- [ ] Integrate with CI/CD (optional)
- [ ] Set up backups (database)
- [ ] Monitor performance
- [ ] Collect user feedback

## Support

If issues persist:
1. Check `QUICKSTART.md` troubleshooting section
2. Review Django logs in terminal
3. Check browser console (F12)
4. Run `frontend/test.html` diagnostics
5. Verify all prerequisites installed

---

**Launch Date:** _______________

**Tested By:** _______________

**Status:** ⬜ Ready  ⬜ Needs Work

**Notes:**
_______________________________________
_______________________________________
_______________________________________
