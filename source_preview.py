"""Interactive source pages on a separate local origin, isolated from the editor."""
import html
import json
import re
import secrets
import ssl
import threading
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urldefrag, parse_qs, quote
from urllib.request import Request, urlopen


class SourcePreview:
    def __init__(self):
        self.frames = {}
        self.allowed = set()
        self.resources = set()
        self.active_origin = None
        self.parent_origin = None
        self.lock = threading.RLock()
        self.bridge = Path(__file__).with_name('source_bridge.js').read_text(encoding='utf-8')
        manager = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                try:
                    if self.path.startswith('/__ue_frame/'):
                        key = self.path.split('/', 2)[2].split('?', 1)[0]
                        with manager.lock:
                            record = manager.frames.get(key)
                            if not record:
                                raise ValueError('Страница устарела. Откройте ссылку заново.')
                            manager.active_origin = record['origin']
                            raw, mime = record['html'].encode('utf-8'), 'text/html; charset=utf-8'
                    elif self.path.startswith('/__ue_resource?'):
                        target = parse_qs(urlsplit(self.path).query).get('url', [''])[0]
                        with manager.lock:
                            if target not in manager.resources:
                                raise ValueError('Неизвестный ресурс.')
                        raw, mime = manager.resource(target)
                    else:
                        with manager.lock:
                            origin = manager.active_origin
                        if not origin or self.path.startswith('//'):
                            raise ValueError('Источник не выбран.')
                        raw, mime = manager.resource(origin+self.path)
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-store' if mime.startswith('text/html') else 'private, max-age=3600')
                    self.end_headers()
                    self.wfile.write(raw)
                except Exception as error:
                    raw = html.escape(str(error)).encode('utf-8')
                    self.send_response(502)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def permits(self, url):
        target = urlsplit(url)
        return (urldefrag(url)[0] in self.allowed or any(
            (parsed.scheme, parsed.netloc) == (target.scheme, target.netloc)
            for parsed in map(urlsplit, self.allowed)))

    def prepare(self, document):
        url = document['url']
        parsed = urlsplit(url)
        origin = parsed.scheme+'://'+parsed.netloc
        content = document['html']
        original_base = re.search(r'<base\b[^>]*href\s*=\s*[\x22\x27]([^\x22\x27]+)', content, re.I)
        base_url = urljoin(url, html.unescape(original_base[1])) if original_base else url
        base_parsed = urlsplit(base_url)
        if document.get('kind') == 'text':
            content = '<html><head></head><body><pre>'+html.escape(content)+'</pre></body></html>'
        with self.lock:
            self.allowed.add(urldefrag(url)[0])
            for target in re.findall(r'(?:href|action|data-href)\s*=\s*[\x22\x27]([^\x22\x27]+)', content, re.I):
                target = urljoin(base_url, html.unescape(target))
                if target.startswith(('https://', 'http://')):
                    self.allowed.add(urldefrag(target)[0])
            for target in re.findall(r'https?://[^\s<>\x22\x27]+', content):
                self.allowed.add(urldefrag(html.unescape(target))[0])
            self.active_origin = origin
            key = secrets.token_urlsafe(24)
            # Keep original scripts, forms and CSS loading hooks. Assets from the
            # same site resolve through this origin, retaining their normal paths.
            content = re.sub(r'<base\b[^>]*>', '', content, flags=re.I)
            content = re.sub(r'<meta\b[^>]*http-equiv\s*=\s*[\x22\x27]?(?:Content-Security-Policy|refresh)[^>]*>', '', content, flags=re.I)
            content = content.replace(origin, self.origin)
            def rewrite_tag(match):
                tag = match[0]
                def rewrite_attribute(attribute):
                    target = html.unescape(attribute[3])
                    if target.startswith('//'):
                        target = parsed.scheme+':'+target
                    if target.startswith(('http://', 'https://')) and not target.startswith(self.origin+'/'):
                        self.resources.add(target)
                        return attribute[1]+attribute[2]+self.origin+'/__ue_resource?url='+quote(target, safe='')+attribute[2]
                    return attribute[0]
                return re.sub(r'((?:src|href)\s*=\s*)([\x22\x27])([^\x22\x27]+)\2', rewrite_attribute, tag, flags=re.I)
            content = re.sub(r'<(?:script|link|img|source|video|audio)\b[^>]*>', rewrite_tag, content, flags=re.I)
            settings = {'key': key, 'source': url, 'remoteOrigin': origin,
                        'proxyOrigin': self.origin, 'parentOrigin': self.parent_origin}
            mapped_base = self.origin+base_parsed.path+('?' + base_parsed.query if base_parsed.query else '')
            if base_parsed.netloc != parsed.netloc:
                mapped_base = base_url
            injected = '<base href="'+html.escape(mapped_base, quote=True)+'">'
            injected += '<script>window.__uePreview='+json.dumps(settings, ensure_ascii=True).replace('<','\\u003c')+';</script><script>'+self.bridge+'</script>'
            if re.search(r'<head\b[^>]*>', content, re.I):
                content = re.sub(r'(<head\b[^>]*>)', lambda match: match[0]+injected, content, count=1, flags=re.I)
            else:
                content = injected+content
            self.frames[key] = {'origin': origin, 'html': content}
            if len(self.frames)>24:
                del self.frames[next(iter(self.frames))]
        return {'kind': 'interactive', 'url': url, 'preview_url': self.origin+'/__ue_frame/'+key, 'bridge_key': key}

    @lru_cache(maxsize=128)
    def resource(self, url):
        try:
            from pip._vendor import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0 Universal-Editor', 'Accept-Encoding': 'identity'})
        # A blocked third-party widget must not stall the document parser forever.
        with urlopen(request, timeout=8, context=context) as response:
            raw = response.read(40_000_001)
            if len(raw)>40_000_000:
                raise ValueError('Источник больше 40 МБ.')
            mime = response.headers.get('Content-Type', 'application/octet-stream')
            if response.headers.get_content_type() in ('text/html', 'text/css', 'application/javascript', 'text/javascript'):
                charset = response.headers.get_content_charset() or 'utf-8'
                content = raw.decode(charset, errors='replace')
                remote_origin = urlsplit(url).scheme+'://'+urlsplit(url).netloc
                content = content.replace(remote_origin, self.origin)
                raw = content.encode('utf-8')
                mime = response.headers.get_content_type()+'; charset=utf-8'
            return raw, mime
