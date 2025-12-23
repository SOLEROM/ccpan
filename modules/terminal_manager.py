"""
Terminal Manager - Direct PTY terminal management without tmux.

Each terminal is a direct PTY process running a shell.
Terminals are ephemeral - they don't persist across server restarts.
"""

import os
import pty
import select
import signal
import struct
import fcntl
import termios
import subprocess
import threading
from collections import defaultdict


class TerminalManager:
    """Manages direct PTY terminals without tmux."""
    
    def __init__(self, config):
        self.config = config
        self.terminals = {}  # name -> terminal info
        self.lock = threading.Lock()
    
    def get_sessions(self):
        """Get list of active terminal names."""
        with self.lock:
            return list(self.terminals.keys())
    
    def session_exists(self, name):
        """Check if a terminal exists."""
        with self.lock:
            return name in self.terminals
    
    def get_full_name(self, name):
        """Get full terminal name with prefix."""
        prefix = self.config.session_prefix
        if name.startswith(prefix):
            return name
        return f"{prefix}{name}"
    
    def create_session(self, name, cwd=None, command=None):
        """Create a new terminal session."""
        full_name = self.get_full_name(name)
        
        with self.lock:
            if full_name in self.terminals:
                return False, "Terminal already exists"
        
        try:
            # Determine working directory
            work_dir = cwd if cwd and os.path.isdir(cwd) else os.path.expanduser('~')
            
            # Determine shell/command
            shell = command if command else self.config.default_shell
            
            # Create PTY
            master_fd, slave_fd = pty.openpty()
            
            # Set initial terminal size
            winsize = struct.pack('HHHH', 24, 80, 0, 0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
            
            # Fork process
            pid = os.fork()
            
            if pid == 0:
                # Child process
                os.close(master_fd)
                os.setsid()
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)
                
                os.chdir(work_dir)
                
                env = os.environ.copy()
                env['TERM'] = 'xterm-256color'
                
                if command:
                    os.execvpe('/bin/sh', ['/bin/sh', '-c', command], env)
                else:
                    os.execvpe(shell, [shell], env)
            else:
                # Parent process
                os.close(slave_fd)
                
                # Make master non-blocking
                flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
                fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                
                with self.lock:
                    self.terminals[full_name] = {
                        'name': full_name,
                        'pid': pid,
                        'master_fd': master_fd,
                        'cwd': work_dir,
                        'cols': 80,
                        'rows': 24,
                        'readers': [],
                        'reader_thread': None,
                        'output_callback': None,
                        'running': True
                    }
                
                return True, full_name
                
        except Exception as e:
            return False, str(e)
    
    def destroy_session(self, name):
        """Destroy a terminal session."""
        # Handle both prefixed and non-prefixed names
        prefix = self.config.session_prefix
        if name.startswith(prefix):
            full_name = name
        else:
            full_name = f"{prefix}{name}"
        
        with self.lock:
            if full_name not in self.terminals:
                return False
            
            term = self.terminals[full_name]
            term['running'] = False
            
            # Close master fd
            try:
                os.close(term['master_fd'])
            except:
                pass
            
            # Kill process
            try:
                os.kill(term['pid'], signal.SIGTERM)
                os.waitpid(term['pid'], os.WNOHANG)
            except:
                pass
            
            del self.terminals[full_name]
            return True
    
    def resize_window(self, name, cols, rows):
        """Resize a terminal window."""
        with self.lock:
            if name not in self.terminals:
                return False
            
            term = self.terminals[name]
            term['cols'] = cols
            term['rows'] = rows
            
            try:
                winsize = struct.pack('HHHH', rows, cols, 0, 0)
                fcntl.ioctl(term['master_fd'], termios.TIOCSWINSZ, winsize)
                # Send SIGWINCH to notify process of resize
                os.kill(term['pid'], signal.SIGWINCH)
                return True
            except:
                return False
    
    def send_keys(self, name, keys):
        """Send keys to a terminal."""
        with self.lock:
            if name not in self.terminals:
                return False
            
            term = self.terminals[name]
            try:
                os.write(term['master_fd'], keys.encode() if isinstance(keys, str) else keys)
                return True
            except:
                return False
    
    def send_signal(self, name, sig):
        """Send a signal to the terminal process."""
        with self.lock:
            if name not in self.terminals:
                return False
            
            term = self.terminals[name]
            try:
                sig_num = getattr(signal, f'SIG{sig.upper()}', None)
                if sig_num:
                    os.kill(term['pid'], sig_num)
                    return True
            except:
                pass
            return False
    
    def get_master_fd(self, name):
        """Get the master file descriptor for a terminal."""
        with self.lock:
            if name not in self.terminals:
                return None
            return self.terminals[name]['master_fd']
    
    def start_reader(self, name, callback):
        """Start a reader thread for terminal output."""
        with self.lock:
            if name not in self.terminals:
                return False
            
            term = self.terminals[name]
            if term['reader_thread'] and term['reader_thread'].is_alive():
                # Reader already running, just update callback
                term['output_callback'] = callback
                return True
            
            term['output_callback'] = callback
            term['running'] = True
            
            thread = threading.Thread(
                target=self._reader_loop,
                args=(name,),
                daemon=True
            )
            term['reader_thread'] = thread
            thread.start()
            return True
    
    def _reader_loop(self, name):
        """Background thread that reads terminal output."""
        while True:
            with self.lock:
                if name not in self.terminals:
                    break
                term = self.terminals[name]
                if not term['running']:
                    break
                master_fd = term['master_fd']
                callback = term['output_callback']
            
            try:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(master_fd, 4096)
                        if data and callback:
                            callback(name, data)
                        elif not data:
                            # EOF - process exited
                            break
                    except OSError:
                        break
            except Exception:
                break
    
    def cleanup_all(self):
        """Clean up all terminals."""
        names = list(self.terminals.keys())
        for name in names:
            self.destroy_session(name)