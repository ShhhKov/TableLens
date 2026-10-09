"""Browser checks against temporary fixtures, using the installed Chrome and bundled Python."""
import base64
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


class CDP:
    def __init__(self, url):
        parsed = urlsplit(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response = b''
        while b'\r\n\r\n' not in response:
            response += self.sock.recv(1)
        assert b'101' in response.split(b'\r\n')[0], response
        self.number = 0
        self.contexts = {}

    def read(self, length):
        content = b''
        while len(content)<length:
            chunk = self.sock.recv(length-len(content))
            if not chunk:
                raise RuntimeError('Chrome connection closed')
            content += chunk
        return content

    def receive(self):
        first, second = self.read(2)
        length = second & 127
        if length==126:
            length = struct.unpack('!H', self.read(2))[0]
        elif length==127:
            length = struct.unpack('!Q', self.read(8))[0]
        mask = self.read(4) if second&128 else None
        raw = self.read(length)
        if mask:
            raw = bytes(value ^ mask[index%4] for index,value in enumerate(raw))
        if first&15!=1:
            return self.receive()
        return json.loads(raw)

    def call(self, method, params=None):
        self.number += 1
        number = self.number
        raw = json.dumps({'id': number, 'method': method, 'params': params or {}}).encode()
        mask = os.urandom(4)
        header = bytes([0x81, 0x80|len(raw)]) if len(raw)<126 else bytes([0x81,0xfe])+struct.pack('!H',len(raw))
        self.sock.sendall(header+mask+bytes(value^mask[index%4] for index,value in enumerate(raw)))
        while True:
            message = self.receive()
            if message.get('method')=='Runtime.executionContextCreated':
                context = message['params']['context']
                if context.get('auxData', {}).get('isDefault'):
                    self.contexts[context['auxData'].get('frameId')] = context['id']
            if message.get('id')==number:
                if 'error' in message:
                    raise RuntimeError(str(message['error']))
                return message.get('result', {})

    def evaluate(self, expression, frame=False):
        args = {'expression': expression, 'returnByValue': True, 'awaitPromise': True}
        if frame:
            tree = self.call('Page.getFrameTree')['frameTree']
            child = next(child for child in tree.get('childFrames', []) if '__ue_frame' in child['frame']['url'])
            args['contextId'] = self.contexts[child['frame']['id']]
        result = self.call('Runtime.evaluate', args)
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'].get('text', '')+str(result.get('result')))
        return result.get('result', {}).get('value')

    def wait(self, expression, frame=False, timeout=45):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                value = self.evaluate(expression, frame)
                if value:
                    return value
            except (KeyError, StopIteration, RuntimeError):
                pass
            time.sleep(.15)
        raise RuntimeError('Timeout: '+expression+'; viewer='+str(self.evaluate("document.querySelector('#viewer-status')?.textContent")))


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path=='/site.css':
            raw, mime = b'body{background:rgb(12,34,56)}#panel{color:red}', 'text/css'
        elif self.path=='/next':
            raw, mime = b'<html><body><h1 id="next-page">Next page</h1></body></html>', 'text/html'
        else:
            raw, mime = b'''<html><head><link rel="preload" as="style" href="/site.css" onload="this.rel='stylesheet'"></head><body><h1>Target</h1><button id="toggle" onclick="document.getElementById('panel').hidden=!document.getElementById('panel').hidden">Toggle</button><div id="panel" hidden>Expanded</div><a id="link" href="/next" target="_blank">Next</a></body></html>''', 'text/html'
        self.send_response(200);self.send_header('Content-Type', mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


def main():
    fixture = ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=fixture.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='ue-browser-',ignore_cleanup_errors=True) as folder:
        folder=Path(folder)
        chrome = subprocess.Popen(['/usr/bin/google-chrome-stable','--headless=new','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-port=0','--user-data-dir='+str(folder/'profile'),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            for _ in range(200):
                portfile=folder/'profile'/'DevToolsActivePort'
                if portfile.exists():
                    break
                time.sleep(.1)
            port=int(portfile.read_text().splitlines()[0])
            targets=json.load(urlopen(f'http://127.0.0.1:{port}/json'))
            client=CDP(next(item['webSocketDebuggerUrl'] for item in targets if item['type']=='page'))
            client.call('Page.enable');client.call('Runtime.enable')
            for universal in (False,True):
                path=folder/('universal.csv' if universal else 'classic.tsv')
                with path.open('w',newline='',encoding='utf-8') as stream:
                    writer=csv.writer(stream,delimiter=',' if universal else '\t')
                    writer.writerow(['Name','URL'] if universal else ['action','proposed_name','category','distinguishing','aliases','examples','key'])
                    writer.writerow(['Target',f'http://127.0.0.1:{fixture.server_port}/ || https://nevrolog-gomel.by/price/'] if universal else ['approve','Target','cat','detail','a; b',f'Target | Org | http://127.0.0.1:{fixture.server_port}/ || Target | Org | https://nevrolog-gomel.by/price/','key'])
                cmd=([str(ROOT/'Launch.sh'),'--no-browser'] if universal else [str(ROOT/'runtime/linux-x64/python/bin/python3'),'-B',str(ROOT.parent/'tsv_editor.py'),'--no-browser'])
                if universal:
                    cmd+=['--storage-dir',str(folder/'storage')]
                else:
                    cmd.append(str(path))
                app=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    line=app.stdout.readline();address=re.search(r'http://\S+',line).group(0)
                    client.call('Page.navigate',{'url':address})
                    if universal:
                        client.wait("document.querySelector('#file-wizard')?.open")
                        root=client.call('DOM.getDocument')['root']['nodeId']
                        node=client.call('DOM.querySelector',{'nodeId':root,'selector':'#file-input'})['nodeId']
                        client.call('DOM.setFileInputFiles',{'nodeId':node,'files':[str(path)]})
                        client.wait("!document.querySelector('#wizard-config').hidden&&!document.querySelector('#wizard-start').disabled")
                        client.evaluate("document.querySelector('#wizard-start').click()")
                    client.wait("document.querySelector('#viewer-status').textContent.includes('Найдено:')")
                    client.wait("getComputedStyle(document.body).backgroundColor==='rgb(12, 34, 56)'",frame=True)
                    assert client.evaluate("document.querySelector('#panel').hidden",frame=True)
                    client.evaluate("document.querySelector('#toggle').click()",frame=True)
                    assert not client.evaluate("document.querySelector('#panel').hidden",frame=True)
                    client.evaluate("document.querySelector('#link').click()",frame=True)
                    client.wait("!!document.querySelector('#next-page')",frame=True)
                    assert len([item for item in json.load(urlopen(f'http://127.0.0.1:{port}/json')) if item['type']=='page'])==1
                    client.evaluate("document.querySelector('#source-back').click()")
                    client.wait("!!document.querySelector('#toggle')",frame=True)
                    client.wait("getComputedStyle(document.body).backgroundColor==='rgb(12, 34, 56)'",frame=True)
                    print(('Universal' if universal else 'Classic')+': CSS preload, collapse, in-panel navigation, back, highlighting OK',flush=True)
                    if universal:
                        client.evaluate("setEditorText(document.querySelector('#col-0'),'Changed');document.querySelector('#col-0').dispatchEvent(new Event('input'));document.querySelector('#save').click()")
                        client.wait("!document.querySelector('#download').disabled")
                        assert path.read_text().find('Changed')==-1
                        print('Universal: upload, column setup and saving copy OK',flush=True)
                    if '--live' in sys.argv:
                        client.evaluate("loadPreview('https://nevrolog-gomel.by/price/')")
                        client.wait("previewOrigin&&sourceURL.includes('nevrolog-gomel.by')",timeout=45)
                        time.sleep(3)
                        client.wait("window.__uePreview?.remoteOrigin?.includes('nevrolog-gomel.by')&&!!document.body",frame=True,timeout=60)
                        client.wait("document.styleSheets.length>0",frame=True,timeout=30)
                        fonts=client.evaluate("({font:getComputedStyle(document.body).fontFamily,styles:document.styleSheets.length})",frame=True)
                        assert fonts['styles']>0 and 'Times New Roman' not in fonts['font']
                        print(('Universal' if universal else 'Classic')+': live clinic CSS loaded '+str(fonts),flush=True)
                        if universal:
                            screenshot=client.call('Page.captureScreenshot',{'format':'png'})['data']
                            (ROOT/'packaging'/'live-source.png').write_bytes(base64.b64decode(screenshot))
                finally:
                    app.terminate();app.wait(timeout=10)
        finally:
            os.killpg(chrome.pid,signal.SIGTERM);chrome.wait(timeout=10);time.sleep(.4)
    fixture.shutdown();fixture.server_close()


if __name__=='__main__':
    main()
