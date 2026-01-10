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
import sys

# Import Config for debug mode check
from modules.config import Config


def debug_log(message, *args):
    """Log debug messages when debug mode is enabled."""
    if Config.debug_mode:
        formatted = message % args if args else message
        print(f"[X11-DEBUG] {formatted}", file=sys.stderr, flush=True)


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
        debug_log("X11Manager initialized")
    
    def _get_clean_env(self, display):
        debug_log("Creating clean environment for display %s", display)
        clean_env = os.environ.copy()
        clean_env.pop('WAYLAND_DISPLAY', None)
        clean_env.pop('XDG_SESSION_TYPE', None)
        clean_env['DISPLAY'] = display
        clean_env['GDK_BACKEND'] = 'x11'
        clean_env['QT_QPA_PLATFORM'] = 'xcb'
        debug_log("Clean env created: DISPLAY=%s, GDK_BACKEND=x11, QT_QPA_PLATFORM=xcb", display)
        return clean_env
    
    def _is_display_available(self, display_num):
        lock_file = f"/tmp/.X{display_num}-lock"
        socket_file = f"/tmp/.X11-unix/X{display_num}"
        lock_exists = os.path.exists(lock_file)
        socket_exists = os.path.exists(socket_file)
        available = not lock_exists and not socket_exists
        debug_log("Display :%d availability check: lock_file=%s (exists=%s), socket_file=%s (exists=%s), available=%s",
                  display_num, lock_file, lock_exists, socket_file, socket_exists, available)
        return available
    
    def _is_port_available(self, port):
        try:
            s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            debug_log("Port %d is available", port)
            return True
        except OSError as e:
            debug_log("Port %d is NOT available: %s", port, e)
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
        missing = [cmd for cmd in required if not shutil.which(cmd)]
        debug_log("Dependency check: required=%s, missing=%s", required, missing)
        return missing
    
    def start_display(self, display_num=None, panel_index=None, width=1280, height=800, depth=24):
        debug_log("start_display called: display_num=%s, panel_index=%s, width=%d, height=%d, depth=%d",
                  display_num, panel_index, width, height, depth)
        
        missing = self.check_dependencies()
        if missing:
            error_msg = f"Missing dependencies: {', '.join(missing)}. Install with: sudo apt install xvfb x11vnc websockify"
            debug_log("ERROR: %s", error_msg)
            return None, error_msg
        
        if display_num is not None:
            if display_num not in self.FIXED_DISPLAYS.values():
                error_msg = f"Invalid display number {display_num}. Must be 100, 101, or 102"
                debug_log("ERROR: %s", error_msg)
                return None, error_msg
            actual_display_num = display_num
        elif panel_index is not None:
            if panel_index not in self.FIXED_DISPLAYS:
                error_msg = f"Invalid panel index {panel_index}. Must be 0, 1, or 2"
                debug_log("ERROR: %s", error_msg)
                return None, error_msg
            actual_display_num = self.FIXED_DISPLAYS[panel_index]
        else:
            error_msg = "Must specify display_num or panel_index"
            debug_log("ERROR: %s", error_msg)
            return None, error_msg
        
        debug_log("Resolved actual_display_num=%d", actual_display_num)
        
        if actual_display_num in self.displays:
            info = self.displays[actual_display_num]
            debug_log("Display :%d already exists, returning existing info", actual_display_num)
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
        debug_log("Using ports: vnc_port=%d, ws_port=%d", vnc_port, ws_port)
        
        if not self._is_port_available(vnc_port):
            error_msg = f"VNC port {vnc_port} is in use"
            debug_log("ERROR: %s", error_msg)
            return None, error_msg
        if not self._is_port_available(ws_port):
            error_msg = f"WebSocket port {ws_port} is in use"
            debug_log("ERROR: %s", error_msg)
            return None, error_msg
        if not self._is_display_available(actual_display_num):
            error_msg = f"Display :{actual_display_num} is in use by another process"
            debug_log("ERROR: %s", error_msg)
            return None, error_msg
        
        display = f":{actual_display_num}"
        clean_env = self._get_clean_env(display)
        
        try:
            # Start Xvfb
            xvfb_cmd = [
                "Xvfb", display,
                "-screen", "0", f"{width}x{height}x{depth}",
                "-ac", "+extension", "GLX", "+extension", "RENDER", "-nolisten", "tcp"
            ]
            debug_log("Starting Xvfb: %s", ' '.join(xvfb_cmd))
            xvfb_proc = subprocess.Popen(xvfb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=clean_env)
            time.sleep(0.5)
            
            if xvfb_proc.poll() is not None:
                _, stderr = xvfb_proc.communicate()
                error_msg = f"Failed to start Xvfb: {stderr.decode()}"
                debug_log("ERROR: %s", error_msg)
                return None, error_msg
            debug_log("Xvfb started successfully, pid=%d", xvfb_proc.pid)
            
            # Start x11vnc
            vnc_cmd = [
                "x11vnc", "-display", display,
                "-rfbport", str(vnc_port),
                "-nopw", "-forever", "-shared", "-noxdamage", "-wait", "5", "-defer", "5"
            ]
            debug_log("Starting x11vnc: %s", ' '.join(vnc_cmd))
            vnc_proc = subprocess.Popen(vnc_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=clean_env)
            time.sleep(0.5)
            
            if vnc_proc.poll() is not None:
                _, stderr = vnc_proc.communicate()
                debug_log("x11vnc failed, killing Xvfb (pid=%d)", xvfb_proc.pid)
                xvfb_proc.terminate()
                error_msg = f"Failed to start x11vnc: {stderr.decode()}"
                debug_log("ERROR: %s", error_msg)
                return None, error_msg
            debug_log("x11vnc started successfully, pid=%d", vnc_proc.pid)
            
            # Start websockify
            ws_cmd = ["websockify", str(ws_port), f"127.0.0.1:{vnc_port}"]
            debug_log("Starting websockify: %s", ' '.join(ws_cmd))
            ws_proc = subprocess.Popen(ws_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.3)
            
            if ws_proc.poll() is not None:
                _, stderr = ws_proc.communicate()
                debug_log("websockify failed, killing x11vnc (pid=%d) and Xvfb (pid=%d)", vnc_proc.pid, xvfb_proc.pid)
                vnc_proc.terminate()
                xvfb_proc.terminate()
                error_msg = f"Failed to start websockify: {stderr.decode()}"
                debug_log("ERROR: %s", error_msg)
                return None, error_msg
            debug_log("websockify started successfully, pid=%d", ws_proc.pid)
            
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
            
            debug_log("Display :%d fully initialized: Xvfb=%d, x11vnc=%d, websockify=%d",
                      actual_display_num, xvfb_proc.pid, vnc_proc.pid, ws_proc.pid)
            
            return {
                'display': display,
                'display_num': actual_display_num,
                'panel_index': self.get_panel_for_display(actual_display_num),
                'ws_port': ws_port,
                'width': width,
                'height': height
            }, None
            
        except Exception as e:
            debug_log("EXCEPTION during start_display: %s", str(e))
            import traceback
            debug_log("Traceback: %s", traceback.format_exc())
            return None, str(e)
    
    def start_display_for_panel(self, panel_index, width=1280, height=800):
        debug_log("start_display_for_panel called: panel_index=%d, width=%d, height=%d", panel_index, width, height)
        return self.start_display(panel_index=panel_index, width=width, height=height)
    
    def stop_display(self, display_num):
        debug_log("stop_display called: display_num=%d", display_num)
        if display_num not in self.displays:
            debug_log("Display :%d not found in tracked displays", display_num)
            return False, "Display not found"
        
        info = self.displays[display_num]
        debug_log("Stopping display :%d - pids: xvfb=%d, vnc=%d, ws=%d",
                  display_num, info.get('xvfb_pid', -1), info.get('vnc_pid', -1), info.get('ws_pid', -1))
        
        for pid_key in ['ws_pid', 'vnc_pid', 'xvfb_pid']:
            pid = info.get(pid_key)
            if pid:
                try:
                    debug_log("Sending SIGTERM to %s (pid=%d)", pid_key, pid)
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(0.1)
                    debug_log("Sending SIGKILL to %s (pid=%d)", pid_key, pid)
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    debug_log("Process %s (pid=%d) already dead", pid_key, pid)
                except Exception as e:
                    debug_log("Error killing %s (pid=%d): %s", pid_key, pid, e)
        
        del self.displays[display_num]
        debug_log("Display :%d stopped and removed from tracking", display_num)
        return True, None
    
    def get_display(self, display_num):
        debug_log("get_display called: display_num=%d", display_num)
        if display_num not in self.displays:
            debug_log("Display :%d not found", display_num)
            return None
        
        info = self.displays[display_num]
        
        try:
            os.kill(info['xvfb_pid'], 0)
            debug_log("Display :%d is alive (xvfb pid=%d)", display_num, info['xvfb_pid'])
        except ProcessLookupError:
            debug_log("Display :%d xvfb process is dead, cleaning up", display_num)
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
        debug_log("resize_display called: display_num=%d, width=%d, height=%d", display_num, width, height)
        if display_num not in self.displays:
            debug_log("Display :%d not found for resize", display_num)
            return None, "Display not found"
        debug_log("Stopping display :%d before resize", display_num)
        self.stop_display(display_num)
        debug_log("Restarting display :%d with new dimensions", display_num)
        return self.start_display(display_num=display_num, width=width, height=height)
    
    def cleanup_all(self):
        debug_log("cleanup_all called, stopping %d displays", len(self.displays))
        for display_num in list(self.displays.keys()):
            self.stop_display(display_num)
        debug_log("cleanup_all complete")
    
    def get_env_setup_commands(self, display_num):
        debug_log("get_env_setup_commands called: display_num=%d", display_num)
        if display_num not in self.displays:
            debug_log("Display :%d not found", display_num)
            return None
        display = self.displays[display_num]['display']
        cmd = (
            f"export DISPLAY={display} && "
            f"unset WAYLAND_DISPLAY && "
            f"export GDK_BACKEND=x11 && "
            f"export QT_QPA_PLATFORM=xcb"
        )
        debug_log("Env setup command: %s", cmd)
        return cmd
    
    def get_env_dict(self, display_num):
        debug_log("get_env_dict called: display_num=%d", display_num)
        if display_num not in self.displays:
            debug_log("Display :%d not found", display_num)
            return None
        display = self.displays[display_num]['display']
        return self._get_clean_env(display)