"""Source workspace browser checks, including Windows/macOS settings adapters."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

from verify_browser import CDP

ROOT = Path(__file__).resolve().parents[1]


def sample_pdf():
    stream = b'BT /F1 18 Tf 40 720 Td (Alpha) Tj 0 -30 Td (Beta) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    raw = b'%PDF-1.4\n'
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += str(number).encode() + b' 0 obj\n' + content + b'\nendobj\n'
    xref = len(raw)
    raw += b'xref\n0 6\n0000000000 65535 f \n'
    raw += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return raw + b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'


class Fixture(BaseHTTPRequestHandler):
    counter = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ('/redirect', '/pdf-redirect'):
            self.send_response(302)
            self.send_header('Location', '/common' if self.path == '/redirect' else '/shared.pdf')
            self.end_headers()
            return
        if self.path == '/style.css':
            raw, mime = f'body{{background:rgb({230 + Fixture.counter},240,248)}}'.encode(), 'text/css'
        elif self.path == '/shared.pdf':
            raw, mime = sample_pdf(), 'application/pdf'
        elif self.path == '/next':
            raw, mime = b'<html><head></head><body><h1 id="next-page">Next page</h1><p>Alpha Beta</p></body></html>', 'text/html'
        else:
            if self.path == '/counter':
                Fixture.counter += 1
            raw = (f'<html><head><link rel="stylesheet" href="/style.css"></head><body><h1 id="common">Shared source</h1>'
                   f'<p>Alpha</p><p>Beta</p><p>Gamma</p><span id="counter">{Fixture.counter}</span>'
                   '<a id="next-link" href="/next">Next page</a></body></html>').encode()
            mime = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{fixture.server_port}'
    with tempfile.TemporaryDirectory(prefix='tablelens-source-browser-') as temporary:
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
            client.call('Emulation.setDeviceMetricsOverride', {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})

            def launch(platform=None):
                nonlocal app
                code = 'import editor; ' + (f'editor.sys.platform={platform!r}; ' if platform else '') + 'editor.main()'
                app = subprocess.Popen([sys.executable, '-B', '-c', code, '--no-browser', '--storage-dir', str(folder / 'workspace')],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       env={**os.environ, 'LC_ALL': 'ru_RU.UTF-8'})
                address = re.search(r'http://\S+', app.stdout.readline()).group(0)
                client.call('Page.navigate', {'url': address})
                client.wait("document.querySelector('#file-wizard')?.open")

            def import_table(name, text):
                payload = {'name': name, 'content': base64.b64encode(text.encode()).decode()}
                client.evaluate(f"(async()=>{{showWizardConfig(await api('import',{json.dumps(payload)}));}})()")
                client.wait("!!wizardState&&$('wizard-columns').querySelectorAll('tbody tr').length>0")
                client.evaluate("$('wizard-start').click()")
                client.wait("!!state&&!$('file-wizard').open&&!busy&&!wizardBusy")

            def open_address(path):
                client.evaluate(f"$('source-address').value={json.dumps(base + path)};$('source-address-row').requestSubmit()")

            def wait_common():
                client.wait("!!document.querySelector('#common')", frame=True)

            launch()
            assert not client.evaluate("$('source-address-row').hidden")
            assert client.evaluate("$('source-address-row').parentElement.id") == 'viewer-toolbar'
            assert client.evaluate("$('external').hidden")
            assert client.evaluate("$('zoom').closest('.zoom-group').parentElement.id") == 'viewer-search-row'
            assert client.evaluate("document.querySelector('.zoom-controls > span').hidden")
            import_table('no-links.tsv', 'Name\nAlpha\nBeta\nGamma\n')
            assert client.evaluate('state.links.length') == 0
            # The existing row-source endpoint keeps its authorization rules.
            result = client.evaluate(f"fetch('/api/source',{{method:'POST',headers:{{'X-Editor-Token':token,'Content-Type':'application/json'}},body:JSON.stringify({{index:0,url:{json.dumps(base + '/common')}}})}}).then(r=>r.status)")
            assert result == 400
            assert client.evaluate("fetch('/api/browser-source',{method:'POST',body:'{}'}).then(r=>r.status)") == 403
            open_address('/redirect')
            wait_common()
            client.wait("document.querySelector('mark[data-ue-hit]')?.textContent==='Alpha'", frame=True)
            assert client.evaluate("$('source-address').value") == base + '/common'
            client.evaluate("$('source-pin').click()")
            frame = client.evaluate("$('source-frame').src")
            version = client.evaluate('sourceVersion')
            client.evaluate("$('next').click()")
            client.wait('state.index===1&&!busy')
            client.wait("document.querySelector('mark[data-ue-hit]')?.textContent==='Beta'", frame=True)
            assert client.evaluate("$('source-frame').src") == frame
            assert client.evaluate('sourceVersion') == version
            assert client.evaluate("$('source-pin').getAttribute('aria-pressed')") == 'true'
            client.evaluate("document.querySelector('#next-link').click()", frame=True)
            client.wait("!!document.querySelector('#next-page')", frame=True)
            assert client.evaluate("$('source-address').value") == base + '/next'
            client.evaluate("$('source-back').click()")
            wait_common()
            client.evaluate("$('source-forward').click()")
            client.wait("!!document.querySelector('#next-page')", frame=True)
            assert client.evaluate('sourcePinned')
            print('Independent address, redirect, pin, row search, navigation and history: OK', flush=True)

            client.evaluate("$('viewer-find').value='missing value';$('find').click()")
            client.wait("!$('viewer-notice').hidden")
            assert client.evaluate("$('viewer-notice').parentElement.className") == 'source-stage'
            Path('/tmp/tablelens-no-match.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot')['data']))
            client.evaluate("$('viewer-notice-close').click();$('find').click()")
            client.evaluate('new Promise(resolve=>setTimeout(resolve,600))')
            assert client.evaluate("$('viewer-notice').hidden")
            client.evaluate("$('viewer-find').value='another missing value';$('find').click()")
            client.wait("!$('viewer-notice').hidden")
            client.evaluate("$('viewer-find').value='Beta';$('find').click()")
            client.wait("$('viewer-notice').hidden")
            print('Toolbar layout and dismissible no-match overlay: OK', flush=True)

            open_address('/counter')
            wait_common()
            initial = Fixture.counter
            client.evaluate("$('source-reload').click()")
            client.wait(f"document.querySelector('#counter')?.textContent==={json.dumps(str(initial + 1))}", frame=True)
            assert Fixture.counter == initial + 1
            client.wait(f"getComputedStyle(document.body).backgroundColor==='rgb({230 + Fixture.counter}, 240, 248)'", frame=True)
            address = client.evaluate('sourceURL')
            version = client.evaluate('sourceVersion')
            client.evaluate("$('source-address').value='javascript:alert(1)';$('source-address-row').requestSubmit()")
            assert client.evaluate('sourceURL') == address
            assert client.evaluate('sourceVersion') == version
            assert 'HTTP' in client.evaluate("$('viewer-status').textContent")
            client.evaluate("$('source-address').value=sourceURL;setEditorText($('col-0'),'Draft');$('col-0').dispatchEvent(new Event('input'));$('language-toggle').click()")
            assert client.evaluate('values()[0]') == 'Draft'
            assert client.evaluate("$('source-pin').title") == 'Unpin page and follow row links'
            assert client.evaluate("$('source-address').placeholder") == 'Page or website address'
            client.evaluate("if(theme!=='dark')switchTheme();$('viewer-status').textContent='';")
            client.evaluate('new Promise(resolve=>setTimeout(resolve,250))')
            Path('/tmp/tablelens-source-browser-dark.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot')['data']))
            client.evaluate("switchTheme();setEditorText($('col-0'),original[0]);$('col-0').dispatchEvent(new Event('input'))")
            client.evaluate('new Promise(resolve=>setTimeout(resolve,250))')
            Path('/tmp/tablelens-source-browser-light.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot')['data']))
            print('Reload, invalid addresses, unsaved edits, localization and both themes: OK', flush=True)

            open_address('/pdf-redirect')
            client.wait("!!pdfDoc&&!$('pdf-page').hidden&&pdfQuery==='Beta'")
            assert client.evaluate("$('source-address').value") == base + '/shared.pdf'
            version = client.evaluate('sourceVersion')
            client.evaluate("$('prev').click()")
            client.wait("state.index===0&&!busy&&pdfQuery==='Alpha'")
            assert client.evaluate('sourceVersion') == version
            assert client.evaluate('pdfMatches.length') == 1
            print('Pinned PDF, final redirect address and row search: OK', flush=True)

            # Explicit row links stay usable while pinned; unpin resumes automatic preview.
            client.evaluate("$('file-wizard').showModal()")
            client.evaluate('wizardState=null')
            import_table('links.tsv', f'Name\tSource\nAlpha\t{base}/common\nBeta\t{base}/next\n')
            wait_common()
            assert not client.evaluate('sourcePinned')
            client.evaluate("$('source-pin').click();$('next').click()")
            client.wait('state.index===1&&!busy')
            wait_common()
            client.evaluate("$('examples').querySelector('a').click()")
            client.wait("!!document.querySelector('#next-page')", frame=True)
            assert client.evaluate('sourcePinned')
            client.evaluate("$('prev').click()")
            client.wait('state.index===0&&!busy')
            client.evaluate("$('source-pin').click()")
            wait_common()
            assert not client.evaluate('sourcePinned')
            print('Document reset, explicit row links and unpinning: OK', flush=True)
            app.terminate()
            app.wait(timeout=10)
            app = None
            for platform in ['win32', 'darwin']:
                launch(platform)
                assert not client.evaluate("$('source-address-row').hidden")
                assert client.evaluate("$('external').hidden")
                assert client.evaluate('sourceBrowserEnabled')
                assert client.evaluate("$('zoom').closest('.zoom-group').parentElement.id") == 'viewer-search-row'
                client.evaluate('wizardState=null')
                import_table(platform + '.tsv', 'Name\nAlpha\nBeta\n')
                open_address('/common')
                wait_common()
                client.evaluate("$('source-pin').click();$('next').click()")
                client.wait('state.index===1&&!busy')
                client.wait("document.querySelector('mark[data-ue-hit]')?.textContent==='Beta'", frame=True)
                assert client.evaluate('sourcePinned')
                client.evaluate("$('viewer-find').value='missing';$('find').click()")
                client.wait("!$('viewer-notice').hidden&&$('viewer-notice').classList.contains('no-match')")
                assert client.evaluate("$('viewer-notice-title').textContent") == 'Совпадений не найдено'
                client.evaluate("$('viewer-notice-close').click()")
                assert client.evaluate("$('viewer-notice').hidden")
                app.terminate()
                app.wait(timeout=10)
                app = None
            print('Windows/macOS adapters: address, pin, row search, layout and notice enabled: OK', flush=True)
        finally:
            if app is not None:
                app.terminate()
                app.wait(timeout=10)
            if chrome.poll() is None:
                os.killpg(chrome.pid, signal.SIGTERM)
            chrome.wait(timeout=10)
            fixture.shutdown()
            fixture.server_close()


if __name__ == '__main__':
    main()
