#!/usr/bin/env python3
"""
Tmux Control Panel - Local service for managing multiple tmux sessions.
Each session represents a "tab" in the browser UI.
"""

import subprocess
import json
import os
import re
import uuid
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Configuration
TMUX_SOCKET = "control-panel"  # Named socket for isolation
SCROLLBACK_LINES = 2000  # Lines of history to capture
SESSION_PREFIX = "cp-"  # Prefix for managed sessions
COMMANDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "commands.json")


def load_commands():
    """Load custom commands from JSON file."""
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_commands(commands):
    """Save custom commands to JSON file."""
    try:
        with open(COMMANDS_FILE, "w") as f:
            json.dump(commands, f, indent=2)
        return True
    except IOError:
        return False


def run_tmux(*args, timeout=10):
    """Execute a tmux command with the control panel socket."""
    cmd = ["tmux", "-L", TMUX_SOCKET] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except Exception as e:
        return "", str(e), 1


def session_exists(session_name):
    """Check if a tmux session exists."""
    _, _, rc = run_tmux("has-session", "-t", session_name)
    return rc == 0


def list_sessions():
    """List all managed tmux sessions with metadata."""
    stdout, stderr, rc = run_tmux(
        "list-sessions",
        "-F", "#{session_name}|#{session_created}|#{session_activity}|#{session_windows}"
    )
    
    sessions = []
    if rc == 0 and stdout:
        for line in stdout.strip().split("\n"):
            if line:
                parts = line.split("|")
                if len(parts) >= 4 and parts[0].startswith(SESSION_PREFIX):
                    sessions.append({
                        "name": parts[0],
                        "display_name": parts[0][len(SESSION_PREFIX):],
                        "created": int(parts[1]) if parts[1].isdigit() else 0,
                        "last_activity": int(parts[2]) if parts[2].isdigit() else 0,
                        "windows": int(parts[3]) if parts[3].isdigit() else 1
                    })
    
    return sessions


def create_session(name, working_dir=None, initial_command=None):
    """Create a new tmux session."""
    session_name = f"{SESSION_PREFIX}{name}"
    
    if session_exists(session_name):
        return False, f"Session '{name}' already exists"
    
    # Build creation command - set reasonable window size
    cmd_args = ["new-session", "-d", "-s", session_name, "-x", "200", "-y", "50"]
    
    if working_dir and os.path.isdir(working_dir):
        cmd_args.extend(["-c", working_dir])
    
    stdout, stderr, rc = run_tmux(*cmd_args)
    
    if rc != 0:
        return False, stderr or "Failed to create session"
    
    # Set up session with larger scrollback
    run_tmux("set-option", "-t", session_name, "history-limit", "50000")
    
    # Send initial command if provided
    if initial_command:
        send_keys(session_name, initial_command, enter=True)
    
    return True, session_name


def destroy_session(session_name):
    """Destroy a tmux session."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    if not session_exists(session_name):
        return False, f"Session '{session_name}' does not exist"
    
    stdout, stderr, rc = run_tmux("kill-session", "-t", session_name)
    
    if rc != 0:
        return False, stderr or "Failed to destroy session"
    
    return True, "Session destroyed"


def send_keys(session_name, keys, enter=False, raw=False):
    """Send keystrokes to a tmux session."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    if not session_exists(session_name):
        return False, f"Session '{session_name}' does not exist"
    
    if raw:
        # Raw mode: send keys exactly as received from xterm.js
        # This handles special keys like Enter, Backspace, Arrow keys, etc.
        # xterm.js sends these as escape sequences
        stdout, stderr, rc = run_tmux("send-keys", "-t", session_name, "-l", keys)
    elif enter:
        # Send command followed by Enter
        stdout, stderr, rc = run_tmux("send-keys", "-t", session_name, "-l", keys)
        if rc != 0:
            return False, stderr or "Failed to send keys"
        # Send Enter separately (not literal)
        stdout, stderr, rc = run_tmux("send-keys", "-t", session_name, "Enter")
    else:
        stdout, stderr, rc = run_tmux("send-keys", "-t", session_name, "-l", keys)
    
    if rc != 0:
        return False, stderr or "Failed to send keys"
    
    return True, "Keys sent"


