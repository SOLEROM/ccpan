"""
REST API routes for the Tmux Control Panel.

Fixed Display Configuration:
  Panel 0 (GUI 1): Display :100
  Panel 1 (GUI 2): Display :101
  Panel 2 (GUI 3): Display :102
"""

import uuid
import signal
from flask import request, jsonify, render_template


def register_routes(app):
    """Register all REST API routes."""
    
    def get_managers():
        return app.config['managers']
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/api/config', methods=['GET'])
    def get_config():
        mgrs = get_managers()
        return jsonify(mgrs['config'].to_dict())
    
    @app.route('/api/config', methods=['POST', 'PATCH'])
    def update_config():
        mgrs = get_managers()
        data = request.get_json() or {}
        allowed = ['tmux_socket', 'session_prefix']
        updates = {k: v for k, v in data.items() if k in allowed}
        if updates:
            mgrs['config'].update(**updates)
        return jsonify({'status': 'ok', 'config': mgrs['config'].to_dict()})
    
    @app.route('/api/sessions', methods=['GET'])
    def list_sessions():
        mgrs = get_managers()
        socket = request.args.get('socket')
        sessions = mgrs['tmux'].get_sessions(socket=socket)
        return jsonify({'sessions': sessions, 'count': len(sessions)})
    
    @app.route('/api/sessions', methods=['POST'])
    def create_session():
        mgrs = get_managers()
        data = request.get_json() or {}
        name = data.get('name', f"session-{uuid.uuid4().hex[:8]}")
        socket = data.get('socket')
        success, result = mgrs['tmux'].create_session(name, data.get('cwd'), data.get('command'), socket=socket)
        if success:
            return jsonify({'status': 'ok', 'session': result})
        return jsonify({'status': 'error', 'message': result}), 400
    
    @app.route('/api/sessions/<name>', methods=['DELETE'])
    def delete_session(name):
        mgrs = get_managers()
        socket = request.args.get('socket')
        mgrs['pty'].cleanup(name)
        if mgrs['tmux'].destroy_session(name, socket=socket):
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Failed to destroy session'}), 400
    
    @app.route('/api/sessions/<name>/command', methods=['POST'])
    def run_command(name):
        mgrs = get_managers()
        data = request.get_json() or {}
        command = data.get('command', '')
        socket = data.get('socket')
        if not command:
            return jsonify({'status': 'error', 'message': 'No command provided'}), 400
        full_name = mgrs['tmux'].get_full_name(name)
        if not mgrs['tmux'].session_exists(full_name, socket=socket):
            return jsonify({'status': 'error', 'message': 'Session not found'}), 404
        if mgrs['pty'].send_keys(full_name, command + '\n'):
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Failed to send command'}), 400
    
    @app.route('/api/commands', methods=['GET'])
    def get_all_commands():
        mgrs = get_managers()
        return jsonify(mgrs['commands'].get_all())
    
    @app.route('/api/commands/<session>', methods=['GET'])
    def get_session_commands(session):
        mgrs = get_managers()
        return jsonify(mgrs['commands'].get(session))
    
    @app.route('/api/commands/<session>', methods=['POST'])
    def add_command(session):
        mgrs = get_managers()
        data = request.get_json() or {}
        if not data.get('command'):
            return jsonify({'status': 'error', 'message': 'No command provided'}), 400
        commands = mgrs['commands'].add(session, data.get('label', 'Command'), data['command'])
        return jsonify({'status': 'ok', 'commands': commands})
    
    @app.route('/api/commands/<session>/<int:index>', methods=['DELETE'])
    def delete_command(session, index):
        mgrs = get_managers()
        commands = mgrs['commands'].delete(session, index)
        if commands is None:
            return jsonify({'status': 'error', 'message': 'Command not found'}), 404
        return jsonify({'status': 'ok', 'commands': commands})
    
    @app.route('/api/x11/check', methods=['GET'])
    def check_x11_deps():
        mgrs = get_managers()
        missing = mgrs['x11'].check_dependencies()
        if missing:
            return jsonify({
                'status': 'missing',
                'missing': missing,
                'install_cmd': 'sudo apt install xvfb x11vnc websockify'
            })
        return jsonify({'status': 'ok'})
    
    @app.route('/api/x11/config', methods=['GET'])
    def get_x11_config():
        mgrs = get_managers()
        return jsonify({'status': 'ok', 'config': mgrs['x11'].get_fixed_config()})
    
    @app.route('/api/x11/displays', methods=['GET'])
    def list_displays():
        mgrs = get_managers()
        return jsonify({'displays': mgrs['x11'].list_displays()})
    
    @app.route('/api/x11/displays', methods=['POST'])
    def create_display():
        mgrs = get_managers()
        data = request.get_json() or {}
        panel_index = data.get('panel_index')
        display_num = data.get('display_num')
        width = data.get('width', 1280)
        height = data.get('height', 800)
        result, error = mgrs['x11'].start_display(display_num=display_num, panel_index=panel_index, width=width, height=height)
        if error:
            return jsonify({'status': 'error', 'message': error}), 400
        return jsonify({'status': 'ok', 'display': result})
    
    @app.route('/api/x11/panel/<int:panel_index>/connect', methods=['POST'])
    def connect_panel(panel_index):
        """
        Connect a GUI panel to its fixed display.
        Creates the display on-demand if it doesn't exist.
        
        Panel 0 -> :100
        Panel 1 -> :101
        Panel 2 -> :102
        """
        mgrs = get_managers()
        data = request.get_json() or {}
        
        if panel_index not in [0, 1, 2]:
            return jsonify({'status': 'error', 'message': 'Invalid panel index. Must be 0, 1, or 2'}), 400
        
        width = data.get('width', 1280)
        height = data.get('height', 800)
        display_num = mgrs['x11'].get_display_for_panel(panel_index)
        
        existing = mgrs['x11'].get_display(display_num)
        if existing:
            return jsonify({
                'status': 'ok',
                'display': existing,
                'created': False,
                'message': f'Display :{display_num} already running'
            })
        
        result, error = mgrs['x11'].start_display_for_panel(panel_index, width=width, height=height)
        if error:
            return jsonify({'status': 'error', 'message': error}), 400
        
        return jsonify({
            'status': 'ok',
            'display': result,
            'created': True,
            'message': f'Display :{display_num} created'
        })
    
    @app.route('/api/x11/panel/<int:panel_index>/disconnect', methods=['POST'])
    def disconnect_panel(panel_index):
        mgrs = get_managers()
        if panel_index not in [0, 1, 2]:
            return jsonify({'status': 'error', 'message': 'Invalid panel index'}), 400
        display_num = mgrs['x11'].get_display_for_panel(panel_index)
        success, error = mgrs['x11'].stop_display(display_num)
        if not success:
            return jsonify({'status': 'error', 'message': error}), 404
        return jsonify({'status': 'ok', 'message': f'Display :{display_num} stopped'})
    
    @app.route('/api/x11/displays/<int:display_num>', methods=['GET'])
    def get_display(display_num):
        mgrs = get_managers()
        info = mgrs['x11'].get_display(display_num)
        if info:
            return jsonify({'status': 'ok', 'display': info})
        return jsonify({'status': 'none', 'message': 'Display not found'})
    
    @app.route('/api/x11/displays/<int:display_num>', methods=['DELETE'])
    def delete_display(display_num):
        mgrs = get_managers()
        success, error = mgrs['x11'].stop_display(display_num)
        if not success:
            return jsonify({'status': 'error', 'message': error}), 404
        return jsonify({'status': 'ok'})
    
    @app.route('/api/x11/displays/<int:display_num>/resize', methods=['POST'])
    def resize_display(display_num):
        mgrs = get_managers()
        data = request.get_json() or {}
        width = data.get('width', 1280)
        height = data.get('height', 800)
        result, error = mgrs['x11'].resize_display(display_num, width, height)
        if error:
            return jsonify({'status': 'error', 'message': error}), 400
        return jsonify({'status': 'ok', 'display': result})
    
    @app.route('/api/x11/displays/<int:display_num>/env', methods=['GET'])
    def get_display_env(display_num):
        mgrs = get_managers()
        env_cmd = mgrs['x11'].get_env_setup_commands(display_num)
        if env_cmd:
            return jsonify({'status': 'ok', 'command': env_cmd, 'display': f':{display_num}'})
        return jsonify({'status': 'error', 'message': 'Display not found'}), 404
    
    @app.route('/api/sessions/<session>/bind-display', methods=['POST'])
    def bind_display_to_session(session):
        mgrs = get_managers()
        data = request.get_json() or {}
        display_num = data.get('display_num')
        panel_index = data.get('panel_index')
        socket = data.get('socket')
        
        if display_num is None and panel_index is not None:
            display_num = mgrs['x11'].get_display_for_panel(panel_index)
        
        if display_num is None:
            return jsonify({'status': 'error', 'message': 'display_num or panel_index required'}), 400
        
        display_info = mgrs['x11'].get_display(display_num)
        if not display_info:
            return jsonify({'status': 'error', 'message': f'Display :{display_num} not found'}), 404
        
        full_name = mgrs['tmux'].get_full_name(session)
        if not mgrs['tmux'].session_exists(full_name, socket=socket):
            return jsonify({'status': 'error', 'message': 'Session not found'}), 404
        
        display = f":{display_num}"
        mgrs['tmux'].set_environment(full_name, "DISPLAY", display, socket=socket)
        mgrs['tmux'].set_environment(full_name, "WAYLAND_DISPLAY", unset=True, socket=socket)
        mgrs['tmux'].set_environment(full_name, "GDK_BACKEND", "x11", socket=socket)
        mgrs['tmux'].set_environment(full_name, "QT_QPA_PLATFORM", "xcb", socket=socket)
        mgrs['tmux'].set_environment(full_name, "LIBGL_ALWAYS_SOFTWARE", "1", socket=socket)
        mgrs['tmux'].set_environment(full_name, "GALLIUM_DRIVER", "llvmpipe", socket=socket)
        mgrs['tmux'].set_environment(full_name, "MESA_GL_VERSION_OVERRIDE", "3.3", socket=socket)
        
        env_cmd = mgrs['x11'].get_env_setup_commands(display_num)
        if env_cmd:
            mgrs['pty'].send_keys(full_name, env_cmd + '\n')
        
        return jsonify({
            'status': 'ok',
            'session': full_name,
            'display': display,
            'display_info': display_info
        })
    
    @app.route('/api/sessions/<session>/unbind-display', methods=['POST'])
    def unbind_display_from_session(session):
        mgrs = get_managers()
        socket = request.get_json().get('socket') if request.get_json() else None
        full_name = mgrs['tmux'].get_full_name(session)
        mgrs['tmux'].set_environment(full_name, "DISPLAY", unset=True, socket=socket)
        mgrs['pty'].send_keys(full_name, 'unset DISPLAY\n')
        return jsonify({'status': 'ok', 'session': full_name})