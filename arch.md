# Tmux Control Panel v4 - Architecture

This document describes the architecture and design concepts of the Tmux Control Panel, providing a high-level overview for maintenance and future development.

## Overview

The application follows a **modular client-server architecture** with:
- **Backend**: Python Flask server with WebSocket support
- **Frontend**: Vanilla JavaScript single-page application
- **External Dependencies**: tmux, Xvfb, x11vnc, websockify

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (Client)                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   xterm.js  │  │  Socket.IO  │  │        noVNC            │ │
│  │  (Terminal) │  │ (WebSocket) │  │   (VNC over WebSocket)  │ │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘ │
└─────────┼────────────────┼─────────────────────┼───────────────┘
          │                │                     │
          │    HTTP/WS     │                     │ WS (VNC)
          │    :5000       │                     │ :6100+
          ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Flask Server (Backend)                     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │    Routes    │  │   WebSocket  │  │    X11 Manager       │  │
│  │  (REST API)  │  │   Handlers   │  │  (Xvfb/VNC/WS)       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                     │              │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌─────────┴────────────┐  │
│  │    Config    │  │ PTY Manager  │  │    Tmux Manager      │  │
│  │   Manager    │  │              │  │                      │  │
│  └──────────────┘  └──────┬───────┘  └──────────┬───────────┘  │
└────────────────────────────┼────────────────────┼──────────────┘
                             │                    │
                             ▼                    ▼
                    ┌────────────────┐   ┌────────────────┐
                    │   PTY/Shell    │   │     tmux       │
                    │   Processes    │   │    Server      │
                    └────────────────┘   └────────────────┘
```

## Backend Modules

### `server.py` - Application Entry Point

**Responsibilities:**
- Initialize Flask application with CORS and Socket.IO
- Register routes and WebSocket handlers
- Manage application lifecycle (startup/shutdown)
- Cleanup resources on exit (PTY connections, X11 displays)

**Key Design Decisions:**
- Uses eventlet for async WebSocket support (falls back to threading)
- Managers are initialized once and passed to routes/handlers
- Cleanup registered via `atexit` for graceful shutdown

### `modules/config.py` - Configuration Management

**Responsibilities:**
- Load/save persistent configuration from `config.json`
- Provide typed access to configuration values
- Define sensible defaults

**Configuration Values:**
```python
DEFAULT_CONFIG = {
    'tmux_socket': 'control-panel',  # tmux -L <socket>
    'session_prefix': 'cp-',          # prefix for session names
    'default_shell': '/bin/bash',
    'scrollback_limit': 50000
}
```

**Design Pattern:** Singleton-like config object passed to all managers.

### `modules/tmux_manager.py` - Tmux Operations

**Responsibilities:**
- Create/destroy tmux sessions
- Resize windows for terminal dimensions
- Send keys and signals to sessions
- Manage scrollback (copy-mode enter/exit, scroll up/down)
- Get scrollback content

**Key Methods:**
```python
create_session(name, cwd, command, socket)  # Create new session
destroy_session(name, socket)                # Kill session
resize_window(name, cols, rows, socket)      # Resize terminal
send_keys(name, keys, socket)                # Send input
scroll(name, command, lines, socket)         # Scroll operations
get_scrollback(name, lines, socket)          # Get history
```

**Design Pattern:** All tmux commands go through `_run()` method which handles socket selection and subprocess execution.

### `modules/pty_manager.py` - PTY Connection Management

**Responsibilities:**
- Spawn PTY processes attached to tmux sessions
- Manage reader threads for output streaming
- Track connected clients per session
- Handle connection/disconnection lifecycle

**Architecture:**
```
Client connects → get_or_create() → spawn_pty() → _start_reader()
                                         │
                                         ▼
                              tmux attach-session -t <session>
                                         │
                                         ▼
                              Reader thread → output callback
```

**Key Design Decisions:**
- One PTY per session (shared across multiple clients viewing same session)
- Reader thread continuously reads PTY output and calls callback
- Reference counting for cleanup (only close PTY when last client disconnects)

### `modules/x11_manager.py` - X11 Display Management

**Responsibilities:**
- Start virtual X11 displays (Xvfb)
- Start VNC server for each display (x11vnc)
- Start WebSocket proxy for browser access (websockify)
- Track display processes and ports
- Clean up processes on display stop

**Process Chain:**
```
Xvfb :100 -screen 0 1280x800x24
         │
         ▼
x11vnc -display :100 -rfbport 5900 -shared -forever
         │
         ▼
websockify 6100 localhost:5900
         │
         ▼
