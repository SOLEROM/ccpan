#!/usr/bin/env python3
"""
Tmux Control Panel v3 - WebSocket + tmux + X11 GUI Apps

This version adds support for running X11 GUI applications in the browser
using Xvfb (virtual framebuffer) and noVNC.

Architecture:
  Terminal: Web UI ──► PTY ──► tmux attach ──► tmux session
  GUI Apps: Web UI ──► noVNC ──► x11vnc ──► Xvfb ──► X11 app
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
import shutil
import atexit
from pathlib import Path

# Try to use eventlet for better WebSocket support
try:
    import eventlet
    eventlet.monkey_patch()
    ASYNC_MODE = 'eventlet'
except ImportError:
    ASYNC_MODE = 'threading'

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

# Configuration
TMUX_SOCKET = "control-panel"
SESSION_PREFIX = "cp-"
COMMANDS_FILE = "commands.json"

# X11 Configuration
XVFB_DISPLAY_BASE = 99  # Start display numbers from :99
X11_APPS = {}  # Track standalone X11 apps: {app_id: {display, xvfb_pid, app_pid, vnc_pid, ws_port}}
SESSION_DISPLAYS = {}  # Track X11 displays for sessions: {session_name: {display, xvfb_pid, vnc_pid, ws_pid, ws_port}}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=ASYNC_MODE)

# Track active PTY connections
pty_connections = {}


def get_clean_x11_env(display):
    """Get a clean environment for X11 processes without Wayland."""
    clean_env = os.environ.copy()
    # Remove Wayland-related variables
    clean_env.pop('WAYLAND_DISPLAY', None)
    clean_env.pop('XDG_SESSION_TYPE', None)
    # Set X11 display
    clean_env['DISPLAY'] = display
    # Force X11 backend for various toolkits
    clean_env['GDK_BACKEND'] = 'x11'
    clean_env['QT_QPA_PLATFORM'] = 'xcb'
    return clean_env


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
    
    # Create with small size - will be resized when client connects
    # This prevents size mismatch issues
    cmd_args = ["new-session", "-d", "-s", full_name, "-x", "80", "-y", "24"]
    if cwd and os.path.isdir(cwd):
        cmd_args.extend(["-c", cwd])
    
    result = run_tmux(*cmd_args)
    if result.returncode != 0:
        return False, result.stderr
    
    # Disable mouse mode so scroll events stay in xterm.js
    run_tmux("set-option", "-t", full_name, "mouse", "off")
    
    # Set large history limit
    run_tmux("set-option", "-t", full_name, "history-limit", "50000")
    
    # Allow window to be resized by any client
    run_tmux("set-window-option", "-t", full_name, "aggressive-resize", "on")
    
    # Set TERM properly
    run_tmux("set-option", "-t", full_name, "default-terminal", "xterm-256color")
    
    # Don't run initial command here - let client connect first
    # Store it and run after client is connected
    if initial_cmd:
        # Wait a bit then send the command
        time.sleep(0.2)
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
    """
    Spawn a PTY that attaches to a tmux session.
    
    The web UI and CLI share the same tmux session.
    Scrollback is handled by tmux's buffer, accessed via capture-pane.
    """
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    # FIRST: Resize tmux to match client BEFORE attaching
    run_tmux("resize-window", "-t", full_name, "-x", str(cols), "-y", str(rows))
    
    # Small delay to let tmux process the resize
    time.sleep(0.05)
    
    pid, master_fd = pty.fork()
    
    if pid == 0:
        # Child process - attach to tmux
        os.environ['TERM'] = 'xterm-256color'
        os.execlp('tmux', 'tmux', '-L', TMUX_SOCKET, 'attach', '-t', full_name)
    else:
        # Parent process
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        set_winsize(master_fd, rows, cols)
        
        # Small delay then resize again and redraw
        time.sleep(0.1)
        run_tmux("resize-window", "-t", full_name, "-x", str(cols), "-y", str(rows))
        
        # Force tmux to redraw cleanly
        run_tmux("refresh-client", "-t", full_name)
        
        return master_fd, pid


def get_tmux_scrollback(session_name, start_line=-10000, end_line=None):
    """
    Get scrollback content from tmux's buffer.
    
    Args:
        session_name: The session to capture from
        start_line: Negative number for history, 0 for top of visible
        end_line: None for end of visible area
    
    Returns:
        String containing the captured content with ANSI codes
    """
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    cmd_args = ["capture-pane", "-t", full_name, "-p", "-e", "-J"]  # -e for escape sequences, -J to join wrapped lines
    
    if start_line is not None:
        cmd_args.extend(["-S", str(start_line)])
    if end_line is not None:
        cmd_args.extend(["-E", str(end_line)])
    
    result = run_tmux(*cmd_args)
    if result.returncode == 0:
        return result.stdout
    return ""


def get_tmux_history_size(session_name):
    """Get the number of lines in tmux's history buffer."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    result = run_tmux("display-message", "-t", full_name, "-p", "#{history_size}")
    if result.returncode == 0:
        try:
            return int(result.stdout.strip())
        except:
            pass
    return 0


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
    
    # Resize PTY first
    if full_name in pty_connections:
        try:
            set_winsize(pty_connections[full_name]['master_fd'], rows, cols)
        except:
            pass
    
    # Resize tmux window
    run_tmux("resize-window", "-t", full_name, "-x", str(cols), "-y", str(rows))
    
    # Force tmux to redraw/refresh
    run_tmux("refresh-client", "-t", full_name)
    
    # Send clear and reset to redraw prompt cleanly
    run_tmux("send-keys", "-t", full_name, "", "")  # Empty to trigger refresh


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
    
    # Resize tmux to match client's terminal size BEFORE connecting
    resize_session(full_name, cols, rows)
    
    join_room(full_name)
    conn = get_or_create_pty_connection(full_name, request.sid, cols, rows)
    
    if not conn:
        emit('error', {'message': f'Failed to connect to session {full_name}'})
        return
    
    # Resize again after PTY is connected
    resize_session(full_name, cols, rows)
    
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


