"""User-selected folders, conflict-aware source editing and non-destructive PDF edits."""
import asyncio
import hashlib
import json
import re
import secrets
import shutil
import mimetypes
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from .workspace_files import allowed_file


def install_workspace_projects(app, previews, root, context):
    locks = {}
    pdf_render_lock = asyncio.Lock()
    clipboard = {}

    def pdf_path(identity):
        record = previews.files.get(identity)
        if not record or Path(record['path']).suffix.lower() != '.pdf' or not Path(record['path']).is_file():
            raise HTTPException(404, 'Open a PDF first.')
        path = Path(record['path'])
        if path.stat().st_size > 100 * 1024 * 1024:
            raise HTTPException(413, 'The PDF editor supports documents up to 100 MB.')
        return path

    @app.get('/api/pdf/{identity}/page')
    async def render_pdf_page(identity: str, page: int = 0, width: int = 1400, rotation: int = 0):
        path = pdf_path(identity)
        if rotation not in {0, 90, 180, 270}:
            raise HTTPException(400, 'Choose a quarter-turn rotation.')
        width = max(400, min(width, 2400))
        cache = root / 'runtime/pdf-previews'
        cache.mkdir(exist_ok=True)
        stamp = path.stat().st_mtime_ns
        target = cache / f'{identity}-{stamp}-{page}-{width}-{rotation}.png'
        async with pdf_render_lock:
            if not target.exists():
                def render():
                    import pymupdf
                    with pymupdf.open(path) as document:
                        if document.needs_pass:
                            raise ValueError('Unlock this PDF before previewing it.')
                        if not 0 <= page < len(document):
                            raise ValueError('Choose an existing page.')
                        current = document[page]
                        current.set_rotation((current.rotation + rotation) % 360)
                        scale = min(width / max(1, current.rect.width), (12000000 / max(1, current.rect.width * current.rect.height)) ** .5)
                        pixmap = current.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True)
                        pixmap.save(target)
                try:
                    await asyncio.to_thread(render)
                except Exception as exc:
                    raise HTTPException(422, str(exc)) from exc
        return FileResponse(target, media_type='image/png')

    @app.get('/api/pdf/{identity}/text')
    async def pdf_page_text(identity: str, page: int = 0):
        path = pdf_path(identity)
        async with pdf_render_lock:
            def read():
                import pymupdf
                with pymupdf.open(path) as document:
                    if document.needs_pass or not 0 <= page < len(document):
                        raise ValueError('Choose an unlocked PDF page.')
                    return document[page].get_text()[:200000]
            try:
                text = await asyncio.to_thread(read)
            except Exception as exc:
                raise HTTPException(422, str(exc)) from exc
        readable = root / 'runtime/workspace-readable'
        readable.mkdir(exist_ok=True)
        (readable / (identity + '.txt')).write_text(f'PDF excerpt from page {page + 1} of {path.name}:\n\n' + text, encoding='utf-8')
        return {'page': page, 'text': text}

    def manifest():
        return root / ('runtime/workspaces-' + context.config.get('profile', 'default') + '.json')

    def load():
        try:
            return json.loads(manifest().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'items': []}

    def save(data):
        target = manifest()
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temporary.replace(target)

    def project(identity):
        item = next((item for item in load()['items'] if item['id'] == identity), None)
        if not item or not Path(item['path']).is_dir():
            raise HTTPException(404, 'This workspace folder is no longer available.')
        return item, Path(item['path']).resolve()

    def inside(base, relative):
        path = (base / str(relative)).resolve()
        if not path.is_relative_to(base) or any(part == '.git' for part in path.relative_to(base).parts):
            raise HTTPException(403, 'Choose a location inside this workspace.')
        return path

    def text_file(path):
        allowed_file(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise HTTPException(413, 'The source editor supports files up to 2 MB.')
        raw = path.read_bytes()
        encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        try:
            text = raw.decode(encoding)
            if '\x00' in text:
                raise UnicodeError()
        except UnicodeError:
            raise HTTPException(415, 'This is a binary document. Use its document editor or ask Vision to edit it.')
        return {'text': text, 'encoding': encoding, 'revision': hashlib.sha256(raw).hexdigest()}

    async def share(path):
        result = await previews.register(path, 'workspace', manual=True)
        if not result:
            raise HTTPException(400, 'This file could not be opened.')
        await context.add({**result, 'kind': 'file', 'path': str(path)})
        return result

    @app.get('/api/projects')
    async def list_projects():
        return load()

    @app.post('/api/projects')
    async def open_project(request: Request):
        data = await request.json()
        if data.get('file_id'):
            record = previews.files.get(str(data['file_id']))
            if not record:
                raise HTTPException(404, 'Open the file first.')
            path = Path(record['path']).resolve().parent
            preferred = next((item for item in load()['items'] if item['id'] == data.get('workspace_id')), None)
            if preferred and path.is_relative_to(Path(preferred['path']).resolve()):
                path = Path(preferred['path']).resolve()
        elif data.get('create'):
            name = str(data.get('name', '')).strip()
            if not re.fullmatch(r'[\w .-]{1,100}', name) or name in {'.', '..'} or name.endswith(('.', ' ')):
                raise HTTPException(400, 'Use a folder name with letters, numbers, spaces, dots or hyphens.')
            parent = Path(data.get('parent') or root / 'runtime/workspaces').resolve()
            parent.mkdir(parents=True, exist_ok=True)
            path = parent / name
            try:
                path.mkdir()
            except FileExistsError:
                raise HTTPException(409, 'That folder already exists. Open it instead.')
            except OSError as exc:
                raise HTTPException(400, str(exc)) from exc
        else:
            path = Path(str(data.get('path', '')))
        if not path.is_absolute() or not path.is_dir():
            raise HTTPException(400, 'Choose an existing workspace folder.')
        path = path.resolve()
        item = {'id': hashlib.sha256(str(path).encode()).hexdigest()[:24], 'name': path.name, 'path': str(path)}
        state = load()
        state['items'] = [old for old in state['items'] if old['id'] != item['id']] + [item]
        state['active'] = item['id']
        save(state)
        await context.add({**item, 'kind': 'folder'})
        return item

    @app.get('/api/projects/{identity}/tree')
    async def tree(identity: str, relative: str = ''):
        _, base = project(identity)
        folder = inside(base, relative)
        if not folder.is_dir():
            raise HTTPException(400, 'Choose a folder.')
        try:
            entries = sorted((p for p in folder.iterdir() if p.name not in {'.git', 'node_modules', '.venv', '__pycache__'}), key=lambda p: (not p.is_dir(), p.name.lower()))
            return {'relative': str(folder.relative_to(base)), 'items': [{'name': p.name, 'relative': str(p.relative_to(base)), 'folder': p.is_dir()} for p in entries[:500]], 'truncated': len(entries) > 500}
        except OSError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post('/api/projects/{identity}/folder')
    async def create_folder(identity: str, request: Request):
        _, base = project(identity)
        path = inside(base, (await request.json()).get('relative', ''))
        try:
            path.mkdir()
        except OSError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'name': path.name, 'relative': str(path.relative_to(base))}

    @app.post('/api/projects/{identity}/open')
    async def project_file(identity: str, request: Request):
        _, base = project(identity)
        path = inside(base, (await request.json()).get('relative', ''))
        if not path.is_file():
            raise HTTPException(404, 'This file is no longer available.')
        allowed_file(path)
        return await share(path)

    @app.post('/api/projects/{identity}/file')
    async def new_file(identity: str, request: Request):
        _, base = project(identity)
        path = inside(base, (await request.json()).get('relative', ''))
        try:
            with path.open('x', encoding='utf-8'):
                pass
        except OSError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await share(path)

    def available(path):
        if not path.exists():
            return path
        for index in range(2, 10000):
            candidate = path.with_name(path.stem + f' ({index})' + path.suffix)
            if not candidate.exists():
                return candidate
        raise HTTPException(409, 'Choose another file name.')

    def copy_item(source, destination, cut=False):
        # Never follow a directory link into an unrelated folder during copy.
        if source.is_symlink():
            raise HTTPException(415, 'Folder and file links cannot be copied through the workspace.')
        if source.is_dir() and destination.resolve().is_relative_to(source.resolve()):
            raise HTTPException(400, 'A folder cannot be pasted into itself.')
        if cut:
            shutil.move(str(source), str(destination))
        elif source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            allowed_file(source)
            shutil.copy2(source, destination)

    async def reconcile(old, destination=None):
        closed, replacements = [], []
        for identity, record in list(previews.files.items()):
            path = Path(record['path'])
            if path != old and not path.is_relative_to(old):
                continue
            closed.append(identity)
            await context.remove(identity)
            previews.files.pop(identity, None)
            if destination is not None:
                new_path = destination / path.relative_to(old) if path != old else destination
                if new_path.is_file():
                    replacements.append(await share(new_path))
        previews.manifest.write_text(json.dumps(list(previews.files.values())), encoding='utf-8')
        return {'closed': closed, 'files': replacements}

    @app.post('/api/projects/{identity}/operation')
    async def file_operation(identity: str, request: Request):
        item, base = project(identity)
        data = await request.json()
        path = inside(base, data.get('relative', ''))
        action = data.get('action')
        owner = context.config.get('profile', 'default')
        if action == 'properties':
            if not path.exists():
                raise HTTPException(404, 'This item no longer exists.')
            stat = path.stat()
            return {'name': path.name, 'location': str(path.parent), 'size': stat.st_size if path.is_file() else None, 'type': 'Folder' if path.is_dir() else mimetypes.guess_type(path.name)[0] or 'File', 'modified': stat.st_mtime, 'folder': path.is_dir()}
        if action in {'copy', 'cut'}:
            if path == base or not path.exists():
                raise HTTPException(400, 'Select a file or child folder.')
            clipboard[owner] = {'project': identity, 'relative': str(path.relative_to(base)), 'cut': action == 'cut'}
            return {'copied': True}
        if action == 'paste':
            source_data = clipboard.get(owner)
            if not source_data:
                raise HTTPException(409, 'Copy or cut a workspace item first.')
            _, source_base = project(source_data['project'])
            source = inside(source_base, source_data['relative'])
            folder = path if path.is_dir() else path.parent
            destination = available(folder / source.name)
            await asyncio.to_thread(copy_item, source, destination, source_data['cut'])
            changes = {}
            if source_data['cut']:
                clipboard.pop(owner, None)
                changes = await reconcile(source, destination)
            return {'name': destination.name, 'clipboard_ready': not source_data['cut'], **changes}
        if action == 'rename':
            name = str(data.get('name', '')).strip()
            if path == base or not name or name in {'.', '..'} or any(c in name for c in '<>:"/\\|?*') or name.endswith(('.', ' ')):
                raise HTTPException(400, 'Choose a valid name for this item.')
            destination = inside(base, str(path.parent.relative_to(base) / name))
            if destination.exists() and destination != path:
                raise HTTPException(409, 'An item with this name already exists.')
            path.rename(destination)
            return {'name': destination.name, 'relative': str(destination.relative_to(base)), **await reconcile(path, destination)}
        if action == 'recycle':
            if path == base or not path.exists():
                raise HTTPException(400, 'Select a file or child folder.')
            def recycle():
                import ctypes
                from ctypes import wintypes
                class Operation(ctypes.Structure):
                    _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT), ('pFrom', wintypes.LPCWSTR), ('pTo', wintypes.LPCWSTR), ('fFlags', wintypes.WORD), ('aborted', wintypes.BOOL), ('mappings', ctypes.c_void_p), ('title', wintypes.LPCWSTR)]
                operation = Operation(None, 3, str(path) + '\0\0', None, 0x40 | 0x10 | 0x400, False, None, None)
                code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
                if code or operation.aborted:
                    raise OSError('Windows could not move this item to the Recycle Bin.')
            await asyncio.to_thread(recycle)
            return {'recycled': True, **await reconcile(path)}
        raise HTTPException(400, 'Choose a file action.')

    @app.post('/api/projects/{identity}/import')
    async def import_upload(identity: str, file: UploadFile, relative: str = ''):
        _, base = project(identity)
        folder = inside(base, relative)
        if not folder.is_dir():
            raise HTTPException(400, 'Choose a destination folder.')
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(file.filename or 'file').name).strip(' .')[:180] or 'file'
        from .workspace_files import APPLICATIONS
        if Path(name).suffix.lower() in APPLICATIONS:
            raise HTTPException(415, 'Applications belong in Apps, not in the editing workspace.')
        destination = available(folder / name)
        temporary = folder / ('.vision-import-' + secrets.token_hex(10))
        try:
            size = 0
            with temporary.open('xb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024 * 1024:
                        raise HTTPException(413, 'Use the native desktop file import for files larger than 2 GB.')
                    stream.write(chunk)
            allowed_file(temporary)
            temporary.rename(destination)
            return await share(destination)
        finally:
            temporary.unlink(missing_ok=True)

    @app.post('/api/projects/{identity}/import-local')
    async def import_local(identity: str, request: Request):
        _, base = project(identity)
        data = await request.json()
        folder = inside(base, data.get('relative', ''))
        if not folder.is_dir():
            raise HTTPException(400, 'Choose a destination folder.')
        paths = data.get('paths', [])
        if not isinstance(paths, list) or len(paths) > 100:
            raise HTTPException(400, 'Import up to 100 files at once.')
        results = []
        for name in paths:
            source = Path(str(name))
            if not source.is_absolute() or not source.is_file():
                raise HTTPException(400, 'Drop files rather than applications or folders.')
            allowed_file(source)
            destination = available(folder / source.name)
            await asyncio.to_thread(shutil.copy2, source, destination)
            results.append(await share(destination))
        return {'files': results}

    @app.get('/api/edit/{identity}')
    async def read_source(identity: str):
        record = previews.files.get(identity)
        if not record or not Path(record['path']).is_file():
            raise HTTPException(404, 'This file is no longer available.')
        return await asyncio.to_thread(text_file, Path(record['path']))

    @app.post('/api/edit/{identity}')
    async def save_source(identity: str, request: Request):
        data = await request.json()
        record = previews.files.get(identity)
        if not record or not Path(record['path']).is_file():
            raise HTTPException(404, 'This file is no longer available.')
        async with locks.setdefault(identity, asyncio.Lock()):
            path = Path(record['path'])
            current = await asyncio.to_thread(text_file, path)
            if current['revision'] != data.get('revision'):
                raise HTTPException(409, 'This file changed outside the editor. Reload it before saving to avoid overwriting changes.')
            text = data.get('text')
            if not isinstance(text, str) or len(text.encode('utf-8')) > 2 * 1024 * 1024:
                raise HTTPException(413, 'The source editor supports text up to 2 MB.')
            backup = root / ('runtime/workspace-backups/' + identity)
            backup.mkdir(parents=True, exist_ok=True)
            (backup / (current['revision'] + '.bak')).write_bytes(path.read_bytes())
            # Keep the original encoding, BOM and line endings. Do not execute the source.
            raw = text.encode(current['encoding'])
            if current['encoding'] == 'utf-8-sig' and not path.read_bytes().startswith(b'\xef\xbb\xbf'):
                raw = text.encode('utf-8')
            temporary = path.with_name('.' + path.name + '.vision-' + secrets.token_hex(6))
            try:
                temporary.write_bytes(raw)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            result = await share(path)
            await context.gateway.publish('settings.saved', {'text': 'Saved ' + path.name})
            return {**(await asyncio.to_thread(text_file, path)), 'file': result}

    @app.get('/api/pdf/{identity}')
    async def pdf_info(identity: str):
        from pypdf import PdfReader
        path = pdf_path(identity)
        try:
            reader = await asyncio.to_thread(PdfReader, str(path))
            if reader.is_encrypted:
                raise HTTPException(422, 'Unlock this PDF before editing it.')
            return {'pages': [{'width': float(p.mediabox.width), 'height': float(p.mediabox.height)} for p in reader.pages], 'revision': hashlib.sha256(path.read_bytes()).hexdigest()}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, 'This PDF could not be read: ' + str(exc)) from exc

    @app.post('/api/pdf/{identity}')
    async def save_pdf(identity: str, request: Request):
        from pypdf import PdfReader, PdfWriter
        from pypdf.annotations import Text
        data = await request.json()
        path = pdf_path(identity)
        def write_copy():
            if hashlib.sha256(path.read_bytes()).hexdigest() != data.get('revision'):
                raise HTTPException(409, 'The PDF changed. Reopen its editor before saving.')
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise HTTPException(422, 'Unlock this PDF before editing it.')
            writer = PdfWriter()
            rotations = data.get('rotations', {})
            for index, page in enumerate(reader.pages):
                rotation = int(rotations.get(str(index), 0))
                if rotation not in {0, 90, 180, 270}:
                    raise HTTPException(400, 'Choose a valid page rotation.')
                if rotation:
                    page.rotate(rotation)
                writer.add_page(page)
            notes = data.get('notes', [])
            if not isinstance(notes, list) or len(notes) > 200:
                raise HTTPException(400, 'Add up to 200 notes per copy.')
            for note in notes:
                index = int(note['page'])
                text = str(note['text']).strip()
                if not 0 <= index < len(writer.pages) or not text or len(text) > 10000:
                    raise HTTPException(400, 'Choose a valid page and note.')
                page = writer.pages[index]
                # Standard visible PDF text annotation, placed at the upper-left of the page.
                y = max(20, float(page.mediabox.height) - 64 - (int(note.get('slot', 0)) % 12) * 28)
                writer.add_annotation(index, Text(rect=(24, y, 48, y + 24), text=text, open=True))
            destination = root / 'runtime/workspace-files' / secrets.token_hex(12)
            destination.mkdir(parents=True)
            result = destination / (path.stem + '-edited.pdf')
            with result.open('wb') as stream:
                writer.write(stream)
            return result
        try:
            result = await asyncio.to_thread(write_copy)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, 'The edited PDF could not be saved: ' + str(exc)) from exc
        return await share(result)
