"""
X11 display management using Xvfb, x11vnc, and websockify.
"""

import os
import subprocess
import signal
import time
import shutil
import socket as sock


class X11Manager:
    """Manages X11 virtual displays for GUI applications."""
    
    DISPLAY_BASE = 99
    
    def __init__(self):
        self.displays = {}  # display_num -> display info
    
    def _get_clean_env(self, display):
        """Get a clean environment for X11 processes without Wayland."""
        clean_env = os.environ.copy()
        clean_env.pop('WAYLAND_DISPLAY', None)
        clean_env.pop('XDG_SESSION_TYPE', None)
        clean_env['DISPLAY'] = display
        clean_env['GDK_BACKEND'] = 'x11'
        clean_env['QT_QPA_PLATFORM'] = 'xcb'
        return clean_env
    
    def _find_free_display(self, preferred=None):
        """Find a free X display number, optionally trying preferred first."""
        if preferred is not None:
            lock_file = f"/tmp/.X{preferred}-lock"
            socket_file = f"/tmp/.X11-unix/X{preferred}"
            if not os.path.exists(lock_file) and not os.path.exists(socket_file):
                return preferred
        
        for display_num in range(self.DISPLAY_BASE, self.DISPLAY_BASE + 100):
            lock_file = f"/tmp/.X{display_num}-lock"
            socket_file = f"/tmp/.X11-unix/X{display_num}"
            if not os.path.exists(lock_file) and not os.path.exists(socket_file):
                return display_num
        return None
    
    def _find_free_port(self, start, end):
        """Find a free port in range."""
        for port in range(start, end):
            try:
                s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
                s.bind(('127.0.0.1', port))
                s.close()
                return port
            except OSError:
                continue
        return None
    
    def check_dependencies(self):
        """Check if required X11 tools are installed."""
        required = ['Xvfb', 'x11vnc', 'websockify']
        missing = [cmd for cmd in required if not shutil.which(cmd)]
        return missing
    
    def start_display(self, display_num=None, width=1280, height=800):
        """
        Start an X11 virtual display.
        
        Args:
            display_num: Preferred display number (e.g., 99 for :99). If None, auto-assign.
            width: Display width
            height: Display height
            
        Returns:
            (display_info, error) tuple
        """
        missing = self.check_dependencies()
        if missing:
            return None, f"Missing dependencies: {', '.join(missing)}. Install with: sudo apt install xvfb x11vnc websockify"
        
        # Find display number
        actual_display_num = self._find_free_display(preferred=display_num)
        if actual_display_num is None:
            return None, "No free X display available"
        
        # Check if this display is already managed by us
        if actual_display_num in self.displays:
            info = self.displays[actual_display_num]
            return {
                'display': info['display'],
                'display_num': actual_display_num,
                'ws_port': info['ws_port'],
                'width': info['width'],
                'height': info['height']
            }, None
        
        # Find ports
        vnc_port = self._find_free_port(5900, 5999)
        if vnc_port is None:
            return None, "No free VNC port available"
        
        ws_port = self._find_free_port(6080, 6180)
        if ws_port is None:
            return None, "No free WebSocket port available"
        
        display = f":{actual_display_num}"
        clean_env = self._get_clean_env(display)
        
        try:
            # Start Xvfb
            xvfb_cmd = [
                "Xvfb", display,
                "-screen", "0", f"{width}x{height}x24",
                "-ac",
                "+extension", "GLX"
            ]
            xvfb_proc = subprocess.Popen(
                xvfb_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_env
            )
            time.sleep(0.5)
            
            if xvfb_proc.poll() is not None:
                _, stderr = xvfb_proc.communicate()
                return None, f"Failed to start Xvfb: {stderr.decode()}"
            
            # Start x11vnc
            vnc_cmd = [
                "x11vnc",
                "-display", display,
                "-rfbport", str(vnc_port),
                "-nopw",
                "-forever",
                "-shared",
                "-noxdamage",
                "-wait", "5",
                "-defer", "5"
            ]
            vnc_proc = subprocess.Popen(
                vnc_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_env
            )
            time.sleep(0.5)
            
            if vnc_proc.poll() is not None:
                _, stderr = vnc_proc.communicate()
                xvfb_proc.terminate()
                return None, f"Failed to start x11vnc: {stderr.decode()}"
            
            # Start websockify
            ws_cmd = [
                "websockify",
                str(ws_port),
                f"127.0.0.1:{vnc_port}"
            ]
            ws_proc = subprocess.Popen(
                ws_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(0.3)
            
            if ws_proc.poll() is not None:
                _, stderr = ws_proc.communicate()
                vnc_proc.terminate()
                xvfb_proc.terminate()
                return None, f"Failed to start websockify: {stderr.decode()}"
            
            # Store display info
            self.displays[actual_display_num] = {
                'display': display,
                'display_num': actual_display_num,
                'xvfb_pid': xvfb_proc.pid,
                'vnc_pid': vnc_proc.pid,
                'vnc_port': vnc_port,
                'ws_pid': ws_proc.pid,
                'ws_port': ws_port,
                'width': width,
                'height': height,
                'sessions': set()  # Sessions using this display
            }
            
            return {
                'display': display,
                'display_num': actual_display_num,
                'ws_port': ws_port,
                'width': width,
                'height': height
            }, None
            
        except Exception as e:
            return None, str(e)
    
    def stop_display(self, display_num):
        """Stop an X11 display."""
        if display_num not in self.displays:
            return False, "Display not found"
        
        info = self.displays[display_num]
        
        # Kill processes
        for pid_key in ['ws_pid', 'vnc_pid', 'xvfb_pid']:
            pid = info.get(pid_key)
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(0.1)
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception:
                    pass
        
        del self.displays[display_num]
        return True, None
    
    def get_display(self, display_num):
        """Get display info."""
        if display_num not in self.displays:
            return None
        
        info = self.displays[display_num]
        
        # Check if still alive
        try:
            os.kill(info['xvfb_pid'], 0)
        except ProcessLookupError:
            self.stop_display(display_num)
            return None
        
        return {
            'display': info['display'],
            'display_num': display_num,
            'ws_port': info['ws_port'],
            'width': info['width'],
            'height': info['height']
        }
    
    def list_displays(self):
        """List all active displays."""
        result = []
        dead = []
        
        for display_num, info in self.displays.items():
            try:
                os.kill(info['xvfb_pid'], 0)
                result.append({
                    'display': info['display'],
                    'display_num': display_num,
                    'ws_port': info['ws_port'],
                    'width': info['width'],
                    'height': info['height']
                })
            except ProcessLookupError:
                dead.append(display_num)
        
        for d in dead:
            self.stop_display(d)
        
        return result
    
    def resize_display(self, display_num, width, height):
        """Resize a display by restarting it."""
        if display_num not in self.displays:
            return None, "Display not found"
        
        self.stop_display(display_num)
        return self.start_display(display_num=display_num, width=width, height=height)
    
    def cleanup_all(self):
        """Clean up all displays."""
        for display_num in list(self.displays.keys()):
            self.stop_display(display_num)
    
    def get_env_setup_commands(self, display_num):
        """Get shell commands to set up environment for a display."""
        if display_num not in self.displays:
            return None
        
        display = self.displays[display_num]['display']
        return (
            f"export DISPLAY={display} && "
            f"unset WAYLAND_DISPLAY && "
            f"export GDK_BACKEND=x11 && "
            f"export QT_QPA_PLATFORM=xcb && "
            f"export LIBGL_ALWAYS_SOFTWARE=1 && "
            f"export GALLIUM_DRIVER=llvmpipe && "
            f"export MESA_GL_VERSION_OVERRIDE=3.3"
        )