@socketio.on('scroll')
def handle_scroll(data):
    """
    Handle scroll requests using tmux copy-mode.
    
    Commands: 'up', 'down', 'page_up', 'page_down', 'top', 'bottom', 'exit'
    """
    session_name = data.get('session')
    command = data.get('command', '')
    lines = data.get('lines', 1)
    
    if not session_name:
        return
    
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if command == 'enter':
        # Enter copy-mode
        run_tmux("copy-mode", "-t", full_name)
    elif command == 'exit':
        # Exit copy-mode by sending 'q'
        run_tmux("send-keys", "-t", full_name, "q")
    elif command == 'up':
        # Scroll up in copy-mode
        run_tmux("send-keys", "-t", full_name, "-N", str(lines), "C-y")
    elif command == 'down':
        # Scroll down in copy-mode
        run_tmux("send-keys", "-t", full_name, "-N", str(lines), "C-e")
    elif command == 'page_up':
        run_tmux("send-keys", "-t", full_name, "C-b")
    elif command == 'page_down':
        run_tmux("send-keys", "-t", full_name, "C-f")
    elif command == 'top':
        run_tmux("send-keys", "-t", full_name, "g")
    elif command == 'bottom':
        run_tmux("send-keys", "-t", full_name, "G")


@socketio.on('get_scrollback')
def handle_get_scrollback(data):
    """
    Get scrollback content from tmux's buffer.
    
    Client sends: {session, start_line, end_line}
    Server responds with: {session, content, history_size}
    """
    session_name = data.get('session')
    start_line = data.get('start_line', -1000)
    end_line = data.get('end_line', None)
    
    if not session_name:
        emit('error', {'message': 'No session specified'})
        return
    
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    content = get_tmux_scrollback(full_name, start_line, end_line)
    history_size = get_tmux_history_size(full_name)
    
    emit('scrollback', {
        'session': full_name,
        'content': content,
        'history_size': history_size,
        'start_line': start_line
    })


# ============================================================================
# X11 GUI App Management
# ============================================================================

def find_free_display():
    """Find a free X display number."""
    for display_num in range(XVFB_DISPLAY_BASE, XVFB_DISPLAY_BASE + 100):
        lock_file = f"/tmp/.X{display_num}-lock"
        socket_file = f"/tmp/.X11-unix/X{display_num}"
        if not os.path.exists(lock_file) and not os.path.exists(socket_file):
            return display_num
    return None


