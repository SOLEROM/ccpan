"""
REST API routes for the Terminal Control Panel (Terminator branch).
Uses direct PTY terminals instead of tmux.
"""

import uuid
import signal
from flask import request, jsonify, render_template


def register_routes(app):
    """Register all REST API routes."""
    
    def get_managers():
        return app.config['managers']
    
    # =========================================================================
    # Pages
    # =========================================================================
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    # =========================================================================
    # Configuration API
    # =========================================================================
    
    @app.route('/api/config', methods=['GET'])
    def get_config():
        """Get current configuration."""
        mgrs = get_managers()
        return jsonify(mgrs['config'].to_dict())
    
    @app.route('/api/config', methods=['POST', 'PATCH'])
    def update_config():
        """Update configuration."""
        mgrs = get_managers()
        data = request.get_json() or {}
        
        # Update allowed fields
        allowed = ['session_prefix']
        updates = {k: v for k, v in data.items() if k in allowed}
        
        if updates:
            mgrs['config'].update(**updates)
        
        return jsonify({'status': 'ok', 'config': mgrs['config'].to_dict()})
    
    # =========================================================================
    # Sessions API (now using terminal_manager)
    # =========================================================================
    
    @app.route('/api/sessions', methods=['GET'])
    def list_sessions():
        """List all terminal sessions."""
        mgrs = get_managers()
        sessions = mgrs['terminal'].get_sessions()
        return jsonify({'sessions': sessions, 'count': len(sessions)})
    
    @app.route('/api/sessions', methods=['POST'])
    def create_session():
        """Create a new terminal session."""
        mgrs = get_managers()
        data = request.get_json() or {}
        
        name = data.get('name', f"session-{uuid.uuid4().hex[:8]}")
        
        success, result = mgrs['terminal'].create_session(
            name, 
            data.get('cwd'), 
            data.get('command')
        )
        
        if success:
            return jsonify({'status': 'ok', 'session': result})
        return jsonify({'status': 'error', 'message': result}), 400
    
    @app.route('/api/sessions/<name>', methods=['DELETE'])
    def delete_session(name):
        """Delete a terminal session."""
        mgrs = get_managers()
        
        if mgrs['terminal'].destroy_session(name):
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Failed to destroy session'}), 400
    
    @app.route('/api/sessions/<name>/command', methods=['POST'])
    def run_command(name):
        """Run a command in a session."""
        mgrs = get_managers()
        data = request.get_json() or {}
        command = data.get('command', '')
        
        if not command:
            return jsonify({'status': 'error', 'message': 'No command provided'}), 400
        
        full_name = mgrs['terminal'].get_full_name(name)
        if not mgrs['terminal'].session_exists(full_name):
            return jsonify({'status': 'error', 'message': 'Session not found'}), 404
        
        if mgrs['terminal'].send_keys(full_name, command + '\n'):
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Failed to send command'}), 400
    
    # =========================================================================
    # Commands API
    # =========================================================================
    
    @app.route('/api/commands', methods=['GET'])
    def get_all_commands():
        """Get all custom commands."""
        mgrs = get_managers()
        return jsonify(mgrs['commands'].get_all())
    
    @app.route('/api/commands/<session>', methods=['GET'])
    def get_session_commands(session):
        """Get commands for a specific session."""
        mgrs = get_managers()
        commands = mgrs['commands'].get(session)
        return jsonify({'session': session, 'commands': commands})
    
    @app.route('/api/commands/<session>', methods=['POST'])
    def add_command(session):
        """Add a command to a session."""
        mgrs = get_managers()
        data = request.get_json() or {}
        
        label = data.get('label', '')
        command = data.get('command', '')
        
        if not label or not command:
            return jsonify({'status': 'error', 'message': 'Label and command required'}), 400
        
        mgrs['commands'].add(session, label, command)
        return jsonify({'status': 'ok', 'commands': mgrs['commands'].get(session)})
    
    @app.route('/api/commands/<session>/<int:index>', methods=['DELETE'])
    def delete_command(session, index):
        """Delete a command from a session."""
        mgrs = get_managers()
        mgrs['commands'].delete(session, index)
        return jsonify({'status': 'ok', 'commands': mgrs['commands'].get(session)})
    
    # =========================================================================
    # X11 Display API
    # =========================================================================
    
    @app.route('/api/x11/displays', methods=['GET'])
    def list_displays():
        """List all X11 displays."""
        mgrs = get_managers()
        displays = mgrs['x11'].list_displays()
        return jsonify({'displays': displays, 'count': len(displays)})
    
    @app.route('/api/x11/displays', methods=['POST'])
    def create_display():
        """Create a new X11 display."""
        mgrs = get_managers()
        data = request.get_json() or {}
        
        display_num = data.get('display_num')
        width = data.get('width', 1280)
        height = data.get('height', 800)
        
        result, error = mgrs['x11'].start_display(
            display_num=display_num,
            width=width,
            height=height
        )
        
        if error:
            return jsonify({'status': 'error', 'message': error}), 400
        
        return jsonify({
            'status': 'ok',
            'display': result['display'],
            'display_num': result['display_num'],
            'ws_port': result['ws_port'],
            'vnc_port': result.get('vnc_port')
        })
    
    @app.route('/api/x11/displays/<int:display_num>', methods=['DELETE'])
    def stop_display(display_num):
        """Stop an X11 display."""
        mgrs = get_managers()
        
        if mgrs['x11'].stop_display(display_num):
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Display not found'}), 404
    
    @app.route('/api/x11/displays/<int:display_num>', methods=['GET'])
    def get_display(display_num):
        """Get info about a specific display."""
        mgrs = get_managers()
        displays = mgrs['x11'].list_displays()
        
        for d in displays:
            if d['display_num'] == display_num:
                return jsonify(d)
        
        return jsonify({'status': 'error', 'message': 'Display not found'}), 404
    
    # =========================================================================
    # Session-Display Binding API
    # =========================================================================
    
    @app.route('/api/sessions/<session>/bind-display', methods=['POST'])
    def bind_display_to_session(session):
        """Bind an X11 display to a session by setting DISPLAY env var."""
        mgrs = get_managers()
        data = request.get_json() or {}
        display_num = data.get('display_num')
        
        if display_num is None:
            return jsonify({'status': 'error', 'message': 'display_num required'}), 400
        
        full_name = mgrs['terminal'].get_full_name(session)
        
        if not mgrs['terminal'].session_exists(full_name):
            return jsonify({'status': 'error', 'message': 'Session not found'}), 404
        
        displays = mgrs['x11'].list_displays()
        display_exists = any(d['display_num'] == display_num for d in displays)
        if not display_exists:
            return jsonify({'status': 'error', 'message': 'Display not found'}), 404
        
        display_str = f":{display_num}"
        export_cmd = f"export DISPLAY={display_str}\n"
        
        if mgrs['terminal'].send_keys(full_name, export_cmd):
            return jsonify({
                'status': 'ok',
                'session': full_name,
                'display': display_str
            })
        
        return jsonify({'status': 'error', 'message': 'Failed to set DISPLAY'}), 400