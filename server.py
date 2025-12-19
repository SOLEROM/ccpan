#!/usr/bin/env python3
"""
Tmux Control Panel v4 - Multi-Display Terminal Manager

A web-based tmux session manager with X11 GUI display support.
Supports multiple layout configurations and configurable tmux prefixes.
"""

import os
import sys
import atexit
import warnings

# Add the script's directory to Python path for module imports
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Try to use eventlet for better WebSocket support (suppress deprecation warning)
warnings.filterwarnings('ignore', category=DeprecationWarning, module='eventlet')
try:
    import eventlet
    eventlet.monkey_patch()
    ASYNC_MODE = 'eventlet'
except ImportError:
    ASYNC_MODE = 'threading'

from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

# Import our modules
from modules.config import Config
from modules.tmux_manager import TmuxManager
from modules.pty_manager import PtyManager
from modules.x11_manager import X11Manager
from modules.commands_manager import CommandsManager
from modules.routes import register_routes
from modules.websocket_handlers import register_websocket_handlers


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    app.config['SECRET_KEY'] = os.urandom(24)
    CORS(app)
    
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode=ASYNC_MODE)
    
    # Initialize managers
    config = Config()
    tmux_mgr = TmuxManager(config)
    pty_mgr = PtyManager(tmux_mgr, socketio)
    x11_mgr = X11Manager()
    cmd_mgr = CommandsManager()
    
    # Store managers in app context
    app.config['managers'] = {
        'config': config,
        'tmux': tmux_mgr,
        'pty': pty_mgr,
        'x11': x11_mgr,
        'commands': cmd_mgr
    }
    
    # Register routes and handlers
    register_routes(app)
    register_websocket_handlers(socketio, app)
    
    # Cleanup on exit
    def cleanup():
        print("\nCleaning up...")
        x11_mgr.cleanup_all()
        pty_mgr.cleanup_all()
    
    atexit.register(cleanup)
    
    return app, socketio


def main():
    app, socketio = create_app()
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║            Tmux Control Panel v4 - Multi-Display                 ║
╠══════════════════════════════════════════════════════════════════╣
║  Features:                                                       ║
║  • Configurable tmux socket prefix per browser tab               ║
║  • Flexible layout: terminals + up to 3 GUI displays             ║
║  • Each GUI display has configurable DISPLAY number              ║
║  • Direct PTY streaming with WebSocket                           ║
║  • X11 GUI via Xvfb + x11vnc + websockify                        ║
╚══════════════════════════════════════════════════════════════════╝
""")
    
    print("Server starting on http://127.0.0.1:5000")
    socketio.run(app, host='127.0.0.1', port=5000, debug=False)


if __name__ == '__main__':
    main()