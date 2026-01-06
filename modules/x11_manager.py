"""
X11 display management using Xvfb, x11vnc, and websockify.

Fixed display configuration:
  - GUI Panel 1: Display :100
  - GUI Panel 2: Display :101
  - GUI Panel 3: Display :102
"""

import os
import subprocess
import signal
import time
import shutil
import socket as sock


class X11Manager:
    """Manages X11 virtual displays for GUI applications."""
    
    # Fixed display numbers - GUI panel index maps directly to display
    FIXED_DISPLAYS = {
        0: 100,  # GUI Panel 1 -> :100
        1: 101,  # GUI Panel 2 -> :101
        2: 102,  # GUI Panel 3 -> :102
    }
    
    FIXED_VNC_PORTS = {
        100: 5900,
        101: 5901,
        102: 5902,
    }
    
    FIXED_WS_PORTS = {
        100: 6100,
        101: 6101,
        102: 6102,
    }
    
    def __init__(self):
        self.displays = {}
    
    def _get_clean_env(self, display):
        clean_env = os.environ.copy()
        clean_env.pop('WAYLAND_DISPLAY', None)
        clean_env.pop('XDG_SESSION_TYPE', None)
        clean_env['DISPLAY'] = display
        clean_env['GDK_BACKEND'] = 'x11'
        clean_env['QT_QPA_PLATFORM'] = 'xcb'
        return clean_env
    
    def _is_display_available(self, display_num):
        lock_file = f"/tmp/.X{display_num}-lock"
        socket_file = f"/tmp/.X11-unix/X{display_num}"
        return not os.path.exists(lock_file) and not os.path.exists(socket_file)
    
    def _is_port_available(self, port):
        try:
            s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            return True
        except OSError:
            return False
    
    def get_display_for_panel(self, panel_index):
        return self.FIXED_DISPLAYS.get(panel_index)
    
    def get_panel_for_display(self, display_num):
        for panel, num in self.FIXED_DISPLAYS.items():
            if num == display_num:
                return panel
        return None
    
    def check_dependencies(self):
        required = ['Xvfb', 'x11vnc', 'websockify']
        return [cmd for cmd in required if not shutil.which(cmd)]
    
    def start_display(self, display_num=None, panel_index=None, width=1280, height=800, depth=24):
        missing = self.check_dependencies()
        if missing:
            return None, f"Missing dependencies: {', '.join(missing)}. Install with: sudo apt install xvfb x11vnc websockify"
        
        if display_num is not None:
            if display_num not in self.FIXED_DISPLAYS.values():
                return None, f"Invalid display number {display_num}. Must be 100, 101, or 102"
            actual_display_num = display_num
        elif panel_index is not None:
            if panel_index not in self.FIXED_DISPLAYS:
                return None, f"Invalid panel index {panel_index}. Must be 0, 1, or 2"
            actual_display_num = self.FIXED_DISPLAYS[panel_index]
        else:
            return None, "Must specify display_num or panel_index"
        
        if actual_display_num in self.displays:
            info = self.displays[actual_display_num]
            return {
                'display': info['display'],
                'display_num': actual_display_num,
                'panel_index': self.get_panel_for_display(actual_display_num),
                'ws_port': info['ws_port'],
                'width': info['width'],
                'height': info['height']
            }, None
        
        vnc_port = self.FIXED_VNC_PORTS[actual_display_num]
        ws_port = self.FIXED_WS_PORTS[actual_display_num]
        
        if not self._is_port_available(vnc_port):
            return None, f"VNC port {vnc_port} is in use"
        if not self._is_port_available(ws_port):
            return None, f"WebSocket port {ws_port} is in use"
        if not self._is_display_available(actual_display_num):
            return None, f"Display :{actual_display_num} is in use by another process"
        
        display = f":{actual_display_num}"
        clean_env = self._get_clean_env(display)
        
        try:
            xvfb_cmd = [
                "Xvfb", display,
                "-screen", "0", f"{width}x{height}x{depth}",
                "-ac", "+extension", "GLX", "+extension", "RENDER", "-nolisten", "tcp"
            ]
            xvfb_proc = subprocess.Popen(xvfb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=clean_env)
            time.sleep(0.5)
            
            if xvfb_proc.poll() is not None:
                _, stderr = xvfb_proc.communicate()
                return None, f"Failed to start Xvfb: {stderr.decode()}"
            
            vnc_cmd = [
                "x11vnc", "-display", display,
                "-rfbport", str(vnc_port),
                "-nopw", "-forever", "-shared", "-noxdamage", "-wait", "5", "-defer", "5"
            ]
            vnc_proc = subprocess.Popen(vnc_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=clean_env)
            time.sleep(0.5)
            
            if vnc_proc.poll() is not None:
                _, stderr = vnc_proc.communicate()
                xvfb_proc.terminate()
                return None, f"Failed to start x11vnc: {stderr.decode()}"
            
            ws_cmd = ["websockify", str(ws_port), f"127.0.0.1:{vnc_port}"]
            ws_proc = subprocess.Popen(ws_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.3)
            
            if ws_proc.poll() is not None:
                _, stderr = ws_proc.communicate()
                vnc_proc.terminate()
                xvfb_proc.terminate()
                return None, f"Failed to start websockify: {stderr.decode()}"
            
            self.displays[actual_display_num] = {
                'display': display,
                'display_num': actual_display_num,
                'panel_index': self.get_panel_for_display(actual_display_num),
                'xvfb_pid': xvfb_proc.pid,
                'vnc_pid': vnc_proc.pid,
                'vnc_port': vnc_port,
                'ws_pid': ws_proc.pid,
                'ws_port': ws_port,
                'width': width,
                'height': height,
                'sessions': set()
            }
            
            return {
                'display': display,
                'display_num': actual_display_num,
                'panel_index': self.get_panel_for_display(actual_display_num),
                'ws_port': ws_port,
                'width': width,
                'height': height
            }, None
            
        except Exception as e:
            return None, str(e)
    
    def start_display_for_panel(self, panel_index, width=1280, height=800):
        return self.start_display(panel_index=panel_index, width=width, height=height)
    
    def stop_display(self, display_num):
        if display_num not in self.displays:
            return False, "Display not found"
        
        info = self.displays[display_num]
        
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
        if display_num not in self.displays:
            return None
        
        info = self.displays[display_num]
        
        try:
            os.kill(info['xvfb_pid'], 0)
        except ProcessLookupError:
            self.stop_display(display_num)
            return None
        
        return {
            'display': info['display'],
            'display_num': display_num,
            'panel_index': self.get_panel_for_display(display_num),
            'ws_port': info['ws_port'],
            'width': info['width'],
            'height': info['height']
        }
    
    def list_displays(self):
        result = []
        dead = []
        
        for display_num, info in self.displays.items():
            try:
                os.kill(info['xvfb_pid'], 0)
                result.append({
                    'display': info['display'],
                    'display_num': display_num,
                    'panel_index': self.get_panel_for_display(display_num),
                    'ws_port': info['ws_port'],
                    'width': info['width'],
                    'height': info['height']
                })
            except ProcessLookupError:
                dead.append(display_num)
        
        for d in dead:
            self.stop_display(d)
        
        return result
    
    def get_fixed_config(self):
        return {
            'panels': [
                {
                    'panel_index': i,
                    'display_num': self.FIXED_DISPLAYS[i],
                    'display': f":{self.FIXED_DISPLAYS[i]}",
                    'vnc_port': self.FIXED_VNC_PORTS[self.FIXED_DISPLAYS[i]],
                    'ws_port': self.FIXED_WS_PORTS[self.FIXED_DISPLAYS[i]],
                }
                for i in range(3)
            ]
        }
    
    def resize_display(self, display_num, width, height):
        if display_num not in self.displays:
            return None, "Display not found"
        self.stop_display(display_num)
        return self.start_display(display_num=display_num, width=width, height=height)
    
    def cleanup_all(self):
        for display_num in list(self.displays.keys()):
            self.stop_display(display_num)
    
    def get_env_setup_commands(self, display_num):
        if display_num not in self.displays:
            return None
        display = self.displays[display_num]['display']
        return (
            f"export DISPLAY={display} && "
            f"unset WAYLAND_DISPLAY && "
            f"export GDK_BACKEND=x11 && "
            f"export QT_QPA_PLATFORM=xcb"
        )
    
    def get_env_dict(self, display_num):
        if display_num not in self.displays:
            return None
        display = self.displays[display_num]['display']
        return self._get_clean_env(display)