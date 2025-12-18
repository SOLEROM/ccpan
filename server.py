#!/usr/bin/env python3
"""
Tmux Control Panel v2 - Alternative Implementation (Direct PTY)

This version uses direct PTY spawning for the WebSocket streaming,
while still integrating with tmux for session persistence and CLI access.

Approach:
  1. Each "session" has a tmux session AND a local PTY master/slave pair
  2. The PTY slave runs: tmux -L control-panel attach -t <session>
  3. PTY master streams to WebSocket, receives input from WebSocket
  4. You can still attach directly via: tmux -L control-panel attach -t <session>

Benefits:
  - More reliable streaming (direct PTY read, not pipe-pane)
  - Better escape sequence handling
  - Proper resize via ioctl
  - tmux persistence preserved
"""

import os
import sys
import json
import subprocess
import threading
import select
import pty
import fcntl
import struct
import termios
import signal
import time
import uuid
import errno
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

# Configuration
TMUX_SOCKET = "control-panel"
SESSION_PREFIX = "cp-"
COMMANDS_FILE = "commands.json"

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Track active PTY connections
pty_connections = {}


def run_tmux(*args):
    """Run a tmux command with our socket."""
    cmd = ["tmux", "-L", TMUX_SOCKET] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def get_tmux_sessions():
    """List all our tmux sessions."""
    result = run_tmux("list-sessions", "-F", "#{session_name}")
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().split('\n') 
            if line and line.startswith(SESSION_PREFIX)]


def session_exists(name):
    """Check if a tmux session exists."""
    full_name = name if name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{name}"
    return full_name in get_tmux_sessions()


def create_tmux_session(name, cwd=None, initial_cmd=None):
    """Create a new tmux session."""
    full_name = f"{SESSION_PREFIX}{name}"
    
    if session_exists(full_name):
        return False, "Session already exists"
    
    cmd_args = ["new-session", "-d", "-s", full_name, "-x", "200", "-y", "50"]
    if cwd and os.path.isdir(cwd):
        cmd_args.extend(["-c", cwd])
    
    result = run_tmux(*cmd_args)
    if result.returncode != 0:
        return False, result.stderr
    
    # Disable mouse mode so scroll events stay in xterm.js
    run_tmux("set-option", "-t", full_name, "mouse", "off")
    
    if initial_cmd:
        time.sleep(0.1)
        run_tmux("send-keys", "-t", full_name, initial_cmd, "Enter")
    
    return True, full_name


def destroy_tmux_session(name):
    """Destroy a tmux session and clean up PTY connection."""
    full_name = name if name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{name}"
    cleanup_pty_connection(full_name)
    result = run_tmux("kill-session", "-t", full_name)
    return result.returncode == 0


def set_winsize(fd, rows, cols):
    """Set terminal window size."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def spawn_pty_for_session(session_name, cols=120, rows=40):
    """Spawn a PTY that attaches to a tmux session."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    # Ensure mouse is off for this session before attaching
    run_tmux("set-option", "-t", full_name, "mouse", "off")
    
    pid, master_fd = pty.fork()
    
    if pid == 0:
        # Child process
        os.environ['TERM'] = 'xterm-256color'
        os.execlp('tmux', 'tmux', '-L', TMUX_SOCKET, 'attach', '-t', full_name)
    else:
        # Parent process
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        set_winsize(master_fd, rows, cols)
        
        # Send escape sequence to disable mouse tracking
        # This disables various mouse modes that might be enabled
        time.sleep(0.1)
        try:
            # Disable mouse tracking modes
            os.write(master_fd, b'\x1b[?1000l')  # Disable mouse click tracking
            os.write(master_fd, b'\x1b[?1002l')  # Disable mouse button tracking  
            os.write(master_fd, b'\x1b[?1003l')  # Disable all mouse tracking
            os.write(master_fd, b'\x1b[?1006l')  # Disable SGR mouse mode
        except:
            pass
        
        return master_fd, pid