def capture_output(session_name, lines=None):
    """Capture recent output from a tmux session with escape sequences."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    if not session_exists(session_name):
        return None, f"Session '{session_name}' does not exist"
    
    # Capture visible pane content with escape sequences for colors
    stdout, stderr, rc = run_tmux(
        "capture-pane",
        "-t", session_name,
        "-p",           # Print to stdout
        "-e",           # Include escape sequences (ANSI colors)
    )
    
    if rc != 0:
        return None, stderr or "Failed to capture output"
    
    return stdout, None


def get_pane_content_and_cursor(session_name):
    """Get pane content along with cursor position for proper terminal sync."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    if not session_exists(session_name):
        return None, f"Session '{session_name}' does not exist"
    
    # Get pane info including cursor position
    info_stdout, _, info_rc = run_tmux(
        "display-message", "-t", session_name, "-p", 
        "#{cursor_x}:#{cursor_y}:#{pane_width}:#{pane_height}"
    )
    
    cursor_x, cursor_y, pane_width, pane_height = 0, 0, 80, 24
    if info_rc == 0 and info_stdout:
        try:
            parts = info_stdout.strip().split(':')
            cursor_x = int(parts[0])
            cursor_y = int(parts[1])
            pane_width = int(parts[2])
            pane_height = int(parts[3])
        except (ValueError, IndexError):
            pass
    
    # Capture visible pane with escape sequences
    content_stdout, stderr, content_rc = run_tmux(
        "capture-pane",
        "-t", session_name,
        "-p",           # Print to stdout
        "-e",           # Include escape sequences (colors)
    )
    
    if content_rc != 0:
        return None, stderr or "Failed to capture output"
    
    return {
        "content": content_stdout,
        "cursor_x": cursor_x,
        "cursor_y": cursor_y,
        "width": pane_width,
        "height": pane_height
    }, None


def send_signal(session_name, signal="INT"):
    """Send a signal to the process in a tmux session."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    if not session_exists(session_name):
        return False, f"Session '{session_name}' does not exist"
    
    signal_keys = {
        "INT": "C-c",      # Ctrl+C
        "QUIT": "C-\\",    # Ctrl+\
        "STOP": "C-z",     # Ctrl+Z
        "EOF": "C-d",      # Ctrl+D
    }
    
    key = signal_keys.get(signal.upper(), "C-c")
    
    # Send the control key (not literal)
    stdout, stderr, rc = run_tmux("send-keys", "-t", session_name, key)
    
    if rc != 0:
        return False, stderr or "Failed to send signal"
    
    return True, "Signal sent"


# Flask Routes

@app.route("/")
def index():
    """Serve the main UI."""
    return render_template("index.html")


@app.route("/api/sessions", methods=["GET"])
def api_list_sessions():
    """List all sessions."""
    sessions = list_sessions()
    return jsonify({"success": True, "sessions": sessions})


@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    """Create a new session."""
    data = request.get_json() or {}
    name = data.get("name", f"session-{uuid.uuid4().hex[:8]}")
    working_dir = data.get("working_dir")
    initial_command = data.get("initial_command")
    
    # Sanitize name
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    
    success, result = create_session(name, working_dir, initial_command)
    
    if success:
        return jsonify({"success": True, "session": result})
    return jsonify({"success": False, "error": result}), 400


@app.route("/api/sessions/<session_name>", methods=["DELETE"])
def api_destroy_session(session_name):
    """Destroy a session."""
    success, result = destroy_session(session_name)
    
    if success:
        return jsonify({"success": True, "message": result})
    return jsonify({"success": False, "error": result}), 400


@app.route("/api/sessions/<session_name>/output", methods=["GET"])
def api_get_output(session_name):
    """Get output from a session."""
    output, error = capture_output(session_name)
    
    if output is not None:
        return jsonify({"success": True, "output": output})
    return jsonify({"success": False, "error": error}), 400


@app.route("/api/sessions/<session_name>/terminal", methods=["GET"])
def api_get_terminal_state(session_name):
    """Get terminal state including cursor position for xterm.js sync."""
    state, error = get_pane_content_and_cursor(session_name)
    
    if state is not None:
        return jsonify({"success": True, **state})
    return jsonify({"success": False, "error": error}), 400


@app.route("/api/sessions/<session_name>/send", methods=["POST"])
def api_send_keys(session_name):
    """Send keys to a session."""
    data = request.get_json() or {}
    keys = data.get("keys", "")
    enter = data.get("enter", True)
    raw = data.get("raw", False)
    
    if not keys:
        return jsonify({"success": False, "error": "No keys provided"}), 400
    
    success, result = send_keys(session_name, keys, enter, raw)
    
    if success:
        return jsonify({"success": True, "message": result})
    return jsonify({"success": False, "error": result}), 400


@app.route("/api/sessions/<session_name>/signal", methods=["POST"])
def api_send_signal(session_name):
    """Send a signal to a session."""
    data = request.get_json() or {}
    signal = data.get("signal", "INT")
    
    success, result = send_signal(session_name, signal)
    
    if success:
        return jsonify({"success": True, "message": result})
    return jsonify({"success": False, "error": result}), 400


@app.route("/api/sessions/<session_name>/command", methods=["POST"])
def api_run_command(session_name):
    """Run a predefined command in a session."""
    data = request.get_json() or {}
    command = data.get("command", "")
    
    if not command:
        return jsonify({"success": False, "error": "No command provided"}), 400
    
    success, result = send_keys(session_name, command, enter=True)
    
    if success:
        return jsonify({"success": True, "message": result})
    return jsonify({"success": False, "error": result}), 400


@app.route("/api/sessions/<session_name>/resize", methods=["POST"])
def api_resize_session(session_name):
    """Resize the tmux pane to match xterm.js dimensions."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    data = request.get_json() or {}
    cols = data.get("cols", 80)
    rows = data.get("rows", 24)
    
    # Resize the tmux window/pane
    stdout, stderr, rc = run_tmux(
        "resize-window", "-t", session_name, "-x", str(cols), "-y", str(rows)
    )
    
    if rc != 0:
        # Try resize-pane as fallback
        stdout, stderr, rc = run_tmux(
            "resize-pane", "-t", session_name, "-x", str(cols), "-y", str(rows)
        )
    
    return jsonify({"success": rc == 0, "cols": cols, "rows": rows})


