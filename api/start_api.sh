#!/bin/bash

# OpenOutreach API Startup Script

echo "Starting OpenOutreach API..."
echo "================================"

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "Error: Please run this script from the api/ directory"
    exit 1
fi

# Check if dependencies are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Check if Playwright is installed
if ! python -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "Installing Playwright..."
    playwright install --with-deps chromium
fi

# Start the API
echo ""
echo "Starting API server on http://localhost:8000"
echo "Documentation available at http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop the server"
echo "================================"

# Run the API
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000