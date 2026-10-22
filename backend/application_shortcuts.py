"""Resolve ordinary .lnk applications and parse their Windows argument vector."""
import asyncio
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from fastapi import HTTPException

SHELL_HOSTS = {'cmd.exe', 'powershell.exe', 'pwsh.exe', 'wscript.exe', 'cscript.exe', 'mshta.exe', 'rundll32.exe', 'regsvr32.exe', 'msiexec.exe'}


def split_arguments(raw):
    if not raw:
        return []
    if len(raw) > 16000 or any(ord(c) < 32 for c in raw):
        raise ValueError('The shortcut contains invalid arguments.')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    parser = shell.CommandLineToArgvW
    parser.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parser.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    argv = parser('vision-shortcut.exe ' + raw, ctypes.byref(count))
    if not argv:
        raise ValueError('Windows could not read the shortcut arguments.')
    try:
        return [argv[index] for index in range(1, count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


async def resolve_shortcut(root, path):
    try:
        process = await asyncio.create_subprocess_exec('powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(root / 'desktop/resolve-shortcut.ps1'), env={**os.environ, 'VISION_SHORTCUT_PATH': str(path)}, creationflags=0x08000000, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, error = await asyncio.wait_for(process.communicate(), 20)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise ValueError('This shortcut could not be resolved. It may be broken, an advertised installer link, or a packaged app shortcut. Add its application file instead.')
        result = json.loads(output.decode('utf-8-sig'))
        target = Path(result['target']).resolve()
        if not target.is_file():
            raise ValueError('The shortcut target is missing. Repair the shortcut or add the application file.')
        if target.suffix.lower() not in {'.exe', '.msi'} or target.name.lower() in SHELL_HOSTS:
            raise ValueError('Choose a shortcut directly to an application EXE or MSI. Script, command-shell and indirect launcher shortcuts are not supported.')
        arguments = split_arguments(result.get('arguments', ''))
        directory = Path(result.get('directory') or target.parent)
        if not directory.is_absolute() or not directory.is_dir():
            directory = target.parent
        return {'path': str(target), 'arguments': arguments, 'argument_text': result.get('arguments', ''), 'directory': str(directory), 'target_name': target.name, 'target_path': str(target)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc) or 'The shortcut could not be resolved.') from exc
