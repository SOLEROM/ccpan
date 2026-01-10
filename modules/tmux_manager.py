"""
Tmux session management.
"""

import os
import subprocess
import signal
import time
import sys
from modules.config import Config


def debug_log(message, *args):
    """Log debug messages when debug mode is enabled."""
    if Config.debug_mode:
        formatted = message % args if args else message
        print(f"[TMUX-DEBUG] {formatted}", file=sys.stderr, flush=True)


class TmuxManager:
    """Manages tmux sessions."""
    
    def __init__(self, config):
        self.config = config
    
    def _run(self, *args, socket=None):
        """Run a tmux command with the configured socket."""
        socket = socket or self.config.tmux_socket
        cmd = ["tmux", "-L", socket] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result
    
    def _get_login_command(self):
        """Return a command that implements a login prompt.
        
        Uses a bash script that prompts for username and uses 'su -l' to 
        authenticate and start a login shell. This approach works without
        requiring root privileges.
        """
        # Create a simple login wrapper script inline
        # This prompts for username, then uses su to authenticate
        login_script = '''bash -c '
while true; do
    echo ""
    echo "================================"
    echo "  Terminal Login Required"
    echo "================================"
    echo ""
    read -p "Username: " username
    if [ -n "$username" ]; then
        su -l "$username"
        exit_code=$?
        if [ $exit_code -eq 0 ]; then
            break
        else
            echo ""
            echo "Login failed. Please try again."
            sleep 1
        fi
    fi
done
'
'''
        return login_script.strip()
    
    def get_sessions(self, socket=None):
        """List all sessions with our prefix."""
        result = self._run("list-sessions", "-F", "#{session_name}", socket=socket)
        if result.returncode != 0:
            return []
        prefix = self.config.session_prefix
        return [line for line in result.stdout.strip().split('\n') 
                if line and line.startswith(prefix)]
    
    def session_exists(self, name, socket=None):
        """Check if a tmux session exists."""
        prefix = self.config.session_prefix
        full_name = name if name.startswith(prefix) else f"{prefix}{name}"
        return full_name in self.get_sessions(socket=socket)
    
    def get_full_name(self, name):
        """Get the full session name with prefix."""
        prefix = self.config.session_prefix
        return name if name.startswith(prefix) else f"{prefix}{name}"
    
    def create_session(self, name, cwd=None, initial_cmd=None, socket=None):
        """Create a new tmux session.
        
        The session shell behavior depends on Config.open_mode:
        - If True (--open): Shell starts without login (direct bash)
        - If False (default): Shell requires user login (via su -l)
        """
        prefix = self.config.session_prefix
        full_name = f"{prefix}{name}"
        
        if self.session_exists(full_name, socket=socket):
            return False, "Session already exists"
        
        # Create with small size - will be resized when client connects
        cmd_args = ["new-session", "-d", "-s", full_name, "-x", "80", "-y", "24"]
        if cwd and os.path.isdir(cwd):
            cmd_args.extend(["-c", cwd])
        
        # If not in open mode, start with a login prompt
        if not Config.open_mode:
            # Use our login wrapper script that prompts for user/pass via su
            login_cmd = self._get_login_command()
            cmd_args.append(login_cmd)
            debug_log("Creating session %s with login prompt (login mode)", full_name)
        else:
            debug_log("Creating session %s with direct shell (open mode)", full_name)
        
        result = self._run(*cmd_args, socket=socket)
        if result.returncode != 0:
            return False, result.stderr
        
        # Configure session
        self._run("set-option", "-t", full_name, "mouse", "off", socket=socket)
        self._run("set-option", "-t", full_name, "history-limit", 
                  str(self.config.scrollback_limit), socket=socket)
        self._run("set-window-option", "-t", full_name, "aggressive-resize", "on", socket=socket)
        self._run("set-option", "-t", full_name, "default-terminal", "xterm-256color", socket=socket)
        
        # Run initial command if provided (only in open mode, as login mode needs auth first)
        if initial_cmd and Config.open_mode:
            time.sleep(0.2)
            self._run("send-keys", "-t", full_name, initial_cmd, "Enter", socket=socket)
        
        return True, full_name
    
    def destroy_session(self, name, socket=None):
        """Destroy a tmux session."""
        full_name = self.get_full_name(name)
        result = self._run("kill-session", "-t", full_name, socket=socket)
        return result.returncode == 0
    
    def resize_window(self, name, cols, rows, socket=None):
        """Resize a tmux window."""
        full_name = self.get_full_name(name)
        self._run("resize-window", "-t", full_name, "-x", str(cols), "-y", str(rows), socket=socket)
        self._run("refresh-client", "-t", full_name, socket=socket)
    
    def send_keys(self, name, keys, socket=None):
        """Send keys to a session."""
        full_name = self.get_full_name(name)
        result = self._run("send-keys", "-t", full_name, "-l", keys, socket=socket)
        return result.returncode == 0
    
    def send_signal(self, name, sig, socket=None):
        """Send a signal to the foreground process in a session."""
        full_name = self.get_full_name(name)
        
        result = self._run("display-message", "-t", full_name, "-p", "#{pane_pid}", socket=socket)
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
        full_name = self.get_full_name(name)
        if unset:
            self._run("set-environment", "-t", full_name, "-u", var, socket=socket)
        else:
            self._run("set-environment", "-t", full_name, var, value, socket=socket)
    
    def enter_copy_mode(self, name, socket=None):
        """Enter copy-mode for scrolling."""
        full_name = self.get_full_name(name)
        self._run("copy-mode", "-t", full_name, socket=socket)
    
    def scroll(self, name, direction, lines=1, socket=None):
        """Scroll in copy-mode."""
        full_name = self.get_full_name(name)
        if direction == 'up':
            self._run("send-keys", "-t", full_name, "-N", str(lines), "C-y", socket=socket)
        elif direction == 'down':
            self._run("send-keys", "-t", full_name, "-N", str(lines), "C-e", socket=socket)
        elif direction == 'page_up':
            self._run("send-keys", "-t", full_name, "C-b", socket=socket)
        elif direction == 'page_down':
            self._run("send-keys", "-t", full_name, "C-f", socket=socket)
        elif direction == 'top':
            self._run("send-keys", "-t", full_name, "g", socket=socket)
        elif direction == 'bottom':
            self._run("send-keys", "-t", full_name, "G", socket=socket)
        elif direction == 'exit':
            self._run("send-keys", "-t", full_name, "q", socket=socket)
    
    def get_scrollback(self, name, start_line=-10000, end_line=None, socket=None):
        """Get scrollback content from tmux's buffer."""
        full_name = self.get_full_name(name)
        
        cmd_args = ["capture-pane", "-t", full_name, "-p", "-e", "-J"]
        if start_line is not None:
            cmd_args.extend(["-S", str(start_line)])
        if end_line is not None:
            cmd_args.extend(["-E", str(end_line)])
        
        result = self._run(*cmd_args, socket=socket)
        return result.stdout if result.returncode == 0 else ""
    
    def get_history_size(self, name, socket=None):
        """Get the number of lines in tmux's history buffer."""
        full_name = self.get_full_name(name)
        result = self._run("display-message", "-t", full_name, "-p", "#{history_size}", socket=socket)
        if result.returncode == 0:
            try:
                return int(result.stdout.strip())
            except:
                pass
        return 0