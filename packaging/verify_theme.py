"""Verify Linux theme detection and live theme switching in Chrome."""
import base64
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from editor import system_theme
from verify_browser import CDP


def check_detection():
    with patch('editor.sys.platform', 'linux'), patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'GNOME'}, clear=True):
        for values, expected in [(['prefer-dark'], 'dark'), (['prefer-light'], 'light'),
                                 (['default', 'Adwaita-dark'], 'dark'), (['default', 'Adwaita'], 'auto')]:
            with patch('editor.subprocess.run', side_effect=[SimpleNamespace(stdout=value) for value in values]):
                assert system_theme() == expected
        for error in [FileNotFoundError(), subprocess.TimeoutExpired('gsettings', 2), subprocess.CalledProcessError(1, 'gsettings')]:
            with patch('editor.subprocess.run', side_effect=error):
                assert system_theme() == 'auto'
    with tempfile.TemporaryDirectory() as folder:
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE', 'XDG_CONFIG_HOME': folder}, clear=True):
            for scheme, expected in [('BreezeDark', 'dark'), ('Breeze', 'light')]:
                (Path(folder) / 'kdeglobals').write_text('[General]\nColorScheme=' + scheme)
                assert system_theme() == expected
    print('GNOME, GTK, KDE and fallback detection: OK', flush=True)


def check_browser():
    with tempfile.TemporaryDirectory(prefix='tablelens-theme-') as temporary:
        folder = Path(temporary)
        chrome = subprocess.Popen(['/usr/bin/google-chrome-stable', '--headless=new', '--no-sandbox',
                                   '--disable-dev-shm-usage', '--remote-debugging-port=0',
                                   '--user-data-dir=' + str(folder / 'profile'), 'about:blank'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        app = None
        try:
            portfile = folder / 'profile' / 'DevToolsActivePort'
            for _ in range(100):
                if portfile.exists():
                    break
                if chrome.poll() is not None:
                    raise RuntimeError(chrome.stderr.read().decode())
                time.sleep(.1)
            port = int(portfile.read_text().splitlines()[0])
            targets = json.load(urlopen(f'http://127.0.0.1:{port}/json'))
            client = CDP(next(target['webSocketDebuggerUrl'] for target in targets if target['type'] == 'page'))
            client.call('Page.enable')
            client.call('Runtime.enable')
            for device, browser, expected in [('auto', 'dark', 'dark'), ('auto', 'light', 'light'),
                                               ('dark', 'light', 'dark'), ('light', 'dark', 'light')]:
                client.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': browser}]})
                app = subprocess.Popen([sys.executable, '-B', '-c',
                                        f"import editor; editor.system_theme=lambda: {device!r}; editor.main()",
                                        '--no-browser', '--storage-dir', str(folder / 'workspace')],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       env={**os.environ, 'LC_ALL': 'ru_RU.UTF-8'})
                address = re.search(r'http://\S+', app.stdout.readline()).group(0)
                client.call('Page.navigate', {'url': address})
                client.wait("document.querySelector('#file-wizard')?.open")
                assert client.evaluate('theme') == expected
                initial = client.evaluate("getComputedStyle($('file-wizard')).backgroundColor")
                assert initial == ('rgb(24, 34, 49)' if expected == 'dark' else 'rgb(244, 246, 251)')
                assert client.evaluate("$('wizard-theme-toggle').querySelector('circle')!==null") == (expected == 'dark')
                assert client.evaluate("getComputedStyle($('wizard-theme-toggle')).width") == '33px'
                client.evaluate("$('wizard-theme-toggle').click()")
                assert client.evaluate('theme') != expected
                assert client.evaluate("getComputedStyle($('file-wizard')).backgroundColor") != initial
                client.evaluate("$('wizard-language-toggle').click()")
                assert client.evaluate("$('wizard-theme-toggle').title") == ('Switch to dark theme' if expected == 'dark' else 'Switch to light theme')
                client.evaluate("(async()=>{showWizardConfig(await api('import',{name:'theme.tsv',content:btoa('Name\\tSource\\nFirst\\thttps://example.org')}));})()")
                client.wait("!!wizardState&&!!$('wizard-columns').querySelector('tbody tr')")
                client.evaluate("$('auto').checked=false;$('wizard-start').click()")
                client.wait("!!state&&!$('file-wizard').open&&!busy&&!wizardBusy")
                client.evaluate("setEditorText($('col-0'),'unsaved draft');$('col-0').dispatchEvent(new Event('input'));$('theme-toggle').click()")
                assert client.evaluate('theme') == expected
                assert client.evaluate('values()[0]') == 'unsaved draft'
                assert client.evaluate('dirty()')
                if device == 'auto' and browser == 'dark':
                    client.evaluate('new Promise(resolve=>setTimeout(resolve,250))')
                    screenshot = client.call('Page.captureScreenshot')['data']
                    Path('/tmp/tablelens-dark-editor.png').write_bytes(base64.b64decode(screenshot))
                client.call('Page.reload')
                client.wait("document.querySelector('#file-wizard')?.open")
                assert client.evaluate('theme') == expected
                print(f'{device=}, {browser=}: startup, icons, switching, language, draft and reset OK', flush=True)
                app.terminate()
                app.wait(timeout=10)
                app = None
        finally:
            if app is not None:
                app.terminate()
                app.wait(timeout=10)
            if chrome.poll() is None:
                os.killpg(chrome.pid, signal.SIGTERM)
            chrome.wait(timeout=10)


if __name__ == '__main__':
    check_detection()
    check_browser()