# Custom commands storage endpoints

@app.route("/api/commands", methods=["GET"])
def api_get_all_commands():
    """Get all custom commands for all sessions."""
    commands = load_commands()
    return jsonify({"success": True, "commands": commands})


@app.route("/api/commands/<session_name>", methods=["GET"])
def api_get_commands(session_name):
    """Get custom commands for a session."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    commands = load_commands()
    session_commands = commands.get(session_name, [])
    return jsonify({"success": True, "commands": session_commands})


@app.route("/api/commands/<session_name>", methods=["POST"])
def api_add_command(session_name):
    """Add a custom command for a session."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    data = request.get_json() or {}
    label = data.get("label", "").strip()
    command = data.get("command", "").strip()
    
    if not label or not command:
        return jsonify({"success": False, "error": "Label and command are required"}), 400
    
    commands = load_commands()
    if session_name not in commands:
        commands[session_name] = []
    
    commands[session_name].append({"label": label, "command": command})
    
    if save_commands(commands):
        return jsonify({"success": True, "commands": commands[session_name]})
    return jsonify({"success": False, "error": "Failed to save commands"}), 500


@app.route("/api/commands/<session_name>/<int:index>", methods=["DELETE"])
def api_delete_command(session_name, index):
    """Delete a custom command by index."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    commands = load_commands()
    if session_name not in commands:
        return jsonify({"success": False, "error": "No commands for this session"}), 404
    
    if index < 0 or index >= len(commands[session_name]):
        return jsonify({"success": False, "error": "Invalid command index"}), 400
    
    deleted = commands[session_name].pop(index)
    
    if save_commands(commands):
        return jsonify({"success": True, "deleted": deleted, "commands": commands[session_name]})
    return jsonify({"success": False, "error": "Failed to save commands"}), 500


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check endpoint."""
    # Check if tmux is available
    stdout, stderr, rc = run_tmux("list-sessions")
    tmux_ok = rc in [0, 1]  # 1 means no sessions, which is fine
    
    return jsonify({
        "success": True,
        "tmux_available": tmux_ok,
        "socket": TMUX_SOCKET
    })


# Debug endpoint to test capture
@app.route("/api/sessions/<session_name>/debug", methods=["GET"])
def api_debug_session(session_name):
    """Debug endpoint to see raw tmux output."""
    if not session_name.startswith(SESSION_PREFIX):
        session_name = f"{SESSION_PREFIX}{session_name}"
    
    # Try different capture methods
    results = {}
    
    # Method 1: Full history
    stdout1, stderr1, rc1 = run_tmux(
        "capture-pane", "-t", session_name, "-p", "-S", "-", "-E", "-"
    )
    results["full_history"] = {"stdout": stdout1[:500], "stderr": stderr1, "rc": rc1}
    
    # Method 2: Last N lines
    stdout2, stderr2, rc2 = run_tmux(
        "capture-pane", "-t", session_name, "-p", "-S", "-100"
    )
    results["last_100"] = {"stdout": stdout2[:500], "stderr": stderr2, "rc": rc2}
    
    # Method 3: Visible only
    stdout3, stderr3, rc3 = run_tmux(
        "capture-pane", "-t", session_name, "-p"
    )
    results["visible"] = {"stdout": stdout3[:500], "stderr": stderr3, "rc": rc3}
    
    return jsonify(results)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Tmux Control Panel Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    
    print(f"Starting Tmux Control Panel on http://{args.host}:{args.port}")
    print(f"tmux socket: {TMUX_SOCKET}")
    print(f"Session prefix: {SESSION_PREFIX}")
    app.run(host=args.host, port=args.port, debug=args.debug)