"""
WebSocket event handlers for the Tmux Control Panel.
"""

import signal
from flask import request
from flask_socketio import emit, join_room, leave_room


def register_websocket_handlers(socketio, app):
    """Register all WebSocket event handlers."""
    
    def get_managers():
        return app.config['managers']
    
    @socketio.on('connect')
    def handle_connect():
        emit('connected', {'status': 'ok'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        mgrs = get_managers()
        for session_name in list(mgrs['pty'].connections.keys()):
            mgrs['pty'].remove_client(session_name, request.sid)
    
    @socketio.on('subscribe')
    def handle_subscribe(data):
        """Subscribe to a session's output."""
        mgrs = get_managers()
        session_name = data.get('session')
        cols = data.get('cols', 120)
        rows = data.get('rows', 40)
        socket = data.get('socket')
        
        if not session_name:
            emit('error', {'message': 'No session specified'})
            return
        
        full_name = mgrs['tmux'].get_full_name(session_name)
        
        if not mgrs['tmux'].session_exists(full_name, socket=socket):
            emit('error', {'message': f'Session {full_name} does not exist'})
            return
        
        # Resize before connecting
        mgrs['pty'].resize(full_name, cols, rows, socket=socket)
        
        join_room(full_name)
        conn = mgrs['pty'].get_or_create(full_name, request.sid, cols, rows, socket=socket)
        
        if not conn:
            emit('error', {'message': f'Failed to connect to session {full_name}'})
            return
        
        # Resize again after PTY is connected
        mgrs['pty'].resize(full_name, cols, rows, socket=socket)
        
        emit('subscribed', {'session': full_name})
    
    @socketio.on('unsubscribe')
    def handle_unsubscribe(data):
        """Unsubscribe from a session."""
        mgrs = get_managers()
        session_name = data.get('session')
        
        if not session_name:
            return
        
        full_name = mgrs['tmux'].get_full_name(session_name)
        leave_room(full_name)
        mgrs['pty'].remove_client(full_name, request.sid)
        emit('unsubscribed', {'session': full_name})
    
    @socketio.on('input')
    def handle_input(data):
        """Handle keyboard input."""
        mgrs = get_managers()
        session_name = data.get('session')
        keys = data.get('keys', '')
        
        if session_name and keys:
            full_name = mgrs['tmux'].get_full_name(session_name)
            mgrs['pty'].send_keys(full_name, keys)
    
    @socketio.on('resize')
    def handle_resize(data):
        """Handle terminal resize."""
        mgrs = get_managers()
        session_name = data.get('session')
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        socket = data.get('socket')
        
        if session_name:
            full_name = mgrs['tmux'].get_full_name(session_name)
            mgrs['pty'].resize(full_name, cols, rows, socket=socket)
    
    @socketio.on('signal')
    def handle_signal(data):
        """Send a signal to the foreground process."""
        mgrs = get_managers()
        session_name = data.get('session')
        sig_name = data.get('signal', 'SIGINT')
        socket = data.get('socket')
        
        if not session_name:
            return
        
        full_name = mgrs['tmux'].get_full_name(session_name)
        sig_map = {
            'SIGINT': signal.SIGINT,
            'SIGTERM': signal.SIGTERM,
            'SIGKILL': signal.SIGKILL,
            'SIGSTOP': signal.SIGSTOP,
            'SIGCONT': signal.SIGCONT,
            'SIGTSTP': signal.SIGTSTP,
        }
        mgrs['tmux'].send_signal(full_name, sig_map.get(sig_name, signal.SIGINT), socket=socket)
    
    @socketio.on('scroll')
    def handle_scroll(data):
        """Handle scroll in copy-mode."""
        mgrs = get_managers()
        session_name = data.get('session')
        command = data.get('command', '')
        lines = data.get('lines', 1)
        socket = data.get('socket')
        
        if not session_name:
            return
        
        full_name = mgrs['tmux'].get_full_name(session_name)
        
        if command == 'enter':
            mgrs['tmux'].enter_copy_mode(full_name, socket=socket)
        elif command == 'exit':
            mgrs['tmux'].scroll(full_name, 'exit', socket=socket)
        elif command in ['up', 'down', 'page_up', 'page_down', 'top', 'bottom']:
            mgrs['tmux'].scroll(full_name, command, lines, socket=socket)
    
    @socketio.on('get_scrollback')
    def handle_get_scrollback(data):
        """Get scrollback content from tmux."""
        mgrs = get_managers()
        session_name = data.get('session')
        start_line = data.get('start_line', -1000)
        end_line = data.get('end_line', None)
        socket = data.get('socket')
        
        if not session_name:
            emit('error', {'message': 'No session specified'})
            return
        
        full_name = mgrs['tmux'].get_full_name(session_name)
        
        content = mgrs['tmux'].get_scrollback(full_name, start_line, end_line, socket=socket)
        history_size = mgrs['tmux'].get_history_size(full_name, socket=socket)
        
        emit('scrollback', {
            'session': full_name,
            'content': content,
            'history_size': history_size,
            'start_line': start_line
        })
