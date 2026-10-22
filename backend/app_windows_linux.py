"""Linux X11 window discovery and live-preview placement primitives.

Wayland intentionally relies on the desktop's capture/input portals; these X11
helpers never pretend that arbitrary Wayland windows can be controlled.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path


class _WindowApi:
    @staticmethod
    def IsWindow(identity):
        return any(int(item['hwnd'], 0) == int(identity) for item in windows())


U = _WindowApi()


def _run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=3, check=False).stdout


def pid(hwnd):
    for item in windows():
        if int(item['hwnd'], 0) == int(hwnd):
            return item['pid']
    return 0


def executable(process_id):
    try:
        return str(Path(f'/proc/{int(process_id)}/exe').resolve())
    except OSError:
        return ''


def same_path(a, b):
    try:
        return os.path.samefile(a, b)
    except (OSError, TypeError):
        return os.path.realpath(a) == os.path.realpath(b)


def windows():
    if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland' and not os.environ.get('DISPLAY'):
        return []
    if not shutil.which('wmctrl'):
        return []
    result = []
    for line in _run('wmctrl', '-lpG').splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        identity, _desktop, process_id, x, y, width, height, title = parts
        try:
            number = int(process_id)
            result.append({'hwnd': identity, 'pid': number, 'title': title, 'class': '',
                           'executable': executable(number), 'app_ids': [], 'owner': '0',
                           'bounds': [int(x), int(y), int(width), int(height)]})
        except ValueError:
            continue
    return result


def process_tree(process_id):
    family = {int(process_id)}
    proc = Path('/proc')
    parents = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / 'stat').read_text()
            parents[int(entry.name)] = int(stat[stat.rfind(')') + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    while True:
        updated = family | {child for child, parent in parents.items() if parent in family}
        if updated == family:
            return family
        family = updated


def present_capture(record):
    identity = record['hwnd']
    if not U.IsWindow(int(identity, 0)):
        raise OSError('The application window closed.')
    # Keep the native window behind Vision so Electron can capture its live
    # desktop source into the center preview without covering the interface.
    subprocess.run(['wmctrl', '-ir', identity, '-b', 'add,below'], capture_output=True, timeout=3)
    return {'mode': 'capture', 'reason': 'Live Linux application view · rendered inside the preview'}


def detach(record):
    identity = record.get('hwnd')
    if identity:
        subprocess.run(['wmctrl', '-ir', str(identity), '-b', 'remove,below'], capture_output=True, timeout=3)


def input_idle():
    if shutil.which('xprintidle'):
        try:
            return int(_run('xprintidle').strip() or 0)
        except ValueError:
            pass
    # Without a trustworthy idle source, require an explicit user action.
    return 0
