"""User-selected Linux applications; package installers are never executed."""
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile


def install_linux_application_library(app, root, context):
    def path_for(profile):
        return root / f'runtime/app-library-{profile}.json'

    def load(profile):
        try:
            return json.loads(path_for(profile).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'items': []}

    def save(profile, data):
        target = path_for(profile)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temporary.replace(target)

    def profile():
        return context.config.get('profile', 'default')

    def digest(path):
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(chunk)
        return sha.hexdigest()

    def lookup(identity):
        item = next((item for item in load(profile())['items'] if item['id'] == identity), None)
        if not item:
            raise HTTPException(404, 'This application is no longer in the library.')
        return item

    def store(item):
        data = load(profile())
        data['items'] = [old for old in data['items'] if old['id'] != item['id']] + [item]
        save(profile(), data)

    def parse_desktop(path):
        import configparser
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(path, encoding='utf-8')
        entry = parser['Desktop Entry']
        if entry.get('Type') != 'Application' or entry.getboolean('Hidden', fallback=False) or entry.getboolean('NoDisplay', fallback=False):
            raise ValueError('This desktop entry is not a visible application.')
        raw = entry.get('Exec', '').strip()
        if not raw or any(char in raw for char in (';', '|', '&', '`', '$', '\n', '\r')):
            raise ValueError('This desktop entry has no safe direct launch command.')
        tokens = shlex.split(raw)
        tokens = [token for token in tokens if not re.fullmatch(r'%[fFuUdDnNickvm]', token)]
        if not tokens or Path(tokens[0]).name in {'sh', 'bash', 'dash', 'zsh', 'python', 'python3', 'env', 'sudo'}:
            raise ValueError('Script, shell and elevated launchers are not supported.')
        executable = shutil.which(tokens[0]) if not Path(tokens[0]).is_absolute() else tokens[0]
        if not executable or not Path(executable).is_file():
            raise ValueError('The application command is missing.')
        return {'executable': str(Path(executable).resolve()), 'args': tokens[1:], 'directory': str(Path(executable).resolve().parent),
                'name': entry.get('Name', path.stem), 'app_id': path.name}

    def add(path):
        if not path.is_file():
            raise HTTPException(400, 'Choose an application file.')
        path = path.resolve()
        suffix = path.suffix.lower()
        if suffix == '.desktop':
            try:
                spec = parse_desktop(path)
            except (OSError, ValueError, KeyError) as exc:
                raise HTTPException(422, str(exc)) from exc
            kind, name = 'desktop-entry', spec['name']
        else:
            if suffix in {'.deb', '.rpm', '.flatpak', '.snap', '.exe', '.msi', '.lnk'}:
                raise HTTPException(415, 'Linux package installers and Windows applications are not launched by Vision.')
            try:
                with path.open('rb') as stream:
                    magic = stream.read(4)
            except OSError as exc:
                raise HTTPException(400, 'The application cannot be read.') from exc
            if magic != b'\x7fELF':
                raise HTTPException(415, 'Choose a Linux ELF executable, AppImage or .desktop application shortcut.')
            if not os.access(path, os.X_OK):
                raise HTTPException(415, 'This Linux application file is not executable. Set its executable permission first.')
            spec = {'executable': str(path), 'args': [], 'directory': str(path.parent), 'name': path.name, 'app_id': None}
            kind, name = 'portable-linux-app', path.name
        identity = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        item = {'id': identity, 'name': name, 'kind': kind, 'path': str(path), 'size': path.stat().st_size,
                'state': 'clear', 'detail': 'File identity recorded. No antivirus scan was performed; this is not a safety verdict.',
                'sha256': digest(path), 'scan_time': __import__('time').time(), **spec}
        store(item)
        return {key: value for key, value in item.items() if key != 'path'}

    @app.get('/api/app-library')
    async def listing():
        data = load(profile())
        return {'items': [{key: value for key, value in item.items() if key != 'path'} for item in data['items']]}

    @app.post('/api/app-library/open')
    async def add_local(request: Request):
        data = await request.json()
        source = Path(str(data.get('path', '')))
        item = add(source)
        await context.add({'id': item['id'], 'name': item['name'], 'path': str(source.resolve()), 'kind': 'application'})
        return item

    @app.post('/api/app-library/upload')
    async def upload(file: UploadFile):
        name = Path(file.filename or 'application').name
        destination = root / 'runtime/app-library-files' / (secrets.token_hex(12) + '-' + name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = 0
            with destination.open('xb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024 * 1024:
                        raise HTTPException(413, 'Application uploads are limited to 2 GB.')
                    stream.write(chunk)
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
            item = add(destination)
            await context.add({'id': item['id'], 'name': item['name'], 'path': str(destination.resolve()), 'kind': 'application'})
            return item
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    @app.post('/api/app-library/{identity}/scan')
    async def rescan(identity: str):
        item = lookup(identity)
        path = Path(item['path'])
        if not path.is_file():
            item.update(state='unavailable', detail='The application file is missing.')
        else:
            item.update(state='clear', sha256=digest(path), size=path.stat().st_size,
                        scan_time=__import__('time').time(), detail='File identity recorded. No antivirus scan was performed; this is not a safety verdict.')
        store(item)
        return {key: value for key, value in item.items() if key != 'path'}

    @app.post('/api/app-library/{identity}/remove')
    async def remove(identity: str):
        data = load(profile())
        item = next((item for item in data['items'] if item['id'] == identity), None)
        data['items'] = [item for item in data['items'] if item['id'] != identity]
        save(profile(), data)
        if item:
            await context.remove(identity)
        return {'removed': bool(item)}

    @app.post('/api/app-library/{identity}/launch')
    async def launch(identity: str, request: Request):
        import secrets as secret_module
        expected = os.environ.get('VISION_DESKTOP_SECRET', '')
        if not expected or not secret_module.compare_digest(expected, request.headers.get('x-vision-desktop', '')):
            raise HTTPException(403, 'Open applications using the Vision desktop app.')
        item = lookup(identity)
        path = Path(item['path'])
        if item['state'] != 'clear' or not path.is_file() or digest(path) != item.get('sha256'):
            raise HTTPException(409, 'The application changed or is unavailable. Add it again before opening.')
        if item['kind'] == 'desktop-entry':
            try:
                spec = parse_desktop(path)
            except (OSError, ValueError, KeyError) as exc:
                raise HTTPException(409, str(exc)) from exc
        else:
            spec = {'executable': str(path), 'args': [], 'directory': str(path.parent), 'name': item['name'], 'app_id': None}
        before = [entry['hwnd'] for entry in __import__('backend.app_windows_linux', fromlist=['windows']).windows()]
        return {**spec, 'before': before}

