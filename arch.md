# Tmux Control Panel v2 - Architecture Documentation

This document explains the internal architecture and design decisions for maintainability.

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Details](#component-details)
4. [Data Flow](#data-flow)
5. [Key Design Decisions](#key-design-decisions)
6. [Code Structure](#code-structure)
7. [Extending the System](#extending-the-system)

---

## System Overview

The Tmux Control Panel provides web-based access to tmux sessions. The key architectural goal is that **web UI and CLI share the exact same tmux session** - what you see in the browser is the same as `tmux attach`.

### Core Components

1. **Flask Server** - HTTP server for REST API and static files
2. **Socket.IO** - WebSocket server for real-time bidirectional communication
3. **PTY Layer** - Pseudo-terminal that attaches to tmux
4. **tmux** - Session manager and scrollback buffer
5. **xterm.js** - Browser-based terminal emulator

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              BROWSER                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         xterm.js Terminal                           │ │
│  │  • Renders terminal output (ANSI colors, cursor positioning)       │ │
│  │  • Captures keyboard input                                          │ │
│  │  • Handles mouse wheel events → triggers scroll commands            │ │
│  └──────────────────────────────┬─────────────────────────────────────┘ │
│                                 │                                        │
│                    Socket.IO WebSocket Connection                        │
│                                 │                                        │
│         ┌───────────────────────┼───────────────────────┐               │
│         │                       │                       │               │
│         ▼                       ▼                       ▼               │
│    ┌─────────┐            ┌─────────┐            ┌─────────┐           │
│    │  input  │            │  output │            │  scroll │           │
│    │ (keys)  │            │ (data)  │            │(command)│           │
│    └─────────┘            └─────────┘            └─────────┘           │
└─────────┼───────────────────────┼───────────────────────┼───────────────┘
          │                       ▲                       │
          │                       │                       │
┌─────────┼───────────────────────┼───────────────────────┼───────────────┐
│         │           PYTHON SERVER (server_pty.py)       │               │
│         │                       │                       │               │
│         ▼                       │                       ▼               │
│  ┌─────────────┐         ┌─────────────┐        ┌─────────────┐        │
│  │  WebSocket  │         │   Reader    │        │   Scroll    │        │
│  │   Handler   │         │   Thread    │        │   Handler   │        │
│  │             │         │             │        │             │        │
│  │ • subscribe │         │ • os.read() │        │ • copy-mode │        │
│  │ • input     │         │ • emit()    │        │ • C-y / C-e │        │
│  │ • resize    │         │             │        │             │        │
│  └──────┬──────┘         └──────┬──────┘        └──────┬──────┘        │
│         │                       │                       │               │
│         │              ┌────────┴────────┐              │               │
│         │              │  PTY Connection │              │               │
│         │              │   Dictionary    │              │               │
│         │              │                 │              │               │
│         │              │ {session_name:  │              │               │
│         │              │   master_fd,    │              │               │
│         │              │   pid,          │              │               │
│         │              │   thread,       │              │               │
│         │              │   clients}      │              │               │
│         │              └────────┬────────┘              │               │
│         │                       │                       │               │
│         ▼                       ▼                       ▼               │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      PTY (Master/Slave Pair)                      │  │
│  │                                                                   │  │
│  │   os.write(master_fd, keys)  ◄────────────────┐                  │  │
│  │                                                │                  │  │
│  │   os.read(master_fd) ─────────────────────────┼──► emit output   │  │
│  │                                                │                  │  │
│  └──────────────────────────────┬────────────────┘──────────────────┘  │
│                                 │                       │               │
│                                 │                       │               │
│                     ┌───────────┴───────────┐           │               │
│                     │    tmux attach -t     │           │               │
│                     │      <session>        │           │               │
│                     └───────────┬───────────┘           │               │
│                                 │                       │               │
└─────────────────────────────────┼───────────────────────┼───────────────┘
                                  │                       │
                                  │    tmux commands      │
                                  │    (copy-mode,        │
                                  │     send-keys,        │
                                  │     resize-window)    │
                                  │                       │
┌─────────────────────────────────┼───────────────────────┼───────────────┐
│                                 ▼                       ▼               │
│                        TMUX SERVER (socket: control-panel)              │
│                                                                         │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                │
│   │ cp-session1 │    │ cp-session2 │    │ cp-session3 │                │
│   │             │    │             │    │             │                │
│   │  • shell    │    │  • shell    │    │  • shell    │                │
│   │  • history  │    │  • history  │    │  • history  │                │
│   │  (50,000    │    │  (50,000    │    │  (50,000    │                │
│   │   lines)    │    │   lines)    │    │   lines)    │                │
│   └─────────────┘    └─────────────┘    └─────────────┘                │
│                                                                         │
│                              ▲                                          │
│                              │                                          │
│                     CLI: tmux -L control-panel attach -t cp-session1    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Flask + Socket.IO Server (`server_pty.py`)

The server handles three types of communication:

#### REST API (HTTP)
- Session CRUD operations
- Quick commands management
- Serves the web UI

#### WebSocket Events (Socket.IO)
- `subscribe` - Client wants to connect to a session
- `unsubscribe` - Client disconnecting from session
- `input` - Keyboard input from client
- `resize` - Terminal size changed
- `signal` - Send SIGINT, SIGTERM, etc.
- `scroll` - Enter/exit copy-mode, scroll up/down

#### PTY Management
- Spawns PTY pairs using `pty.fork()`
- Child process runs `tmux attach -t <session>`
- Parent process reads/writes to master_fd

### 2. PTY Connections Dictionary

```python
pty_connections = {
    "cp-session1": {
        "master_fd": 5,              # File descriptor for PTY master
        "pid": 12345,                # PID of tmux attach process
        "reader_thread": <Thread>,   # Thread reading PTY output
        "stop_event": <Event>,       # Signal to stop reader thread
        "clients": {"sid1", "sid2"}  # Connected WebSocket client IDs
    }
}
```

### 3. Reader Thread

Each session has a dedicated thread that:
1. Uses `select()` to wait for data on master_fd (50ms timeout)
2. Reads up to 16KB of data
3. Emits to all clients in the session's Socket.IO room
4. Handles cleanup when PTY closes

```python
def reader_thread():
    while not stop_event.is_set():
        readable, _, _ = select.select([master_fd], [], [], 0.05)
        if readable:
            data = os.read(master_fd, 16384)
            socketio.emit('output', {'session': name, 'data': data}, room=name)
```

### 4. tmux Integration

tmux is used for:
- **Session persistence** - Sessions survive server restart
- **Scrollback buffer** - 50,000 lines of history per session
- **Copy-mode** - Native scroll support with keyboard navigation
- **CLI access** - Attach from terminal with `tmux attach`

Key tmux commands used:
```bash
tmux -L control-panel new-session -d -s cp-name    # Create session
tmux -L control-panel kill-session -t cp-name      # Delete session
tmux -L control-panel resize-window -t name -x -y  # Resize
tmux -L control-panel copy-mode -t name            # Enter scroll mode
tmux -L control-panel send-keys -t name -N 5 C-y   # Scroll up 5 lines
tmux -L control-panel send-keys -t name q          # Exit copy-mode
```

### 5. xterm.js Frontend

The frontend uses xterm.js with these addons:
- **FitAddon** - Auto-resize terminal to container
- **WebLinksAddon** - Clickable URLs

Key handlers:
- `term.onData()` - Captures keyboard input → sends to server
- `term.onResize()` - Detects size changes → sends resize event
- `term.write()` - Renders output from server
- `wheel` event - Triggers scroll commands

---

## Data Flow

### Typing a Command

```
1. User types 'l' in browser
   │
2. xterm.js onData fires with 'l'
   │
3. Socket.IO emit('input', {session, keys: 'l'})
   │
4. Server handle_input() receives event
   │
5. os.write(master_fd, b'l')
   │
6. PTY sends 'l' to tmux attach process
   │
7. tmux sends 'l' to shell, shell echoes 'l'
   │
8. tmux sends echo back through PTY
   │
9. Reader thread: os.read(master_fd) → 'l'
   │
10. socketio.emit('output', {data: 'l'}, room=session)
    │
11. Browser receives 'output' event
    │
12. term.write('l') → character appears on screen
```

### Scrolling Up

```
1. User scrolls mouse wheel up
   │
2. wheel event handler detects deltaY < 0
   │
3. If not in copy-mode:
   │   emit('scroll', {command: 'enter'})
   │   Server: tmux copy-mode -t session
   │   (tmux enters copy-mode, shows indicator)
   │
4. emit('scroll', {command: 'up', lines: 3})
   │
5. Server: tmux send-keys -t session -N 3 C-y
   │
6. tmux scrolls up 3 lines in copy-mode
   │
7. tmux redraws screen through PTY
   │
8. Reader thread emits new screen content
   │
9. xterm.js renders scrolled view
```

### Exiting Copy-Mode

```
1. User types any key while in copy-mode
   │
2. onData handler checks inCopyMode flag
   │
3. emit('scroll', {command: 'exit'})
   │
4. Server: tmux send-keys -t session q
   │
5. tmux exits copy-mode, returns to live shell
   │
6. inCopyMode = false
   │
7. Normal key is sent to shell
```

---

## Key Design Decisions

### Why PTY + tmux attach?

**Problem:** How to share a session between web UI and CLI?

**Options considered:**
1. Direct shell in PTY (no tmux) - No CLI access, no persistent scrollback
2. tmux pipe-pane - Unreliable, misses output
3. tmux capture-pane - Width mismatch causes display corruption
4. **PTY running tmux attach** ✓ - Both see same session

**Solution:** The PTY child process runs `tmux attach`, so all I/O goes through tmux. The web UI and any CLI attachment see identical content.

### Why tmux copy-mode for scrolling?

**Problem:** How to scroll through history in the web UI?

**Options considered:**
1. xterm.js scrollback buffer - Doesn't work because tmux uses alternate screen
2. Fetch scrollback with capture-pane - Width mismatch causes corruption
3. **tmux copy-mode** ✓ - Native scrolling, correct width, no corruption

**Solution:** Mouse wheel triggers tmux copy-mode commands. tmux handles the scroll rendering, ensuring correct line wrapping.

### Why eventlet?

**Problem:** Flask-SocketIO needs async support for WebSockets.

**Options:**
1. threading mode - Simpler but can have issues with WebSocket upgrade
2. **eventlet** ✓ - Monkey-patches for async, reliable WebSocket support
3. gevent - Similar to eventlet, either works

### Why resize before subscribe?

**Problem:** Display corruption when terminal sizes don't match.

**Solution:** 
1. Client sends cols/rows in subscribe event
2. Server resizes tmux BEFORE spawning PTY
3. PTY attaches to correctly-sized tmux
4. Client sends resize again after subscribe to ensure sync

---

## Code Structure

### server_pty.py

```
Imports and Configuration (lines 1-50)
├── eventlet monkey-patching
├── Flask/SocketIO setup
└── Constants (TMUX_SOCKET, SESSION_PREFIX)

tmux Helper Functions (lines 50-120)
├── run_tmux() - Execute tmux commands
├── get_tmux_sessions() - List sessions
├── session_exists() - Check if session exists
├── create_tmux_session() - Create new session
└── destroy_tmux_session() - Delete session

PTY Functions (lines 120-200)
├── set_winsize() - Set terminal size via ioctl
├── spawn_pty_for_session() - Fork PTY, attach to tmux
├── get_tmux_scrollback() - Capture pane content
└── get_tmux_history_size() - Get history line count

PTY Connection Management (lines 200-320)
├── start_pty_reader() - Start reader thread
├── cleanup_pty_connection() - Stop thread, close FD
├── get_or_create_pty_connection() - Get/create connection
├── remove_client_from_connection() - Remove client
├── send_keys_to_session() - Write to PTY
├── resize_session() - Resize PTY and tmux
└── send_signal_to_session() - Send signal to process

WebSocket Handlers (lines 380-520)
├── handle_connect() - New WebSocket connection
├── handle_disconnect() - WebSocket disconnected
├── handle_subscribe() - Client subscribing to session
├── handle_unsubscribe() - Client unsubscribing
├── handle_input() - Keyboard input
├── handle_resize() - Terminal resize
├── handle_signal() - Signal control
└── handle_scroll() - Scroll commands (copy-mode)

REST API (lines 520-600)
├── index() - Serve web UI
├── list_sessions() - GET /api/sessions
├── create_session() - POST /api/sessions
├── delete_session() - DELETE /api/sessions/<n>
└── commands endpoints - Quick commands CRUD

Main (lines 600+)
├── cleanup() - Cleanup on exit
└── socketio.run() - Start server
```

### templates/index.html

```
HTML Structure (lines 1-480)
├── Head - CSS, external scripts (xterm.js, Socket.IO)
├── Sidebar - Session list, new session button
├── Main panel - Terminal container, controls
└── Modals - New session, add command dialogs

JavaScript (lines 480-1060)
├── Global State - socket, term, currentSession, etc.
├── WebSocket Functions
│   ├── connectWebSocket() - Setup Socket.IO
│   └── Event handlers (connect, output, subscribed, etc.)
├── Terminal Functions
│   ├── initTerminal() - Create xterm.js instance
│   └── attachTerminal() - Open terminal, setup scroll
├── Session Management
│   ├── refreshSessions() - Fetch session list
│   ├── selectSession() - Switch to session
│   ├── createSession() - Create new session
│   └── deleteSession() - Delete session
├── Quick Commands - Add, render, execute, delete
├── UI Functions - Modals, status updates
└── Initialization - DOMContentLoaded setup
```

---

## Extending the System

### Adding a New WebSocket Event

1. **Server side** (`server_pty.py`):
```python
@socketio.on('my_event')
def handle_my_event(data):
    session = data.get('session')
    # ... handle event ...
    emit('my_response', {'result': 'ok'})
```

2. **Client side** (`index.html`):
```javascript
// Send event
socket.emit('my_event', { session: currentSession, param: value });

// Handle response
socket.on('my_response', (data) => {
    console.log(data.result);
});
```

### Adding a New REST Endpoint

```python
@app.route('/api/my_endpoint', methods=['POST'])
def my_endpoint():
    data = request.get_json() or {}
    # ... process ...
    return jsonify({'status': 'ok', 'result': result})
```

### Adding a tmux Feature

1. Find the tmux command: `man tmux`
2. Test it manually: `tmux -L control-panel <command>`
3. Add to server:
```python
def my_tmux_feature(session_name):
    full_name = f"{SESSION_PREFIX}{session_name}"
    result = run_tmux("my-command", "-t", full_name, "args")
    return result.returncode == 0
```

### Modifying the UI

The UI is a single HTML file with inline CSS and JavaScript. Key areas:

- **Styles**: `<style>` tag in `<head>` (lines 17-470)
- **HTML structure**: `<body>` content (lines 470-480)
- **JavaScript**: `<script>` tag at end (lines 480-1060)

To add a new button:
```html
<button class="btn" onclick="myFunction()">My Button</button>
```

```javascript
function myFunction() {
    socket.emit('my_event', { session: currentSession });
}
```

---

## Maintenance Tips

1. **Debug WebSocket issues**: Check browser console (F12) and server output
2. **Debug tmux issues**: Run tmux commands manually to test
3. **Reset everything**: `tmux -L control-panel kill-server` then restart Python
4. **Check PTY connections**: Add logging to `start_pty_reader()`
5. **Test scroll**: Run `seq 1 1000` and scroll up

---

## Known Limitations

1. **Single-user design** - No authentication, local use only
2. **No session restore** - PTY connections lost on server restart (tmux sessions persist)
3. **Copy-mode indicator** - Shows in tmux but user needs to know to type to exit
4. **Browser compatibility** - Requires modern browser with WebSocket support