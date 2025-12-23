"""
Tmux session/window management.

Architecture:
- One tmux SESSION per socket (named after the socket, e.g., "control-panel")
- Each "terminal" in the web UI is a WINDOW within that session
- Windows are named with the prefix (e.g., "cp-myterm")
- Attaching via CLI shows all windows: tmux -L <socket> attach
"""

import os
import subprocess
import signal
import time


class TmuxManager:
    """Manages tmux sessions and windows."""
    
    def __init__(self, config):
        self.config = config
    
    def _run(self, *args, socket=None):
        """Run a tmux command with the configured socket."""
        socket = socket or self.config.tmux_socket
        cmd = ["tmux", "-L", socket] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result
    
    def _ensure_session(self, socket=None):
        """Ensure the main session exists for this socket."""
        socket = socket or self.config.tmux_socket
        
        # Check if session exists
        result = self._run("has-session", "-t", socket, socket=socket)
        if result.returncode != 0:
            # Create the session with a default window (we'll rename/use it)
            result = self._run(
                "new-session", "-d", "-s", socket, 
                "-x", "80", "-y", "24",
                socket=socket
            )
            if result.returncode == 0:
                # Configure session
                self._run("set-option", "-t", socket, "mouse", "off", socket=socket)
                self._run("set-option", "-t", socket, "history-limit", 
                          str(self.config.scrollback_limit), socket=socket)
                self._run("set-option", "-t", socket, "default-terminal", "xterm-256color", socket=socket)
                # Rename the default window
                self._run("rename-window", "-t", f"{socket}:0", "_default", socket=socket)
        
        return result.returncode == 0
    
    def get_session_name(self, socket=None):
        """Get the session name for a socket (session name = socket name)."""
        return socket or self.config.tmux_socket
    
    def get_windows(self, socket=None):
        """List all windows with our prefix."""
        socket = socket or self.config.tmux_socket
        session = self.get_session_name(socket)
        
        result = self._run("list-windows", "-t", session, "-F", "#{window_name}", socket=socket)
        if result.returncode != 0:
            return []
        
        prefix = self.config.session_prefix
        return [line for line in result.stdout.strip().split('\n') 
                if line and line.startswith(prefix)]
    
    # Keep old method name for compatibility
    def get_sessions(self, socket=None):
        """List all windows (kept for API compatibility)."""
        return self.get_windows(socket=socket)
    
    def window_exists(self, name, socket=None):
        """Check if a window exists using direct tmux check."""
        socket = socket or self.config.tmux_socket
        session = self.get_session_name(socket)
        prefix = self.config.session_prefix
        full_name = name if name.startswith(prefix) else f"{prefix}{name}"
        target = f"{session}:{full_name}"
        
        # Direct check - list windows and filter by name
        result = self._run("list-windows", "-t", session, "-F", "#{window_name}", socket=socket)
        if result.returncode != 0:
            return False
        
        windows = result.stdout.strip().split('\n')
        return full_name in windows
    
    # Keep old method name for compatibility
    def session_exists(self, name, socket=None):
        """Check if a window exists (kept for API compatibility)."""
        return self.window_exists(name, socket=socket)
    
    def get_full_name(self, name):
        """Get the full window name with prefix."""
        prefix = self.config.session_prefix
        return name if name.startswith(prefix) else f"{prefix}{name}"
    
    def create_window(self, name, cwd=None, initial_cmd=None, socket=None):
        """Create a new window in the session."""
        socket = socket or self.config.tmux_socket
        session = self.get_session_name(socket)
        prefix = self.config.session_prefix
        full_name = f"{prefix}{name}"
        
        # Ensure session exists
        self._ensure_session(socket=socket)
        
        if self.window_exists(full_name, socket=socket):
            return False, "Window already exists"
        
        # Create new window
        cmd_args = ["new-window", "-t", session, "-n", full_name]
        if cwd and os.path.isdir(cwd):
            cmd_args.extend(["-c", cwd])
        
        result = self._run(*cmd_args, socket=socket)
        if result.returncode != 0:
            return False, result.stderr
        
        # Configure window
        self._run("set-window-option", "-t", f"{session}:{full_name}", 
                  "aggressive-resize", "on", socket=socket)
        
        # Run initial command if provided
        if initial_cmd:
            time.sleep(0.2)
            self._run("send-keys", "-t", f"{session}:{full_name}", 
                      initial_cmd, "Enter", socket=socket)
        
        return True, full_name
    
    # Keep old method name for compatibility
    def create_session(self, name, cwd=None, initial_cmd=None, socket=None):
        """Create a new window (kept for API compatibility)."""
        return self.create_window(name, cwd, initial_cmd, socket)
    
    def destroy_window(self, name, socket=None):
        """Destroy a window."""
        socket = socket or self.config.tmux_socket
        session = self.get_session_name(socket)
        full_name = self.get_full_name(name)
        
        result = self._run("kill-window", "-t", f"{session}:{full_name}", socket=socket)
        return result.returncode == 0
    
    # Keep old method name for compatibility  
    def destroy_session(self, name, socket=None):
        """Destroy a window (kept for API compatibility)."""
        return self.destroy_window(name, socket)
    
    def get_window_target(self, name, socket=None):
        """Get the tmux target string for a window."""
        socket = socket or self.config.tmux_socket
        session = self.get_session_name(socket)
        full_name = self.get_full_name(name)
        return f"{session}:{full_name}"
    
    def resize_window(self, name, cols, rows, socket=None):
        """Resize a tmux window."""
        target = self.get_window_target(name, socket)
        self._run("resize-window", "-t", target, "-x", str(cols), "-y", str(rows), socket=socket)
        self._run("refresh-client", "-t", target, socket=socket)
    
    def send_keys(self, name, keys, socket=None):
        """Send keys to a window."""
        target = self.get_window_target(name, socket)
        result = self._run("send-keys", "-t", target, "-l", keys, socket=socket)
        return result.returncode == 0
    
    def send_signal(self, name, sig, socket=None):
        """Send a signal to the foreground process in a window."""
        target = self.get_window_target(name, socket)
        
        result = self._run("display-message", "-t", target, "-p", "#{pane_pid}", socket=socket)
        if result.returncode != 0:
            return False
        
        try:
            pane_pid = int(result.stdout.strip())
            children = subprocess.run(["pgrep", "-P", str(pane_pid)], 
                                      capture_output=True, text=True)
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
    
    def set_environment(self, name, var, value=None, unset=False, socket=None):
        """Set or unset an environment variable in a session."""
        socket = socket or self.config.tmux_socket
        session = self.get_session_name(socket)
        if unset:
            self._run("set-environment", "-t", session, "-u", var, socket=socket)
        else:
            self._run("set-environment", "-t", session, var, value, socket=socket)
    
    def enter_copy_mode(self, name, socket=None):
        """Enter copy-mode for scrolling."""
        target = self.get_window_target(name, socket)
        self._run("copy-mode", "-t", target, socket=socket)
    
    def scroll(self, name, direction, lines=1, socket=None):
        """Scroll in copy-mode."""
        target = self.get_window_target(name, socket)
        if direction == 'up':
            self._run("send-keys", "-t", target, "-N", str(lines), "C-y", socket=socket)
        elif direction == 'down':
            self._run("send-keys", "-t", target, "-N", str(lines), "C-e", socket=socket)
        elif direction == 'page_up':
            self._run("send-keys", "-t", target, "C-b", socket=socket)
        elif direction == 'page_down':
            self._run("send-keys", "-t", target, "C-f", socket=socket)
        elif direction == 'top':
            self._run("send-keys", "-t", target, "g", socket=socket)
        elif direction == 'bottom':
            self._run("send-keys", "-t", target, "G", socket=socket)
        elif direction == 'exit':
            self._run("send-keys", "-t", target, "q", socket=socket)
    
    def get_scrollback(self, name, start_line=-10000, end_line=None, socket=None):
        """Get scrollback content from tmux's buffer."""
        target = self.get_window_target(name, socket)
        
        cmd_args = ["capture-pane", "-t", target, "-p", "-e", "-J"]
        if start_line is not None:
            cmd_args.extend(["-S", str(start_line)])
        if end_line is not None:
            cmd_args.extend(["-E", str(end_line)])
        
        result = self._run(*cmd_args, socket=socket)
        return result.stdout if result.returncode == 0 else ""
    
    def get_history_size(self, name, socket=None):
        """Get the number of lines in tmux's history buffer."""
        target = self.get_window_target(name, socket)
        result = self._run("display-message", "-t", target, "-p", "#{history_size}", socket=socket)
        if result.returncode == 0:
            try:
                return int(result.stdout.strip())
            except:
                pass
        return 0
    
    def select_window(self, name, socket=None):
        """Select/focus a window (useful when attaching via CLI)."""
        target = self.get_window_target(name, socket)
        self._run("select-window", "-t", target, socket=socket)