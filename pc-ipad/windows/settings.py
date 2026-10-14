"""Persistent identity: discovery never exposes the pairing PIN."""
import json
import os
from pathlib import Path
import secrets
import uuid


def load_settings(path=None):
    path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ShockStream' / 'settings.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            value = {}
    except (OSError, ValueError):
        value = {}
    changed = False
    if not isinstance(value.get('hostId'), str) or len(value['hostId']) != 32:
        value['hostId'] = uuid.uuid4().hex
        changed = True
    if not isinstance(value.get('pin'), str) or len(value['pin']) != 6 or not value['pin'].isascii() or not value['pin'].isdigit():
        value['pin'] = f'{secrets.randbelow(1000000):06d}'
        changed = True
    if changed:
        save_settings(value, path)
    return value


def save_settings(value, path=None):
    path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ShockStream' / 'settings.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