Browser connects via noVNC to ws://host:6100
```

**Port Allocation:**
- Display numbers: 100, 101, 102, ... (configurable base)
- VNC ports: 5900 + display_num (internal)
- WebSocket ports: 6100+ (external, browser-accessible)

**Design Pattern:** Process management with PID tracking for cleanup.

### `modules/commands_manager.py` - Quick Commands

**Responsibilities:**
- Store per-session quick commands
- Persist to config file
- CRUD operations for commands

**Data Structure:**
```python
{
    "session-name": [
        {"label": "Build", "command": "npm run build"},
        {"label": "Test", "command": "npm test"}
    ]
}
```

### `modules/routes.py` - REST API

**Responsibilities:**
- Define all HTTP endpoints
- Request validation and error handling
- Coordinate between managers

**Endpoint Groups:**
- `/api/sessions/*` - Session CRUD and operations
- `/api/x11/displays/*` - Display management
- `/api/config` - Configuration
- `/api/commands/*` - Quick commands

**Design Pattern:** Flask Blueprint-style organization within single file.

### `modules/websocket_handlers.py` - Real-time Communication

**Responsibilities:**
- Handle terminal I/O over WebSocket
- Manage session subscriptions
- Forward terminal input/output between client and PTY

**Events:**
```
Client → Server:
  - subscribe(session)    # Start receiving output
  - unsubscribe(session)  # Stop receiving output
  - input(session, keys)  # Send keystrokes
  - resize(session, cols, rows)  # Terminal resize
  - signal(session, sig)  # Send signal (SIGINT, etc)
  - scroll(session, cmd)  # Scroll operations

Server → Client:
  - subscribed(session)   # Confirmation
  - output(session, data) # Terminal output
  - error(message)        # Error notification
```

## Frontend Architecture

### State Management

Single global `state` object holds all application state:

```javascript
const state = {
    socket: null,        // Socket.IO connection
    terminal: null,      // xterm.js Terminal instance
    fitAddon: null,      // Terminal fit addon
    
    config: {            // Server configuration
        tmuxSocket: 'control-panel',
        sessionPrefix: 'cp-'
    },
    
    sessions: [],        // List of session names
    currentSession: null,
    customCommands: {},  // Per-session quick commands
    
    displays: [],        // X11 display info
    
    layout: 'terminals-only',  // Current layout mode
    
    guiPanels: [         // GUI panel states
        { displayNum, rfb, visible, detached, fullscreen },
        // ...
    ],
    
    panelSizes: {        // Resizable panel dimensions
        guiContainer: 50,
        terminal: 50,
        guiRows: [33.33, 33.33, 33.33]
    }
};
```

### DOM Caching

DOM elements cached in `dom` object at startup for performance:

```javascript
const dom = {};
function cacheDomElements() {
    dom.statusDot = document.getElementById('statusDot');
    dom.terminalPanel = document.getElementById('terminalPanel');
    // ...
}
```

### Component Organization

Frontend organized by feature:

1. **Configuration** - Load/save server config
2. **WebSocket** - Connection management, event handlers
3. **Terminal** - xterm.js setup, input/output handling
4. **Sessions** - CRUD operations, list rendering
5. **Quick Commands** - Command management UI
6. **X11 Displays** - Display creation, listing
7. **Layout** - Panel visibility, arrangement
8. **Resizing** - Drag-to-resize functionality
9. **GUI Panels** - VNC connection, fullscreen, detach

### External Libraries

| Library | Purpose | CDN |
|---------|---------|-----|
| xterm.js | Terminal emulator | unpkg |
| xterm-addon-fit | Auto-resize terminal | unpkg |
| xterm-addon-web-links | Clickable URLs | unpkg |
| Socket.IO | WebSocket client | cdnjs |
| noVNC | VNC over WebSocket | jsdelivr |

## Data Flow

### Terminal Input Flow
```
User types → xterm.js onData → Socket.IO 'input' event
    → WebSocket handler → PTY write → tmux session
```

### Terminal Output Flow
```
tmux output → PTY read → reader thread callback
    → Socket.IO 'output' emit → xterm.js write
```

### GUI Display Flow
```
Create display → Xvfb starts → x11vnc connects → websockify proxies
    → noVNC connects from browser → GUI visible in panel
```

## Design Principles

### 1. Separation of Concerns
Each module has a single responsibility. Managers don't know about HTTP or WebSocket - they just manage their domain.

### 2. Stateless Routes
Routes are stateless - all state lives in managers. This makes testing and debugging easier.

### 3. Graceful Degradation
- Works without X11 packages (terminal-only mode)
- Falls back to threading if eventlet unavailable
- GUI panels handle VNC disconnection gracefully

### 4. Resource Cleanup
- PTY processes cleaned up on disconnect
- X11 processes killed on display stop
- Cleanup on server shutdown via atexit

### 5. Client-Side State Persistence
- GUI connections survive layout changes
- Panel sizes remembered during session
- Detached panel positions maintained

## Maintenance Guide

### Adding a New Tmux Feature

1. Add method to `TmuxManager` class
2. Add route in `routes.py` if HTTP access needed
3. Add WebSocket event in `websocket_handlers.py` if real-time
4. Add frontend function and UI

### Adding a New Display Feature

1. Modify `X11Manager` class
2. Update display info structure if needed
3. Add route for HTTP control
4. Update frontend display list rendering

### Modifying Layouts

1. Update CSS in `main.css` for new layout styles
2. Modify `setLayout()` function in `app.js`
3. Add layout button in `index.html`
4. Update resizer logic if panel arrangement changes

### Debugging Tips

1. **Server logs**: Check terminal running `server.py`
2. **Browser console**: WebSocket errors, JS errors
3. **Network tab**: API call failures
4. **tmux directly**: `tmux -L control-panel ls` to verify sessions
5. **X11 processes**: `ps aux | grep -E 'Xvfb|x11vnc|websockify'`

## Future Improvements

Potential enhancements for future development:

- [ ] Session grouping/tagging
- [ ] Multiple terminal panels (split terminal view)
- [ ] Session templates (predefined configurations)
- [ ] Keyboard shortcuts for common actions
- [ ] Display resolution presets
- [ ] Session sharing (multiple users)
- [ ] Recording/playback of sessions
- [ ] Plugin system for extensions
- [ ] Dark/light theme toggle
- [ ] Mobile-responsive layout