def find_free_port(start=5900, end=5999):
    """Find a free port for VNC."""
    import socket
    for port in range(start, end):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            continue
    return None


def check_x11_dependencies():
    """Check if required X11 tools are installed."""
    required = ['Xvfb', 'x11vnc']
    missing = []
    for cmd in required:
        if not shutil.which(cmd):
            missing.append(cmd)
    return missing


def check_virtualgl():
    """Check if VirtualGL is installed."""
    return shutil.which('vglrun') is not None


def check_software_gl():
    """Check if software OpenGL (Mesa LLVMpipe) can be used."""
    # Check for Mesa drivers
    llvmpipe_paths = [
        '/usr/lib/x86_64-linux-gnu/dri/swrast_dri.so',
        '/usr/lib64/dri/swrast_dri.so',
        '/usr/lib/dri/swrast_dri.so'
    ]
    return any(os.path.exists(p) for p in llvmpipe_paths)


def start_x11_app(app_command, width=400, height=400, app_id=None):
    """
    Start an X11 application in a virtual framebuffer.
    
    Returns: {app_id, display, vnc_port, ws_port} or None on failure
    """
    # Check dependencies
    missing = check_x11_dependencies()
    if missing:
        return None, f"Missing dependencies: {', '.join(missing)}. Install with: sudo apt install xvfb x11vnc"
    
    # Find free display and ports
    display_num = find_free_display()
    if display_num is None:
        return None, "No free X display available"
    
    vnc_port = find_free_port(5900, 5999)
    if vnc_port is None:
        return None, "No free VNC port available"
    
    ws_port = find_free_port(6080, 6180)
    if ws_port is None:
        return None, "No free WebSocket port available"
    
    display = f":{display_num}"
    app_id = app_id or f"app-{uuid.uuid4().hex[:8]}"
    
    # Get clean environment for X11 (without Wayland)
    clean_env = get_clean_x11_env(display)
    
    try:
        # Start Xvfb (virtual framebuffer)
        xvfb_cmd = [
            "Xvfb", display,
            "-screen", "0", f"{width}x{height}x24",
            "-ac",  # Disable access control
            "+extension", "GLX"
        ]
        xvfb_proc = subprocess.Popen(
            xvfb_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env
        )
        time.sleep(0.5)  # Wait for Xvfb to start
        
        if xvfb_proc.poll() is not None:
            return None, "Failed to start Xvfb"
        
        # Start the X11 application
        app_proc = subprocess.Popen(
            app_command,
            shell=True,
            env=clean_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(0.3)  # Wait for app to start
        
        if app_proc.poll() is not None:
            xvfb_proc.terminate()
            return None, f"Failed to start application: {app_command}"
        
        # Start x11vnc to capture the display
        vnc_cmd = [
            "x11vnc",
            "-display", display,
            "-rfbport", str(vnc_port),
            "-nopw",  # No password
            "-forever",  # Don't exit when client disconnects
            "-shared",  # Allow multiple connections
            "-noxdamage",  # Disable DAMAGE extension (more compatible)
            "-wait", "5",  # Polling wait
            "-defer", "5"  # Defer updates
        ]
        vnc_proc = subprocess.Popen(
            vnc_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env
        )
        time.sleep(0.5)  # Wait for VNC to start
        
        if vnc_proc.poll() is not None:
            app_proc.terminate()
            xvfb_proc.terminate()
            return None, "Failed to start x11vnc"
        
        # Start websockify to bridge VNC to WebSocket
        ws_cmd = [
            "websockify",
            "--web", "/usr/share/novnc",  # noVNC web files (if available)
            str(ws_port),
            f"127.0.0.1:{vnc_port}"
        ]
        ws_proc = subprocess.Popen(
            ws_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(0.3)
        
        if ws_proc.poll() is not None:
            vnc_proc.terminate()
            app_proc.terminate()
            xvfb_proc.terminate()
            return None, "Failed to start websockify"
        
        # Store app info
        X11_APPS[app_id] = {
            'display': display,
            'display_num': display_num,
            'xvfb_pid': xvfb_proc.pid,
            'app_pid': app_proc.pid,
            'app_command': app_command,
            'vnc_pid': vnc_proc.pid,
            'vnc_port': vnc_port,
            'ws_pid': ws_proc.pid,
            'ws_port': ws_port,
            'width': width,
            'height': height
        }
        
        return {
            'app_id': app_id,
            'display': display,
            'vnc_port': vnc_port,
            'ws_port': ws_port,
            'width': width,
            'height': height
        }, None
        
    except Exception as e:
        return None, str(e)


def stop_x11_app(app_id):
    """Stop an X11 application and clean up."""
    if app_id not in X11_APPS:
        return False, "App not found"
    
    app_info = X11_APPS[app_id]
    
    # Kill processes in reverse order
    for pid_key in ['ws_pid', 'vnc_pid', 'app_pid', 'xvfb_pid']:
        pid = app_info.get(pid_key)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
                os.kill(pid, signal.SIGKILL)  # Force kill if still alive
            except ProcessLookupError:
                pass  # Already dead
            except Exception:
                pass
    
    del X11_APPS[app_id]
    return True, None


def get_x11_apps():
    """Get list of running X11 apps."""
    # Clean up dead apps
    dead_apps = []
    for app_id, info in X11_APPS.items():
        try:
            os.kill(info['app_pid'], 0)  # Check if alive
        except ProcessLookupError:
            dead_apps.append(app_id)
    
    for app_id in dead_apps:
        stop_x11_app(app_id)
    
    return [
        {
            'app_id': app_id,
            'command': info['app_command'],
            'display': info['display'],
            'ws_port': info['ws_port'],
            'width': info['width'],
            'height': info['height']
        }
        for app_id, info in X11_APPS.items()
    ]


def cleanup_x11_apps():
    """Clean up all X11 apps on exit."""
    for app_id in list(X11_APPS.keys()):
        stop_x11_app(app_id)


# ============================================================================
# Session X11 Display Management
# ============================================================================

def start_session_display(session_name, width=800, height=600):
    """
    Start an X11 display for a tmux session.
    
    This creates a virtual X server that the session can use.
    Any GUI app launched in the session will appear on this display.
    """
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    # Check if already has a display
    if full_name in SESSION_DISPLAYS:
        info = SESSION_DISPLAYS[full_name]
        return {
            'session': full_name,
            'display': info['display'],
            'ws_port': info['ws_port'],
            'width': info['width'],
            'height': info['height']
        }, None
    
    # Check dependencies
    missing = check_x11_dependencies()
    if missing:
        return None, f"Missing dependencies: {', '.join(missing)}"
    
    # Find free display and ports
    display_num = find_free_display()
    if display_num is None:
        return None, "No free X display available"
    
    vnc_port = find_free_port(5900, 5999)
    if vnc_port is None:
        return None, "No free VNC port available"
    
    ws_port = find_free_port(6080, 6180)
    if ws_port is None:
        return None, "No free WebSocket port available"
    
    display = f":{display_num}"
    
    # Get clean environment for X11 (without Wayland)
    clean_env = get_clean_x11_env(display)
    
    print(f"[DEBUG] Starting X11 display: {display}, VNC port: {vnc_port}, WS port: {ws_port}")
    
    try:
        # Start Xvfb
        xvfb_cmd = [
            "Xvfb", display,
            "-screen", "0", f"{width}x{height}x24",
            "-ac",
            "+extension", "GLX"
        ]
        print(f"[DEBUG] Running: {' '.join(xvfb_cmd)}")
        xvfb_proc = subprocess.Popen(
            xvfb_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_env
        )
        time.sleep(0.5)
        
        poll_result = xvfb_proc.poll()
        if poll_result is not None:
            stdout, stderr = xvfb_proc.communicate()
            return None, f"Failed to start Xvfb (exit code {poll_result}): {stderr.decode()}"
        print(f"[DEBUG] Xvfb started, PID: {xvfb_proc.pid}")
        
        # Start x11vnc with clean environment (no Wayland)
        vnc_cmd = [
            "x11vnc",
            "-display", display,
            "-rfbport", str(vnc_port),
            "-nopw",
            "-forever",
            "-shared",
            "-noxdamage",
            "-wait", "5",
            "-defer", "5"
        ]
        print(f"[DEBUG] Running: {' '.join(vnc_cmd)}")
        vnc_proc = subprocess.Popen(
            vnc_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_env
        )
        time.sleep(0.5)
        
        poll_result = vnc_proc.poll()
        if poll_result is not None:
            stdout, stderr = vnc_proc.communicate()
            xvfb_proc.terminate()
            return None, f"Failed to start x11vnc (exit code {poll_result}): {stderr.decode()}"
        print(f"[DEBUG] x11vnc started, PID: {vnc_proc.pid}")
        
        # Start websockify
        ws_cmd = [
            "websockify",
            str(ws_port),
            f"127.0.0.1:{vnc_port}"
        ]
        print(f"[DEBUG] Running: {' '.join(ws_cmd)}")
        ws_proc = subprocess.Popen(
            ws_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(0.3)
        
        poll_result = ws_proc.poll()
        if poll_result is not None:
            stdout, stderr = ws_proc.communicate()
            vnc_proc.terminate()
            xvfb_proc.terminate()
            return None, f"Failed to start websockify (exit code {poll_result}): {stderr.decode()}"
        print(f"[DEBUG] websockify started, PID: {ws_proc.pid}")
        
        # Set DISPLAY environment in the tmux session
        run_tmux("set-environment", "-t", full_name, "DISPLAY", display)
        
        # Unset Wayland to force X11
        run_tmux("set-environment", "-t", full_name, "-u", "WAYLAND_DISPLAY")
        run_tmux("set-environment", "-t", full_name, "GDK_BACKEND", "x11")
        run_tmux("set-environment", "-t", full_name, "QT_QPA_PLATFORM", "xcb")
        
        # Enable software OpenGL rendering (Mesa LLVMpipe)
        run_tmux("set-environment", "-t", full_name, "LIBGL_ALWAYS_SOFTWARE", "1")
        run_tmux("set-environment", "-t", full_name, "GALLIUM_DRIVER", "llvmpipe")
        run_tmux("set-environment", "-t", full_name, "MESA_GL_VERSION_OVERRIDE", "3.3")
        
        # Check for VirtualGL
        has_vgl = check_virtualgl()
        
        # Send commands to set up the environment in the shell
        env_setup = f"export DISPLAY={display} && unset WAYLAND_DISPLAY && export GDK_BACKEND=x11 && export QT_QPA_PLATFORM=xcb && export LIBGL_ALWAYS_SOFTWARE=1 && export GALLIUM_DRIVER=llvmpipe && export MESA_GL_VERSION_OVERRIDE=3.3"
        run_tmux("send-keys", "-t", full_name, env_setup, "Enter")
        
        # Store display info
        SESSION_DISPLAYS[full_name] = {
            'display': display,
            'display_num': display_num,
            'xvfb_pid': xvfb_proc.pid,
            'vnc_pid': vnc_proc.pid,
            'vnc_port': vnc_port,
            'ws_pid': ws_proc.pid,
            'ws_port': ws_port,
            'width': width,
            'height': height,
            'has_virtualgl': has_vgl
        }
        
        print(f"[DEBUG] Session display started successfully")
        
        return {
            'session': full_name,
            'display': display,
            'ws_port': ws_port,
            'width': width,
            'height': height,
            'has_virtualgl': has_vgl,
            'software_gl': True
        }, None
        
    except Exception as e:
        import traceback
        print(f"[DEBUG] Exception: {traceback.format_exc()}")
        return None, str(e)


def stop_session_display(session_name):
    """Stop the X11 display for a session."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name not in SESSION_DISPLAYS:
        return False, "No display for this session"
    
    info = SESSION_DISPLAYS[full_name]
    
    # Kill processes
    for pid_key in ['ws_pid', 'vnc_pid', 'xvfb_pid']:
        pid = info.get(pid_key)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                pass
    
    # Unset DISPLAY in session
    run_tmux("set-environment", "-t", full_name, "-u", "DISPLAY")
    run_tmux("send-keys", "-t", full_name, "unset DISPLAY", "Enter")
    
    del SESSION_DISPLAYS[full_name]
    return True, None


def get_session_display(session_name):
    """Get the X11 display info for a session."""
    full_name = session_name if session_name.startswith(SESSION_PREFIX) else f"{SESSION_PREFIX}{session_name}"
    
    if full_name not in SESSION_DISPLAYS:
        return None
    
    info = SESSION_DISPLAYS[full_name]
    
    # Check if still alive
    try:
        os.kill(info['xvfb_pid'], 0)
    except ProcessLookupError:
        stop_session_display(full_name)
        return None
    
    return {
        'session': full_name,
        'display': info['display'],
        'ws_port': info['ws_port'],
        'width': info['width'],
        'height': info['height']
    }


def cleanup_session_displays():
    """Clean up all session displays on exit."""
    for session_name in list(SESSION_DISPLAYS.keys()):
        stop_session_display(session_name)


# Register cleanup
atexit.register(cleanup_x11_apps)
atexit.register(cleanup_session_displays)


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


# X11 App API
@app.route('/api/x11/apps', methods=['GET'])
def list_x11_apps():
    """List running X11 apps."""
    return jsonify({'apps': get_x11_apps()})


@app.route('/api/x11/apps', methods=['POST'])
def start_x11_app_endpoint():
    """Start a new X11 app."""
    data = request.get_json() or {}
    command = data.get('command')
    if not command:
        return jsonify({'status': 'error', 'message': 'No command provided'}), 400
    
    width = data.get('width', 400)
    height = data.get('height', 400)
    app_id = data.get('app_id')
    
    result, error = start_x11_app(command, width, height, app_id)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400
    
    return jsonify({'status': 'ok', 'app': result})


@app.route('/api/x11/apps/<app_id>', methods=['DELETE'])
def stop_x11_app_endpoint(app_id):
    """Stop an X11 app."""
    success, error = stop_x11_app(app_id)
    if not success:
        return jsonify({'status': 'error', 'message': error}), 404
    return jsonify({'status': 'ok'})


@app.route('/api/x11/check', methods=['GET'])
def check_x11_deps():
    """Check if X11 dependencies are installed."""
    missing = check_x11_dependencies()
    if missing:
        return jsonify({
            'status': 'missing',
            'missing': missing,
            'install_cmd': f"sudo apt install xvfb x11vnc novnc websockify"
        })
    return jsonify({'status': 'ok'})


# Session X11 Display API
@app.route('/api/sessions/<session>/display', methods=['GET'])
def get_session_display_endpoint(session):
    """Get the X11 display for a session."""
    display_info = get_session_display(session)
    if display_info:
        return jsonify({'status': 'ok', 'display': display_info})
    return jsonify({'status': 'none', 'message': 'No display for this session'})


@app.route('/api/sessions/<session>/display', methods=['POST'])
def start_session_display_endpoint(session):
    """Start an X11 display for a session."""
    data = request.get_json() or {}
    width = data.get('width', 800)
    height = data.get('height', 600)
    
    result, error = start_session_display(session, width, height)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400
    
    return jsonify({'status': 'ok', 'display': result})


@app.route('/api/sessions/<session>/display', methods=['DELETE'])
def stop_session_display_endpoint(session):
    """Stop the X11 display for a session."""
    success, error = stop_session_display(session)
    if not success:
        return jsonify({'status': 'error', 'message': error}), 404
    return jsonify({'status': 'ok'})


def cleanup():
    print("\nCleaning up...")
    cleanup_x11_apps()
    cleanup_session_displays()
    for session_name in list(pty_connections.keys()):
        cleanup_pty_connection(session_name)


if __name__ == '__main__':
    import atexit
    atexit.register(cleanup)
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║         Tmux Control Panel v3 - Direct PTY Edition               ║
╠══════════════════════════════════════════════════════════════════╣
║  • WebSocket for real-time bidirectional communication           ║
║  • Direct PTY streaming (more reliable than pipe-pane)           ║
║  • X11 GUI support via Xvfb + x11vnc + websockify                ║
║  • Still uses tmux backend - attach anytime with:                ║
║      tmux -L {TMUX_SOCKET} attach -t <session>               
╚══════════════════════════════════════════════════════════════════╝
""")
    
    print("Server starting on http://127.0.0.1:5000")
    socketio.run(app, host='127.0.0.1', port=5000, debug=False)