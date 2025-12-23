#!/usr/bin/env python3
"""
Terminal Control Panel - Terminator Branch

A web-based terminal manager with X11 GUI display support.
Uses direct PTY terminals instead of tmux for ephemeral sessions.

Terminals are NOT persistent - they are destroyed when the server stops.
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
from modules.terminal_manager import TerminalManager
from modules.x11_manager import X11Manager
from modules.commands_manager import CommandsManager
from modules.routes import register_routes
from modules.websocket_handlers import register_websocket_handlers


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.urandom(24)
    
    CORS(app)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode=ASYNC_MODE)
    
    # Initialize managers
    config = Config()
    managers = {
        'config': config,
        'terminal': TerminalManager(config),
        'x11': X11Manager(),
        'commands': CommandsManager()
    }
    
    app.config['managers'] = managers
    
    # Register routes and handlers
    register_routes(app)
    register_websocket_handlers(socketio, managers)
    
    # Cleanup on exit
    def cleanup():
        print("\nCleaning up...")
        managers['terminal'].cleanup_all()
        managers['x11'].cleanup_all()
        print("Cleanup complete.")
    
    atexit.register(cleanup)
    
    return app, socketio


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Terminal Control Panel (Terminator) - Ephemeral Terminal Manager')
    parser.add_argument('--public', action='store_true', 
                        help='Make server accessible on local network (0.0.0.0). Default is localhost only.')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to run server on (default: 5000)')
    args = parser.parse_args()
    
    host = '0.0.0.0' if args.public else '127.0.0.1'
    port = args.port
    
    app, socketio = create_app()
    
    # Get local IP for display if public
    local_ip = ''
    if args.public:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = 'your-local-ip'
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║       Terminal Control Panel - TERMINATOR Branch                 ║
╠══════════════════════════════════════════════════════════════════╣
║  Mode: Direct PTY (no tmux)                                      ║
║  Sessions: Ephemeral - destroyed on server stop                  ║
╠══════════════════════════════════════════════════════════════════╣
║  Features:                                                       ║
║  • Fresh shell sessions with no history                          ║
║  • Flexible layout: terminals + up to 3 GUI displays             ║
║  • Each GUI display has configurable DISPLAY number              ║
║  • Direct PTY streaming with WebSocket                           ║
║  • X11 GUI via Xvfb + x11vnc + websockify                        ║
╚══════════════════════════════════════════════════════════════════╝
""")
    
    if args.public:
        print(f"Server starting on http://{host}:{port}")
        print(f"Access from local network: http://{local_ip}:{port}")
        print(f"\n⚠️  WARNING: Server is accessible from your local network!")
    else:
        print(f"Server starting on http://{host}:{port}")
        print(f"Use --public flag to make accessible on local network")
    
    print("\n⚠️  NOTE: Sessions will be destroyed when server stops!\n")
    
    socketio.run(app, host=host, port=port, debug=False)


if __name__ == '__main__':
    main()