def start_pty_reader(session_name, master_fd):
    """Start a thread that reads from PTY and emits to WebSocket."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    stop_event = threading.Event()
    
    def reader_thread():
        try:
            while not stop_event.is_set():
                try:
                    readable, _, _ = select.select([master_fd], [], [], 0.05)
                    if readable:
                        try:
                            data = os.read(master_fd, 16384)
                            if data:
                                socketio.emit('output', {
                                    'session': full_name,
                                    'data': data.decode('utf-8', errors='replace')
                                }, room=full_name)
                            else:
                                break  # EOF
                        except OSError as e:
                            if e.errno in (errno.EIO, errno.EBADF):
                                break
                            raise
                except (ValueError, OSError):
                    break
        except Exception as e:
            print(f"PTY reader error for {full_name}: {e}")
        finally:
            if full_name in pty_connections:
                pty_connections[full_name]['reader_stopped'] = True
    
    thread = threading.Thread(target=reader_thread, daemon=True)
    thread.start()
    return thread, stop_event


def get_or_create_pty_connection(session_name, sid, cols=120, rows=40):
    """Get existing PTY connection or create a new one."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name in pty_connections:
        conn = pty_connections[full_name]
        conn['clients'].add(sid)
        if conn.get('reader_stopped', False):
            cleanup_pty_connection(full_name)
        else:
            return conn
    
    if not session_exists(full_name):
        return None
    
    master_fd, pid = spawn_pty_for_session(full_name, cols, rows)
    reader_thread, stop_event = start_pty_reader(full_name, master_fd)
    
    pty_connections[full_name] = {
        'master_fd': master_fd,
        'pid': pid,
        'reader_thread': reader_thread,
        'stop_event': stop_event,
        'clients': {sid},
        'reader_stopped': False
    }
    return pty_connections[full_name]


def cleanup_pty_connection(session_name):
    """Clean up PTY connection for a session."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name not in pty_connections:
        return
    
    conn = pty_connections[full_name]
    conn['stop_event'].set()
    
    try:
        os.close(conn['master_fd'])
    except:
        pass
    
    try:
        os.kill(conn['pid'], signal.SIGTERM)
        os.waitpid(conn['pid'], os.WNOHANG)
    except:
        pass
    
    del pty_connections[full_name]


def remove_client_from_connection(session_name, sid):
    """Remove a client from a PTY connection."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name not in pty_connections:
        return
    
    conn = pty_connections[full_name]
    conn['clients'].discard(sid)
    
    if not conn['clients']:
        def delayed_cleanup():
            time.sleep(5)
            if full_name in pty_connections and not pty_connections[full_name]['clients']:
                cleanup_pty_connection(full_name)
        threading.Thread(target=delayed_cleanup, daemon=True).start()


def send_keys_to_session(session_name, keys):
    """Send keys to the PTY."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name in pty_connections:
        try:
            os.write(pty_connections[full_name]['master_fd'], keys.encode('utf-8'))
            return True
        except:
            pass
    
    result = run_tmux("send-keys", "-t", full_name, "-l", keys)
    return result.returncode == 0


def resize_session(session_name, cols, rows):
    """Resize both the PTY and tmux session."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name in pty_connections:
        try:
            set_winsize(pty_connections[full_name]['master_fd'], rows, cols)
        except:
            pass
    
    run_tmux("resize-window", "-t", full_name, "-x", str(cols), "-y", str(rows))


