"""Bundle portable CPython and pure Python spreadsheet libraries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'linux-x64': 'x86_64-unknown-linux-gnu',
           'linux-arm64': 'aarch64-unknown-linux-gnu',
           'windows-x64': 'x86_64-pc-windows-msvc',
           'macos-x64': 'x86_64-apple-darwin',
           'macos-arm64': 'aarch64-apple-darwin'}


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'TableLens-Packager'}), timeout=120) as response:
        return response.read()


def main():
    release = json.loads(fetch('https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest'))
    manifest = {'release': release['tag_name'], 'runtimes': {}, 'libraries': {}}
    assets = release['assets']
    def runtime(item):
        label, target = item
        folder = ROOT/'runtime'/label
        marker = folder/'bundle.json'
        if marker.exists():
            metadata = json.loads(marker.read_text())
            print('Already bundled:', label, flush=True)
            return label, metadata
        candidates = [asset for asset in assets if re.fullmatch(
            r'cpython-3\.13\.\d+\+[^/]+-'+re.escape(target)+r'-install_only\.tar\.gz', asset['name'])]
        if not candidates:
            raise RuntimeError('No runtime for '+label)
        asset = candidates[0]
        print('Downloading:', asset['name'], flush=True)
        raw = fetch(asset['browser_download_url'])
        digest = hashlib.sha256(raw).hexdigest()
        expected = asset.get('digest')
        if expected and expected != 'sha256:'+digest:
            raise RuntimeError('Checksum mismatch: '+asset['name'])
        if not expected:
            checksum = next((other for other in assets if other['name']==asset['name']+'.sha256'), None)
            if checksum:
                expected = fetch(checksum['browser_download_url']).decode().split()[0]
                if expected != digest:
                    raise RuntimeError('Checksum mismatch: '+asset['name'])
        folder.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            archive.extractall(folder, filter='data')
        metadata = {'url': asset['browser_download_url'], 'sha256': digest, 'archive': asset['name']}
        marker.write_text(json.dumps(metadata, indent=2))
        print('Bundled:', label, len(raw)//1_000_000, 'MB compressed', flush=True)
        return label, metadata
    with ThreadPoolExecutor(max_workers=3) as pool:
        for label, metadata in pool.map(runtime, TARGETS.items()):
            manifest['runtimes'][label] = metadata
    libraries = ROOT/'libraries'
    libraries.mkdir(exist_ok=True)
    for name in ('et-xmlfile', 'openpyxl', 'xlrd', 'pyxlsb'):
        package = json.loads(fetch('https://pypi.org/pypi/'+name+'/json'))
        wheel = next(item for item in package['urls'] if item['filename'].endswith('none-any.whl'))
        raw = fetch(wheel['url'])
        digest = hashlib.sha256(raw).hexdigest()
        if digest != wheel['digests']['sha256']:
            raise RuntimeError('Checksum mismatch: '+name)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for info in archive.infolist():
                target = (libraries/info.filename).resolve()
                if not target.is_relative_to(libraries.resolve()):
                    raise RuntimeError('Invalid wheel path')
            archive.extractall(libraries)
        manifest['libraries'][name] = {'version': package['info']['version'], 'url': wheel['url'], 'sha256': digest}
        print('Bundled library:', name, package['info']['version'], flush=True)
    (ROOT/'BUNDLE_MANIFEST.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
