# Tmux Control Panel v2

A web-based terminal interface for managing tmux sessions with real-time WebSocket streaming and mouse scroll support.

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![License](https://img.shields.io/badge/license-MIT-gray)

## Features

- **Real-time Terminal Streaming** - WebSocket-based output with <10ms latency
- **Shared Sessions** - Web UI and CLI access the same tmux session
- **Mouse Scroll Support** - Scroll through history using tmux copy-mode
- **Session Management** - Create, delete, and switch between sessions
- **Quick Commands** - Save and execute frequently used commands
- **Signal Control** - Send SIGINT, SIGTERM, etc. to running processes
- **Modern UI** - Clean dark theme with xterm.js terminal emulator

## Quick Start

### Prerequisites

- Python 3.8+
- tmux
- Modern web browser

### Installation

```bash
# Clone or download the project
cd ccpan

# Run setup script
chmod +x setup.sh
./setup.sh

# Or install manually
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running

```bash
# Activate virtual environment
source venv/bin/activate

# Start the server
python server_pty.py
```

Open http://127.0.0.1:5000 in your browser.

## Usage

### Web Interface

1. **Create a Session** - Click "New Session", enter a name, optional working directory and initial command
2. **Select a Session** - Click on a session in the left sidebar to connect
3. **Type Commands** - Terminal input is sent to the tmux session in real-time
4. **Scroll History** - Use mouse wheel to scroll up (enters tmux copy-mode), type any key to exit
5. **Quick Commands** - Add frequently used commands for one-click execution
6. **Send Signals** - Use Stop (SIGINT), Suspend (SIGTSTP), or Kill buttons

### CLI Access

You can attach to any session from the command line:

```bash
# List sessions
tmux -L control-panel list-sessions

# Attach to a session
tmux -L control-panel attach -t cp-<session-name>

# Detach from session
# Press: Ctrl+B, then D
```

**Note:** Web UI and CLI share the same tmux session - changes in one appear in the other.

## Configuration

Edit `server_pty.py` to change:

```python
TMUX_SOCKET = "control-panel"  # tmux socket name
SESSION_PREFIX = "cp-"         # Prefix for session names
COMMANDS_FILE = "commands.json" # Quick commands storage
```

The server runs on `127.0.0.1:5000` by default (local only for security).

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions` | List all sessions |
| POST | `/api/sessions` | Create session `{name, cwd?, command?}` |
| DELETE | `/api/sessions/<n>` | Delete session |
| POST | `/api/sessions/<n>/command` | Run command in session |
| GET | `/api/commands` | Get quick commands |
| POST | `/api/commands` | Add quick command |
| DELETE | `/api/commands/<session>/<index>` | Delete quick command |

### WebSocket Events

**Client → Server:**
- `subscribe` - Connect to session `{session, cols, rows}`
- `unsubscribe` - Disconnect from session `{session}`
- `input` - Send keystrokes `{session, keys}`
- `resize` - Resize terminal `{session, cols, rows}`
- `signal` - Send signal `{session, signal}`
- `scroll` - Scroll control `{session, command, lines?}`

**Server → Client:**
- `connected` - Connection acknowledged
- `subscribed` - Subscribed to session
- `output` - Terminal output `{session, data}`
- `error` - Error message `{message}`

## File Structure

```
ccpan/
├── server_pty.py      # Main server (Flask + Socket.IO + PTY)
├── templates/
│   └── index.html     # Web UI (single-page application)
├── requirements.txt   # Python dependencies
├── setup.sh          # Installation script
├── commands.json     # Quick commands storage (auto-created)
├── README.md         # This file
└── ARCH.md           # Architecture documentation
```

## Troubleshooting

### "Disconnected" status
- Check if server is running
- Check browser console for errors (F12)
- Ensure eventlet is installed: `pip install eventlet`

### Display offset/corruption
- Delete session and create new one
- Kill tmux server: `tmux -L control-panel kill-server`
- Restart Python server

### Scroll not working
- Make sure you scroll up first to enter copy-mode
- Type any key to exit copy-mode and return to live view

### Session not accessible from CLI
- Use the correct socket: `tmux -L control-panel attach -t cp-<n>`
- Check session exists: `tmux -L control-panel list-sessions`

## Dependencies

- Flask - Web framework
- Flask-SocketIO - WebSocket support
- Flask-CORS - Cross-origin support
- eventlet - Async networking
- xterm.js - Terminal emulator (CDN)
- Socket.IO client (CDN)

## Security Notes

- Server binds to `127.0.0.1` only (not accessible from network)
- No authentication - designed for local development use
- For production deployment, add authentication and use HTTPS

## License

MIT License - feel free to use and modify.

## See Also

- [ARCH.md](ARCH.md) - Detailed architecture documentation
- [tmux manual](https://man7.org/linux/man-pages/man1/tmux.1.html)
- [xterm.js](https://xtermjs.org/)
- [Socket.IO](https://socket.io/)