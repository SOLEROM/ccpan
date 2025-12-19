"""
PTY (Pseudo-terminal) management for tmux sessions.
"""

import os
import pty
import fcntl
import struct
import termios
import signal
import select
import threading
import time
import errno


class PtyManager:
    """Manages PTY connections to tmux sessions."""
    
    def __init__(self, tmux_manager, socketio):
        self.tmux_mgr = tmux_manager
        self.socketio = socketio
        self.connections = {}  # session_name -> connection info
    
    def _set_winsize(self, fd, rows, cols):
        """Set terminal window size."""
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    
    def _spawn_pty(self, session_name, cols=120, rows=40, socket=None):
        """Spawn a PTY that attaches to a tmux session."""
        full_name = self.tmux_mgr.get_full_name(session_name)
        socket = socket or self.tmux_mgr.config.tmux_socket
        
        # Resize tmux before attaching
        self.tmux_mgr.resize_window(full_name, cols, rows, socket=socket)
        time.sleep(0.05)
        
        pid, master_fd = pty.fork()
        
        if pid == 0:
            # Child process
            os.environ['TERM'] = 'xterm-256color'
            os.execlp('tmux', 'tmux', '-L', socket, 'attach', '-t', full_name)
        else:
            # Parent process
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self._set_winsize(master_fd, rows, cols)
            
            time.sleep(0.1)
            self.tmux_mgr.resize_window(full_name, cols, rows, socket=socket)
            
            return master_fd, pid
    
    def _start_reader(self, session_name, master_fd):
        """Start a thread that reads from PTY and emits to WebSocket."""
        full_name = self.tmux_mgr.get_full_name(session_name)
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
                                    self.socketio.emit('output', {
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
                if full_name in self.connections:
                    self.connections[full_name]['reader_stopped'] = True
        
        thread = threading.Thread(target=reader_thread, daemon=True)
        thread.start()
        return thread, stop_event
    
    def get_or_create(self, session_name, sid, cols=120, rows=40, socket=None):
        """Get existing PTY connection or create a new one."""
        full_name = self.tmux_mgr.get_full_name(session_name)
        
        if full_name in self.connections:
            conn = self.connections[full_name]
            conn['clients'].add(sid)
            if conn.get('reader_stopped', False):
                self.cleanup(full_name)
            else:
                return conn
        
        if not self.tmux_mgr.session_exists(full_name, socket=socket):
            return None
        
        master_fd, pid = self._spawn_pty(full_name, cols, rows, socket=socket)
        reader_thread, stop_event = self._start_reader(full_name, master_fd)
        
        self.connections[full_name] = {
            'master_fd': master_fd,
            'pid': pid,
            'reader_thread': reader_thread,
            'stop_event': stop_event,
            'clients': {sid},
            'reader_stopped': False,
            'socket': socket or self.tmux_mgr.config.tmux_socket
        }
        return self.connections[full_name]
    
    def cleanup(self, session_name):
        """Clean up PTY connection for a session."""
        full_name = self.tmux_mgr.get_full_name(session_name)
        
        if full_name not in self.connections:
            return
        
        conn = self.connections[full_name]
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
        
        del self.connections[full_name]
    
    def cleanup_all(self):
        """Clean up all PTY connections."""
        for session_name in list(self.connections.keys()):
            self.cleanup(session_name)
    
    def remove_client(self, session_name, sid):
        """Remove a client from a PTY connection."""
        full_name = self.tmux_mgr.get_full_name(session_name)
        
        if full_name not in self.connections:
            return
        
        conn = self.connections[full_name]
        conn['clients'].discard(sid)
        
        if not conn['clients']:
            def delayed_cleanup():
                time.sleep(5)
                if full_name in self.connections and not self.connections[full_name]['clients']:
                    self.cleanup(full_name)
            threading.Thread(target=delayed_cleanup, daemon=True).start()
    
    def send_keys(self, session_name, keys):
        """Send keys to the PTY."""
        full_name = self.tmux_mgr.get_full_name(session_name)
        
        if full_name in self.connections:
            try:
                os.write(self.connections[full_name]['master_fd'], keys.encode('utf-8'))
                return True
            except:
                pass
        
        return self.tmux_mgr.send_keys(full_name, keys)
    
    def resize(self, session_name, cols, rows, socket=None):
        """Resize both the PTY and tmux session."""
        full_name = self.tmux_mgr.get_full_name(session_name)
        
        if full_name in self.connections:
            try:
                self._set_winsize(self.connections[full_name]['master_fd'], rows, cols)
            except:
                pass
        
        self.tmux_mgr.resize_window(full_name, cols, rows, socket=socket)