def send_signal_to_session(session_name, sig):
    """Send a signal to the foreground process."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    result = run_tmux("display-message", "-t", full_name, "-p", "#{pane_pid}")
    if result.returncode != 0:
        return False
    
    try:
        pane_pid = int(result.stdout.strip())
        children = subprocess.run(["pgrep", "-P", str(pane_pid)], capture_output=True, text=True)
        if children.stdout.strip():
            for child_pid in children.stdout.strip().split('\n'):
                try:
                    os.kill(int(child_pid), sig)
                except:
                    pass
        else:
            os.kill(pane_pid, sig)
        return True
    except:
        return False


# Custom Commands
def load_commands():
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_commands(commands):
    with open(COMMANDS_FILE, 'w') as f:
        json.dump(commands, f, indent=2)


# WebSocket Handlers
@socketio.on('connect')
def handle_connect():
    emit('connected', {'status': 'ok'})


@socketio.on('disconnect')
def handle_disconnect():
    for session_name in list(pty_connections.keys()):
        remove_client_from_connection(session_name, request.sid)


@socketio.on('subscribe')
def handle_subscribe(data):
    session_name = data.get('session')
    cols = data.get('cols', 120)
    rows = data.get('rows', 40)
    
    if not session_name:
        emit('error', {'message': 'No session specified'})
        return
    
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if not session_exists(full_name):
        emit('error', {'message': f'Session {full_name} does not exist'})
        return
    
    join_room(full_name)
    conn = get_or_create_pty_connection(full_name, request.sid, cols, rows)
    
    if not conn:
        emit('error', {'message': f'Failed to connect to session {full_name}'})
        return
    
    emit('subscribed', {'session': full_name})


@socketio.on('unsubscribe')
def handle_unsubscribe(data):
    session_name = data.get('session')
    if not session_name:
        return
    
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    leave_room(full_name)
    remove_client_from_connection(full_name, request.sid)
    emit('unsubscribed', {'session': full_name})


@socketio.on('input')
def handle_input(data):
    session_name = data.get('session')
    keys = data.get('keys', '')
    if session_name and keys:
        full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
        send_keys_to_session(full_name, keys)


@socketio.on('resize')
def handle_resize(data):
    session_name = data.get('session')
    cols = data.get('cols', 80)
    rows = data.get('rows', 24)
    if session_name:
        full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
        resize_session(full_name, cols, rows)


@socketio.on('signal')
def handle_signal(data):
    session_name = data.get('session')
    sig_name = data.get('signal', 'SIGINT')
    
    if not session_name:
        return
    
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    sig_map = {
        'SIGINT': signal.SIGINT, 'SIGTERM': signal.SIGTERM, 'SIGKILL': signal.SIGKILL,
        'SIGSTOP': signal.SIGSTOP, 'SIGCONT': signal.SIGCONT, 'SIGTSTP': signal.SIGTSTP,
    }
    send_signal_to_session(full_name, sig_map.get(sig_name, signal.SIGINT))


# REST API
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    return jsonify({'sessions': get_tmux_sessions(), 'count': len(get_tmux_sessions())})


@app.route('/api/sessions', methods=['POST'])
def create_session():
    data = request.get_json() or {}
    name = data.get('name', f"session-{uuid.uuid4().hex[:8]}")
    success, result = create_tmux_session(name, data.get('cwd'), data.get('command'))
    if success:
        return jsonify({'status': 'ok', 'session': result})
    return jsonify({'status': 'error', 'message': result}), 400


@app.route('/api/sessions/<name>', methods=['DELETE'])
def delete_session(name):
    if destroy_tmux_session(name):
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'message': 'Failed to destroy session'}), 400


@app.route('/api/sessions/<name>/command', methods=['POST'])
def run_command(name):
    data = request.get_json() or {}
    command = data.get('command', '')
    if not command:
        return jsonify({'status': 'error', 'message': 'No command provided'}), 400
    
    full_name = name if name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{name}"
    if not session_exists(full_name):
        return jsonify({'status': 'error', 'message': 'Session not found'}), 404
    
    if send_keys_to_session(full_name, command + '\n'):
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'message': 'Failed to send command'}), 400


@app.route('/api/commands', methods=['GET'])
def get_all_commands():
    return jsonify(load_commands())


@app.route('/api/commands/<session>', methods=['GET'])
def get_session_commands(session):
    return jsonify(load_commands().get(session, []))


@app.route('/api/commands/<session>', methods=['POST'])
def add_command(session):
    data = request.get_json() or {}
    if not data.get('command'):
        return jsonify({'status': 'error', 'message': 'No command provided'}), 400
    
    commands = load_commands()
    if session not in commands:
        commands[session] = []
    commands[session].append({'label': data.get('label', 'Command'), 'command': data['command']})
    save_commands(commands)
    return jsonify({'status': 'ok', 'commands': commands[session]})


@app.route('/api/commands/<session>/<int:index>', methods=['DELETE'])
def delete_command(session, index):
    commands = load_commands()
    if session not in commands or index >= len(commands[session]):
        return jsonify({'status': 'error', 'message': 'Command not found'}), 404
    commands[session].pop(index)
    save_commands(commands)
    return jsonify({'status': 'ok', 'commands': commands[session]})


def cleanup():
    print("\nCleaning up...")
    for session_name in list(pty_connections.keys()):
        cleanup_pty_connection(session_name)


if __name__ == '__main__':
    import atexit
    atexit.register(cleanup)
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║         Tmux Control Panel v2 - Direct PTY Edition               ║
╠══════════════════════════════════════════════════════════════════╣
║  • WebSocket for real-time bidirectional communication           ║
║  • Direct PTY streaming (more reliable than pipe-pane)           ║
║  • Still uses tmux backend - attach anytime with:                ║
║      tmux -L {TMUX_SOCKET} attach -t <session>               
╚══════════════════════════════════════════════════════════════════╝
""")
    
    print("Server starting on http://127.0.0.1:5000")
    socketio.run(app, host='127.0.0.1', port=5000, debug=False)