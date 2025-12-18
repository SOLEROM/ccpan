#!/bin/bash
# Setup script for Tmux Control Panel v3

set -e

echo "🖥️  Setting up Tmux Control Panel v3..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Check for tmux
if ! command -v tmux &> /dev/null; then
    echo "❌ tmux is required but not installed."
    echo "   Install with: sudo apt install tmux"
    exit 1
fi

# Check for X11 dependencies (optional)
echo ""
echo "Checking X11 dependencies for GUI app support..."
MISSING=""
if ! command -v Xvfb &> /dev/null; then
    MISSING="$MISSING xvfb"
fi
if ! command -v x11vnc &> /dev/null; then
    MISSING="$MISSING x11vnc"
fi
if ! command -v websockify &> /dev/null; then
    MISSING="$MISSING websockify"
fi

if [ -n "$MISSING" ]; then
    echo "⚠️  Optional X11 dependencies missing:$MISSING"
    echo "   Install with: sudo apt install$MISSING novnc"
    echo "   (GUI app features will be disabled without these)"
else
    echo "✅ X11 dependencies found"
fi

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate and install dependencies
echo "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  python server_pty.py"
echo ""
echo "Then open http://127.0.0.1:5000 in your browser"