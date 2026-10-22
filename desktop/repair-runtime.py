"""Rebase the bundled Windows interpreters and native command launchers."""
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
native = root / 'runtime/hermes/hermes-agent'
old = Path.home() / 'AppData/Local/hermes/hermes-agent'
for venv in [root / '.venv', native / 'venv']:
    cfg = venv / 'pyvenv.cfg'
    lines = cfg.read_text().splitlines()
    cfg.write_text('\n'.join('home = ' + str(root / 'runtime/python') if line.startswith('home =') else line for line in lines) + '\n')
    # uv's trampoline embeds its original base interpreter; use CPython's
    # standard launcher which resolves the home above instead.
    for name in ['python.exe', 'pythonw.exe']:
        shutil.copy2(root / 'runtime/python/Lib/venv/scripts/nt' / name, venv / 'Scripts' / name)
site = native / 'venv/Lib/site-packages'
for file in site.glob('__editable__*'):
    if file.suffix in {'.py', '.pth'}:
        text = file.read_text()
        for before, after in [(str(old), str(native)), (str(old).replace('\\', '\\\\'), str(native).replace('\\', '\\\\')), (old.as_posix(), native.as_posix())]:
            text = text.replace(before, after)
        file.write_text(text)
config = root / 'runtime/config.json'
data = json.loads(config.read_text())
data['hermes_path'] = str(native)
config.write_text(json.dumps(data, indent=2))
# Windows console launchers embed an absolute interpreter path.
from pip._vendor.distlib.scripts import ScriptMaker
from importlib.metadata import distributions
maker = ScriptMaker(None, str(native / 'venv/Scripts'))
maker.executable = str(native / 'venv/Scripts/python.exe')
maker.clobber = True
maker.variants = {''}
for dist in distributions(path=[str(site)]):
    for entry in dist.entry_points:
        if entry.group == 'console_scripts':
            maker.make(f'{entry.name} = {entry.value}')
print('Bundled runtime paths and launchers updated.')
