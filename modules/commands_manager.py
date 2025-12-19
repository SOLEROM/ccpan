"""
Custom commands management for quick command buttons.
"""

import os
import json


class CommandsManager:
    """Manages custom quick commands per session."""
    
    def __init__(self, commands_file='commands.json'):
        self.commands_file = commands_file
        self._commands = self._load()
    
    def _load(self):
        """Load commands from file."""
        if os.path.exists(self.commands_file):
            try:
                with open(self.commands_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save(self):
        """Save commands to file."""
        try:
            with open(self.commands_file, 'w') as f:
                json.dump(self._commands, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save commands: {e}")
    
    def get_all(self):
        """Get all commands for all sessions."""
        return self._commands.copy()
    
    def get(self, session):
        """Get commands for a session."""
        return self._commands.get(session, [])
    
    def add(self, session, label, command):
        """Add a command to a session."""
        if session not in self._commands:
            self._commands[session] = []
        self._commands[session].append({
            'label': label,
            'command': command
        })
        self._save()
        return self._commands[session]
    
    def delete(self, session, index):
        """Delete a command from a session."""
        if session not in self._commands:
            return None
        if index < 0 or index >= len(self._commands[session]):
            return None
        self._commands[session].pop(index)
        self._save()
        return self._commands[session]
    
    def clear(self, session):
        """Clear all commands for a session."""
        if session in self._commands:
            del self._commands[session]
            self._save()
