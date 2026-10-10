# Network Security Compliance - Frontend

A minimal, clean frontend interface for the Network Security Compliance automation platform.

## Features

- **Hero Section**: Product description with upload form
- **Vendor Selection**: Choose between Cisco and Juniper devices
- **File Upload**: Simple drag-and-drop or browse interface
- **Real-time Analysis**: Live status updates during processing
- **Results Display**: Clean presentation of compliance reports
- **PDF Export**: Download comprehensive compliance reports

## Setup

### 1. Ensure Backend is Running

```bash
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run Django server
python manage.py runserver
```

The backend should be running at `http://127.0.0.1:8000`

### 2. Open Frontend

Simply open `index.html` in your browser:

```bash
# Using default browser
start index.html

# Or using a specific browser
chrome.exe index.html
firefox.exe index.html
```

Alternatively, you can use a simple HTTP server:

```bash
# Python 3
python -m http.server 8080

# Then open http://localhost:8080 in your browser
```

## Usage

1. **Select Vendor**: Choose either Cisco or Juniper from the dropdown
2. **Upload File**: Click "Choose file" and select your configuration file (`.txt`, `.conf`, or `.cfg`)
3. **Analyze**: Click "Analyze Configuration" button
4. **View Results**: Scroll down to see the compliance report
5. **Download PDF**: Click "Download PDF" to save the report

## File Structure

```
frontend/
├── index.html      # Main HTML structure
├── style.css       # Minimal, clean styling
├── script.js       # Frontend logic and API integration
└── README.md       # This file
```

## API Integration

The frontend connects to these backend endpoints:

- `POST /api/uploads/` - Upload and analyze configuration
- `GET /api/uploads/{id}/` - Retrieve analysis results
- `GET /api/uploads/report/pdf/?ids={id}` - Download PDF report

## Browser Support

- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## Design Philosophy

**Minimal. Clean. Functional.**

- No heavy frameworks (React, Vue, Angular)
- No build process required
- No dependencies to install
- Pure HTML, CSS, and vanilla JavaScript
- Light theme with proper contrast
- Responsive design for all screen sizes

## Customization

### Colors

Edit `style.css` and modify the CSS variables in `:root`:

```css
:root {
    --bg-primary: #fafafa;
    --bg-secondary: #ffffff;
    --text-primary: #1a1a1a;
    --accent-color: #2c3e50;
    /* ... */
}
```

### API URL

Edit `script.js` and modify the base URL:

```javascript
const API_BASE_URL = 'http://127.0.0.1:8000/api';
```

## Troubleshooting

### CORS Issues

If you see CORS errors in the browser console, ensure `CORS_ALLOWED_ORIGINS` in `config/settings.py` includes your frontend URL:

```python
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
```

### Backend Not Responding

1. Check Django server is running: `python manage.py runserver`
2. Verify Ollama is running: `ollama list`
3. Check PostgreSQL is running and databases exist

### PDF Download Issues

Ensure `reportlab` is installed:

```bash
pip install reportlab
```

## Sample Files

Test the interface with sample configuration files:

- `sample_config.txt` - Cisco IOS configuration
- `sample_config_juniper.txt` - Juniper configuration

## License

Part of the Security Compliance project.
