# Tmux Control Panel v4

A web-based terminal manager with X11 GUI display support. Manage multiple tmux sessions from your browser with the ability to run and view graphical applications.

![Layout Example](docs/layout-example.png)

## Features

- **Multi-Session Management**: Create, switch, and delete tmux sessions from a clean web interface
- **X11 GUI Support**: Run graphical applications (browsers, IDEs, GUI tools) in virtual X11 displays
- **Flexible Layouts**: Terminal-only or split views with 1-3 GUI panels
- **Resizable Panels**: Drag dividers to adjust panel sizes
- **Detachable GUI Panels**: Pop out GUI panels as floating windows
- **Fullscreen Mode**: Expand any GUI panel to fullscreen
- **Per-Tab Configuration**: Different browser tabs can connect to different tmux sockets
- **Quick Commands**: Save and execute frequently used commands per session
- **Scrollback Support**: Mouse wheel scrolling through terminal history via tmux copy-mode

## Requirements

### System Dependencies

```bash
# Ubuntu/Debian
sudo apt install tmux xvfb x11vnc websockify

# Fedora/RHEL
sudo dnf install tmux xorg-x11-server-Xvfb x11vnc websockify
```

### Python Dependencies

```bash
pip install flask flask-socketio flask-cors eventlet
```

## Quick Start

1. **Clone/Download** the project files

2. **Install dependencies**:
   ```bash
   pip install flask flask-socketio flask-cors eventlet
   sudo apt install tmux xvfb x11vnc websockify
   ```

3. **Run the server**:
   ```bash
   python server.py
   ```

4. **Open in browser**: http://127.0.0.1:5000

## Command Line Options

```bash
python server.py [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--public` | Make server accessible on local network (0.0.0.0). Default is localhost only. |
| `--port PORT` | Port to run server on (default: 5000) |
| `--open` | Open mode: shells start without requiring login. Without this flag, new shells require user authentication. |
| `--debug` | Enable debug logging for X11/GUI terminal operations. Useful for troubleshooting display binding issues on different hosts. |

### Examples

```bash
# Run on localhost with login required (default - most secure)
python server.py

# Run on localhost with open shells (no login required)
python server.py --open

# Run on local network with debug logging
python server.py --public --debug

# Run on custom port with all options
python server.py --port 8080 --public --open --debug
```

### Shell Modes

- **Login Mode** (default): Each new terminal session shows a login prompt asking for username and password. Uses `su -l` for authentication. This is the recommended mode for shared or public networks.
- **Open Mode** (`--open`): Shells start directly without login prompts, running as the user who started the server. Convenient for local development but less secure.

### Debug Mode

The `--debug` flag enables verbose logging for X11/GUI operations to stderr. This is particularly useful when:
- GUI applications fail to display
- Display binding doesn't work on certain hosts
- Troubleshooting Xvfb, x11vnc, or websockify issues

Debug output includes:
- Display creation/destruction events
- Port availability checks
- Process spawn information
- Environment variable setup
- Error details with stack traces

## Usage Guide

### Managing Sessions

1. Click **"+ New"** in the Sessions sidebar to create a new tmux session
2. Enter a session name (alphanumeric and hyphens only)
3. Optionally set a working directory and startup command
4. Click on a session in the list to connect to it
5. Use the **×** button to delete a session

### Using X11 GUI Displays

1. Click **"+ New"** in the X11 Displays sidebar
2. Enter a display number (starting from 100) and resolution
3. Select a layout with GUI panels (Terminal + 1/2/3 GUI)
4. Click **"Connect"** on a GUI panel and select a display
5. Click **"Bind"** to set the DISPLAY variable in your terminal
6. Run a GUI application: `firefox &` or `xeyes &`

### Layout Options

| Layout | Description |
|--------|-------------|
| **Terminal Only** | Full-width terminal, no GUI panels |
| **Terminal + 1 GUI** | Terminal on left, one GUI panel on right |
| **Terminal + 2 GUI** | Terminal on left, two stacked GUI panels on right |
| **Terminal + 3 GUI** | Terminal on left, three stacked GUI panels on right |

### GUI Panel Controls

| Button | Action |
|--------|--------|
| **Connect** | Connect panel to an X11 display |
| **Bind** | Inject `export DISPLAY=:XXX` into terminal |
| **⛶** | Toggle fullscreen mode (Esc to exit) |
| **⧉** | Detach/attach panel as floating window |
| **×** | Disconnect from display |

### Resizing Panels

- **Horizontal divider**: Drag left/right to resize terminal vs GUI area
- **Vertical dividers**: Drag up/down to resize GUI panels relative to each other
- **Detached panels**: Drag edges to resize, drag header to move

### Quick Commands

1. Select a session
2. Click **"+ Add"** in the quick commands bar
3. Enter a label and command
4. Click the button to execute the command in the current session

### Configuration

The header contains two configuration fields:

- **Socket**: tmux socket name (default: `control-panel`)
- **Prefix**: Session name prefix (default: `cp-`)

Different browser tabs can use different socket/prefix combinations to manage separate groups of sessions.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **Escape** | Exit fullscreen mode, close modals |
| **Enter** | Submit modal forms |
| **Mouse wheel** | Scroll through terminal history |

## Directory Structure

```
tmux-control-panel/
├── server.py              # Main Flask application
├── config.json            # Persistent configuration
├── modules/
│   ├── __init__.py
│   ├── config.py          # Configuration management
│   ├── tmux_manager.py    # Tmux operations
│   ├── pty_manager.py     # PTY connections
│   ├── x11_manager.py     # X11 display management
│   ├── commands_manager.py # Quick commands storage
│   ├── routes.py          # REST API endpoints
│   └── websocket_handlers.py # Real-time terminal I/O
├── templates/
│   └── index.html         # Main HTML template
└── static/
    ├── css/
    │   └── main.css       # Styles
    └── js/
        └── app.js         # Frontend application
```

## API Endpoints

### Sessions
- `GET /api/sessions` - List all sessions
- `POST /api/sessions` - Create new session
- `DELETE /api/sessions/<name>` - Delete session
- `POST /api/sessions/<name>/command` - Run command in session
- `POST /api/sessions/<name>/bind-display` - Bind display to session

### X11 Displays
- `GET /api/x11/displays` - List all displays
- `POST /api/x11/displays` - Create new display
- `DELETE /api/x11/displays/<num>` - Stop display

### Configuration
- `GET /api/config` - Get current config
- `POST /api/config` - Update config

### Commands
- `GET /api/commands` - Get all quick commands
- `POST /api/commands/<session>` - Add command to session
- `DELETE /api/commands/<session>/<index>` - Delete command

## Troubleshooting

### "Disconnected" status
- Check that the server is running
- Check browser console for WebSocket errors
- Ensure port 5000 is not blocked

### GUI not displaying
- Verify X11 packages are installed: `which Xvfb x11vnc websockify`
- Check that the display was created successfully in the sidebar
- Ensure you clicked "Connect" on the GUI panel
- Check server logs for X11-related errors

### Session not creating
- Check that tmux is installed: `which tmux`
- Check server logs for tmux errors
- Verify the session name contains only valid characters

### VNC connection failed
- The websockify port may be blocked by firewall
- Try refreshing the page and reconnecting
- Check that x11vnc is running: `ps aux | grep x11vnc`

