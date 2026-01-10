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
    import argparse
    
    parser = argparse.ArgumentParser(description='Tmux Control Panel v4 - Multi-Display Terminal Manager')
    parser.add_argument('--public', action='store_true', 
                        help='Make server accessible on local network (0.0.0.0). Default is localhost only.')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to run server on (default: 5000)')
    parser.add_argument('--open', action='store_true',
                        help='Open mode: shells start without requiring login (default if flag provided). '
                             'Without this flag, new shells require user login.')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging for X11/GUI terminal operations. '
                             'Useful for troubleshooting display binding issues on different hosts.')
    args = parser.parse_args()
    
    # Configure runtime settings based on arguments
    from modules.config import Config
    Config.open_mode = args.open
    Config.debug_mode = args.debug
    
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
    
    # Build mode indicator string
    shell_mode = "OPEN (no login required)" if args.open else "LOGIN (authentication required)"
    debug_status = "ENABLED" if args.debug else "disabled"
    
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
╠══════════════════════════════════════════════════════════════════╣
║  Runtime Settings:                                               ║
║  • Shell Mode: {shell_mode:<47}║
║  • Debug Mode: {debug_status:<47}║
╚══════════════════════════════════════════════════════════════════╝
""")
    
    if args.public:
        print(f"Server starting on http://{host}:{port}")
        print(f"Access from local network: http://{local_ip}:{port}")
        print(f"\n⚠️  WARNING: Server is accessible from your local network!")
    else:
        print(f"Server starting on http://{host}:{port}")
        print(f"Use --public flag to make accessible on local network")
    
    if args.debug:
        print(f"\n🔍 Debug mode enabled - X11/GUI operations will be logged to stderr")
    
    if not args.open:
        print(f"\n🔐 Login mode: New shells will require user authentication")
        print(f"   Use --open flag to disable login requirement")
    
    socketio.run(app, host=host, port=port, debug=False)


if __name__ == '__main__':
    main()