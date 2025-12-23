"""
WebSocket handlers for real-time terminal I/O (Terminator branch).
Uses direct PTY terminals instead of tmux.
"""

from flask_socketio import emit


def register_websocket_handlers(socketio, managers):
    """Register all WebSocket event handlers."""
    
    terminal_mgr = managers['terminal']
    
    # Track subscriptions per client
    client_sessions = {}  # sid -> session_name
    
    def output_callback(session, data):
        """Called when terminal produces output."""
        socketio.emit('output', {
            'session': session,
            'data': data.decode('utf-8', errors='replace')
        })
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        print(f"Client connected: {request.sid if hasattr(request, 'sid') else 'unknown'}")
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        sid = getattr(request, 'sid', None)
        if sid and sid in client_sessions:
            session = client_sessions.pop(sid)
            print(f"Client {sid} disconnected from session {session}")
    
    @socketio.on('subscribe')
    def handle_subscribe(data):
        """Subscribe to a terminal session's output."""
        session = data.get('session')
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        
        if not session:
            emit('error', {'message': 'No session specified'})
            return
        
        # Check if session exists
        if not terminal_mgr.session_exists(session):
            emit('error', {'message': f'Session {session} not found'})
            return
        
        # Track this client's subscription
        sid = getattr(request, 'sid', None)
        if sid:
            client_sessions[sid] = session
        
        # Resize terminal
        terminal_mgr.resize_window(session, cols, rows)
        
        # Start reader for this session
        terminal_mgr.start_reader(session, output_callback)
        
        emit('subscribed', {'session': session})
        print(f"Client subscribed to session: {session}")
    
    @socketio.on('unsubscribe')
    def handle_unsubscribe(data):
        """Unsubscribe from a terminal session."""
        session = data.get('session')
        sid = getattr(request, 'sid', None)
        
        if sid and sid in client_sessions:
            del client_sessions[sid]
        
        print(f"Client unsubscribed from session: {session}")
    
    @socketio.on('input')
    def handle_input(data):
        """Handle terminal input from client."""
        session = data.get('session')
        keys = data.get('keys', '')
        
        if not session or not keys:
            return
        
        if not terminal_mgr.session_exists(session):
            emit('error', {'message': f'Session {session} not found'})
            return
        
        terminal_mgr.send_keys(session, keys)
    
    @socketio.on('resize')
    def handle_resize(data):
        """Handle terminal resize."""
        session = data.get('session')
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        
        if not session:
            return
        
        if terminal_mgr.session_exists(session):
            terminal_mgr.resize_window(session, cols, rows)
    
    @socketio.on('signal')
    def handle_signal(data):
        """Send a signal to the terminal process."""
        session = data.get('session')
        sig = data.get('signal', 'INT')
        
        if not session:
            return
        
        if terminal_mgr.session_exists(session):
            terminal_mgr.send_signal(session, sig)
    
    # Note: scroll events are not supported in terminator mode
    # since we don't have tmux's copy-mode. Scrollback is handled
    # by xterm.js on the client side.
    @socketio.on('scroll')
    def handle_scroll(data):
        """Handle scroll request - not supported in terminator mode."""
        # In terminator mode, scrollback is handled by xterm.js
        # We could implement a scrollback buffer if needed
        pass


# Need to import request for sid access
from flask import request