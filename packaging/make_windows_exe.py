"""Build packages/TableLens.exe on Windows using the repository's libraries."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build_command():
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onefile', '--windowed', '--name', 'TableLens',
               '--distpath', str(ROOT / 'packages'),
               '--workpath', str(ROOT / 'build' / 'windows-exe'),
               '--specpath', str(ROOT / 'build'),
               '--paths', str(ROOT), '--paths', str(ROOT / 'libraries')]
    for package in ['openpyxl', 'xlrd', 'pyxlsb', 'et_xmlfile']:
        command.extend(['--collect-all', package])
    # Source requests use pip's certificate bundle when it is available.
    # PyInstaller detects the Python import but needs the PEM file explicitly.
    command.extend(['--collect-data', 'pip._vendor.certifi'])
    for source, destination in [('editor.html', '.'), ('source_bridge.js', '.'),
                                ('assets', 'assets'), ('README.md', '.'),
                                ('BUNDLE_MANIFEST.json', '.')]:
        command.extend(['--add-data', str(ROOT / source) + ':' + destination])
    for metadata in sorted((ROOT / 'libraries').glob('*.dist-info')):
        command.extend(['--add-data', str(metadata) + ':licenses/' + metadata.name])
    command.append(str(ROOT / 'packaging' / 'windows_entry.py'))
    return command


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build TableLens.exe on Windows or use the Windows EXE GitHub Actions workflow.')
    (ROOT / 'build').mkdir(exist_ok=True)
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join(filter(None, [
        str(ROOT / 'libraries'), environment.get('PYTHONPATH')]))
    subprocess.run(build_command(), cwd=ROOT, env=environment, check=True)
    print('Built:', ROOT / 'packages' / 'TableLens.exe')


if __name__ == '__main__':
    main()
