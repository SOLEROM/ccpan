#!/bin/bash
# Tmux Control Panel - Quick Setup Script for Ubuntu 22.04

set -e

echo "=========================================="
echo "  Tmux Control Panel - Setup Script"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check for root
if [ "$EUID" -eq 0 ]; then
    echo "Please do not run as root. Run as your normal user."
    exit 1
fi

# Install system dependencies
echo -e "${YELLOW}[1/5] Installing system dependencies...${NC}"
sudo apt update
sudo apt install -y tmux python3 python3-venv python3-pip

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create virtual environment
echo -e "${YELLOW}[2/5] Creating Python virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created."
else
    echo "Virtual environment already exists."
fi

# Activate and install dependencies
echo -e "${YELLOW}[3/5] Installing Python dependencies...${NC}"
source venv/bin/activate
pip install --upgrade pip
pip install flask flask-cors

# Verify installation
echo -e "${YELLOW}[4/5] Verifying installation...${NC}"
python -c "import flask; print(f'Flask version: {flask.__version__}')"
tmux -V

# Make server executable
chmod +x server.py

echo -e "${YELLOW}[5/5] Setup complete!${NC}"
echo ""
echo -e "${GREEN}=========================================="
echo "  Installation Successful!"
echo "==========================================${NC}"
echo ""
echo "To start the control panel:"
echo ""
echo "  cd $SCRIPT_DIR"
echo "  source venv/bin/activate"
echo "  python server.py"
echo ""
echo "Then open: http://127.0.0.1:5000"
echo ""
echo "To deactivate the virtual environment:"
echo "  deactivate"
echo ""
