# Tmux Control Panel v1

A local web-based control panel for running and managing multiple long-running shell or Docker workloads in parallel. Each workload runs in its own real interactive shell backed by a dedicated tmux session.

**v1 Features: Now with xterm.js for a real terminal experience!**

## What's New in v1

- **xterm.js Terminal** - Full terminal emulator with proper escape sequence handling
- **Direct Typing** - Type directly in the terminal, no separate input box needed
- **Better Colors** - ANSI color support for colorful command output
- **Clickable Links** - URLs in terminal output are clickable
- **Proper Scrollback** - 10,000 lines of scrollback with smooth scrolling
- **Faster Updates** - 300ms refresh rate for smoother experience
- **Cursor Support** - Blinking cursor, proper cursor positioning

## Features

- **Multiple Sessions** - Run multiple workloads in parallel, each in its own tab
- **Real TTY** - Each session is a real tmux session with full PTY support
- **Live Output** - Terminal output with xterm.js rendering
- **Quick Commands** - Add custom command buttons per session (server-side storage)
- **Signal Control** - Send Ctrl+C, Ctrl+Z signals to running processes
- **Persistent** - Sessions survive browser refresh and server restart
- **Inspectable** - Attach directly to any session via tmux

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER (localhost:5000)                     │
│                                                                      │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐                               │
│   │  Tab 1  │ │  Tab 2  │ │  Tab 3  │    ← One tab per session      │
│   └─────────┘ └─────────┘ └─────────┘                               │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                    xterm.js Terminal                         │   │
│   │  $ npm run dev                                               │   │
│   │  > server@1.0.0 dev                                          │   │
│   │  > nodemon index.js                                          │   │
│   │  [nodemon] watching...                                       │   │
│   │  █                                                           │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│   [Quick Commands] [Signal Buttons]                                 │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/JSON API (polling @ 300ms)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FLASK SERVER (Python)                             │
│                                                                      │
│   • Creates/destroys tmux sessions                                  │
│   • Sends keystrokes (raw mode for xterm.js)                        │
│   • Captures session output                                         │
│   • Stores custom commands (commands.json)                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ tmux CLI commands
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    TMUX SERVER (socket: control-panel)               │
│                                                                      │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│   │ cp-session1  │  │ cp-session2  │  │ cp-session3  │              │
│   │  [bash/PTY]  │  │  [npm/PTY]   │  │ [python/PTY] │              │
│   │ [scrollback] │  │ [scrollback] │  │ [scrollback] │              │
│   └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

Ubuntu 22.04 (or similar Linux):

```bash
sudo apt update
sudo apt install -y tmux python3 python3-venv python3-pip
```

## Quick Setup

```bash
cd tmux-control-panel-v1

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install flask flask-cors

# Run the server
python server.py
```

Open **http://127.0.0.1:5000** in your browser.

## Project Structure

```
tmux-control-panel-v1/
├── server.py           # Flask backend
├── requirements.txt    # Python dependencies
├── setup.sh            # Quick setup script
├── commands.json       # Custom commands storage (auto-created)
├── README.md
├── venv/               # Virtual environment
└── templates/
    └── index.html      # Web UI with xterm.js
```

## Usage

### Creating Sessions

1. Click **"+ New Session"**
2. Enter a session name
3. Optionally set a working directory
4. Optionally set an initial command
5. Click **"Create"**

### Using the Terminal

- **Click the terminal** to focus it
- **Type directly** - keystrokes go straight to the shell
- **Arrow keys work** - command history, cursor movement
- **Tab completion works** - just press Tab
- **Ctrl+C** - interrupt running process
- **Ctrl+D** - send EOF
- **Ctrl+L** - clear screen

### Quick Commands & Buttons

- **⏹ Stop** - Sends Ctrl+C (SIGINT)
- **⏸ Suspend** - Sends Ctrl+Z (SIGSTOP)
- **🔄 Clear** - Runs `clear` command
- **+ Add** - Create custom command buttons

### Custom Quick Commands

Commands are stored server-side in `commands.json`:
- Persist across browser refresh ✅
- Persist across server restart ✅
- Work from any browser/device ✅

## Direct tmux Access

```bash
# List sessions
tmux -L control-panel list-sessions

# Attach to a session
tmux -L control-panel attach -t cp-SESSION_NAME

# Detach: Ctrl+B, then D
```

## API Reference

### Sessions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | GET | List all sessions |
| `/api/sessions` | POST | Create new session |
| `/api/sessions/<n>` | DELETE | Destroy session |
| `/api/sessions/<n>/output` | GET | Get terminal output |
| `/api/sessions/<n>/send` | POST | Send keystrokes (supports `raw` mode) |
| `/api/sessions/<n>/signal` | POST | Send signal |
| `/api/sessions/<n>/command` | POST | Run a command |

### Custom Commands

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/commands` | GET | Get all custom commands |
| `/api/commands/<session>` | GET | Get commands for a session |
| `/api/commands/<session>` | POST | Add a command |
| `/api/commands/<session>/<index>` | DELETE | Delete a command |

### Raw Key Mode

v1 adds `raw` mode for xterm.js integration:

```bash
# Raw mode sends keys exactly as received (escape sequences, etc.)
curl -X POST http://127.0.0.1:5000/api/sessions/cp-test/send \
  -H "Content-Type: application/json" \
  -d '{"keys": "ls -la\r", "raw": true}'
```

## Configuration

Edit `server.py`:

```python
TMUX_SOCKET = "control-panel"  # tmux socket name
SCROLLBACK_LINES = 2000        # Lines to capture
SESSION_PREFIX = "cp-"         # Session prefix
COMMANDS_FILE = "commands.json" # Commands storage
```

## xterm.js Configuration

The terminal is configured in `index.html`:

```javascript
const term = new Terminal({
    cursorBlink: true,
    fontSize: 14,
    fontFamily: 'Consolas, "Courier New", monospace',
    scrollback: 10000,
    theme: {
        background: '#0a0a0a',
        foreground: '#c8c8c8',
        cursor: '#4ecca3',
        // ... colors
    }
});
```

## Troubleshooting

### Terminal not responding to input
- Click the terminal to focus it
- Check browser console for errors

### Colors not showing
- Make sure the command outputs ANSI colors
- Try: `ls --color=always`

### Slow/laggy updates
- Check network latency
- Reduce refresh interval if needed

## Security Notes

⚠️ **Important:**
- Server binds to `127.0.0.1` only
- Do NOT expose without authentication
- Sessions run with server permissions

## Dependencies

- **Server**: Flask, Flask-CORS
- **Client**: xterm.js (loaded from CDN)
  - xterm.js 5.3.0
  - xterm-addon-fit 0.8.0
  - xterm-addon-web-links 0.9.0

## License

MIT License

---

## Changelog

### v1.0.0
- Upgraded terminal to xterm.js
- Added raw key input mode
- Direct typing in terminal
- ANSI color support
- Clickable links
- 10,000 line scrollback
- Faster 300ms refresh rate

### v0.1.0
- Initial release
- Basic terminal display
- Session management
- Quick commands with server storage
