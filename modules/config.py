"""
Configuration management for Terminal Control Panel (Terminator branch).
"""

import os
import json
from pathlib import Path

DEFAULT_CONFIG = {
    'session_prefix': 'term-',
    'xvfb_display_base': 100,
    'commands_file': 'commands.json',
    'default_cols': 120,
    'default_rows': 40,
    'scrollback_limit': 50000,
    'default_shell': os.environ.get('SHELL', '/bin/bash'),
}


class Config:
    """Manages application configuration."""
    
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self._config = DEFAULT_CONFIG.copy()
        self._load()
    
    def _load(self):
        """Load configuration from file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    self._config.update(loaded)
            except Exception as e:
                print(f"Warning: Could not load config: {e}")
    
    def save(self):
        """Save configuration to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save config: {e}")
    
    @property
    def tmux_socket(self):
        return self._config['tmux_socket']
    
    @tmux_socket.setter
    def tmux_socket(self, value):
        self._config['tmux_socket'] = value
        self.save()
    
    @property
    def session_prefix(self):
        return self._config['session_prefix']
    
    @session_prefix.setter
    def session_prefix(self, value):
        self._config['session_prefix'] = value
        self.save()
    
    @property
    def xvfb_display_base(self):
        return self._config['xvfb_display_base']
    
    @property
    def commands_file(self):
        return self._config['commands_file']
    
    @property
    def default_cols(self):
        return self._config['default_cols']
    
    @property
    def default_rows(self):
        return self._config['default_rows']
    
    @property
    def scrollback_limit(self):
        return self._config['scrollback_limit']
    
    @property
    def default_shell(self):
        return self._config['default_shell']
    
    def to_dict(self):
        """Return config as dictionary."""
        return self._config.copy()
    
    def update(self, **kwargs):
        """Update multiple config values."""
        for key, value in kwargs.items():
            if key in self._config:
                self._config[key] = value
        self.save()