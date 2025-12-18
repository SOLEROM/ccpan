#!/bin/bash
# Tmux Control Panel v2 - Setup Script

set -e

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║              Tmux Control Panel v2 - Setup                       ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Check for tmux
if ! command -v tmux &> /dev/null; then
    echo "❌ tmux is not installed. Installing..."
    sudo apt update && sudo apt install -y tmux
else
    echo "✅ tmux is installed"
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install it first."
    exit 1
else
    echo "✅ Python 3 is installed"
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
else
    echo "✅ Virtual environment exists"
fi

# Activate and install dependencies
echo "📦 Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                     Setup Complete!                              ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║  To start the server:                                            ║"
echo "║    source venv/bin/activate                                      ║"
echo "║    python server.py                                              ║"
echo "║                                                                  ║"
echo "║  Then open: http://127.0.0.1:5000                                ║"
echo "╚══════════════════════════════════════════════════════════════════╝"