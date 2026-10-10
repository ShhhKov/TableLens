"""Check Windows/macOS settings adapters and Unix launchers on any host."""
import ctypes
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from editor import mac_preferences, system_language, system_theme


def check_settings():
    with patch('editor.sys.platform', 'win32'):
        api = MagicMock()
        with patch.object(ctypes, 'windll', api, create=True):
            for language_id, expected in [(0x419, 'ru'), (0x409, 'en'), (0x407, 'en')]:
                api.kernel32.GetUserDefaultUILanguage.return_value = language_id
                assert system_language() == expected
        registry = MagicMock()
        with patch.dict(sys.modules, {'winreg': registry}):
            for value, expected in [(0, 'dark'), (1, 'light')]:
                registry.QueryValueEx.return_value = (value, 4)
                assert system_theme() == expected
            registry.OpenKey.side_effect = FileNotFoundError()
            assert system_theme() == 'auto'
    with patch('editor.sys.platform', 'darwin'):
        for preferences, language, theme in [
            ({'AppleLanguages': ['ru-RU', 'en-US'], 'AppleInterfaceStyle': 'Dark'}, 'ru', 'dark'),
            ({'AppleLanguages': ['en-US']}, 'en', 'light'),
            ({'AppleLanguages': ['fr-FR', 'ru-RU']}, 'en', 'light'),
        ]:
            with patch('editor.subprocess.run', return_value=SimpleNamespace(stdout=plistlib.dumps(preferences))):
                assert system_language() == language
                assert system_theme() == theme
        with patch('editor.subprocess.run', side_effect=FileNotFoundError()), patch.dict(os.environ, {'LANG': 'ru_RU.UTF-8'}, clear=True):
            assert system_language() == 'ru'
            assert system_theme() == 'auto'
        with patch('editor.subprocess.run', return_value=SimpleNamespace(stdout=b'invalid plist')):
            assert mac_preferences() == {}
    print('Windows/macOS UI languages, themes and fallbacks: OK')


def check_launchers():
    with tempfile.TemporaryDirectory(prefix='tablelens-platforms-') as temporary:
        folder = Path(temporary) / 'Application with spaces'
        folder.mkdir()
        for name in ['Launch.sh', 'Launch.command']:
            (folder / name).write_bytes((ROOT / name).read_bytes())
            (folder / name).chmod(0o755)
        fakebin = folder / 'commands'
        fakebin.mkdir()
        uname = fakebin / 'uname'
        uname.write_text('#!/bin/sh\ncase "$1" in -s) echo "$TEST_OS";; -m) echo "$TEST_ARCH";; esac\n')
        uname.chmod(0o755)
        for platform, osname, architecture in [('linux-x64', 'Linux', 'x86_64'), ('linux-arm64', 'Linux', 'aarch64'),
                                                ('macos-x64', 'Darwin', 'x86_64'), ('macos-arm64', 'Darwin', 'arm64')]:
            interpreter = folder / 'runtime' / platform / 'python' / 'bin' / 'python3'
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$0" "$@"\n')
            interpreter.chmod(0o755)
            launcher = 'Launch.command' if osname == 'Darwin' else 'Launch.sh'
            result = subprocess.run(['sh', str(folder / launcher), 'File with spaces.tsv', '--no-browser'],
                                    capture_output=True, text=True, check=True,
                                    env={**os.environ, 'PATH': str(fakebin) + os.pathsep + os.environ['PATH'],
                                         'TEST_OS': osname, 'TEST_ARCH': architecture})
            assert result.stdout.splitlines() == [str(interpreter), '-B', str(folder / 'editor.py'), 'File with spaces.tsv', '--no-browser']
    print('Linux/macOS launchers, both architectures and paths with spaces: OK')


if __name__ == '__main__':
    check_settings()
    check_launchers()
