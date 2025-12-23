#!/bin/bash

# setup.sh - Install dependencies for ccpan (xeyes branch)
# Ubuntu only

set -e

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    tmux \
    python3 \
    python3-pip \
    python3-venv \
    x11vnc \
    xvfb \
    xauth \
    x11-apps \
    websockify \
    novnc

echo ""
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Verifying installation..."
echo -n "x11vnc: "; x11vnc -version 2>&1 | head -1 || echo "NOT FOUND"
echo -n "Xvfb: "; which Xvfb || echo "NOT FOUND"
echo -n "websockify: "; which websockify || echo "NOT FOUND"
echo -n "xeyes: "; which xeyes || echo "NOT FOUND"

echo ""
echo "Setup complete!"
echo "Run: source venv/bin/activate && python server.py"
