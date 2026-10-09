"""Create portable OS archives. No compilation or system Python is needed to run."""
import argparse
import os
import stat
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {'Linux': ('linux-x64', 'linux-arm64')}


def make_desktop():
    # %k is the location of this desktop file, allowing the folder to be moved.
    command = 'launcher="$1"; case "$launcher" in file://*) launcher="${launcher#file://}";; esac; exec "$(dirname "$launcher")/Launch.sh"'
    quoted = '"'+command.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')+'"'
    desktop = ROOT/'TableLens.desktop'
    desktop.write_text('[Desktop Entry]\nVersion=1.0\nType=Application\nName=TableLens\n'
                       'Comment=Edit tables. Verify sources.\nTerminal=true\n'
                       'Icon=accessories-text-editor\nCategories=Office;\nExec=/bin/sh -c '+quoted+' sh %k\n', encoding='utf-8')
    desktop.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description='Create portable TableLens archives')
    parser.add_argument('--platform', choices=PACKAGES, help='Build only this platform')
    args = parser.parse_args()
    make_desktop()
    for name in ('Launch.sh', 'Launch.command'):
        (ROOT/name).chmod(0o755)
    packages = ROOT/'packages'
    packages.mkdir(exist_ok=True)
    for platform, runtimes in PACKAGES.items():
        if args.platform and platform != args.platform:
            continue
        archive_path = packages/f'TableLens-{platform}.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in ROOT.rglob('*'):
                relative = path.relative_to(ROOT)
                if relative.parts[0] in ('packages', 'workspace', 'packaging', '__pycache__'):
                    continue
                if relative.name in ('Launch.cmd', 'Launch.command'):
                    continue
                if '__pycache__' in relative.parts or path.suffix=='.pyc':
                    continue
                if relative.parts[0]=='runtime' and len(relative.parts)>1 and relative.parts[1] not in runtimes:
                    continue
                if path.is_symlink():
                    info = zipfile.ZipInfo(str(Path('TableLens')/relative))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, os.readlink(path))
                elif path.is_file():
                    archive.write(path, Path('TableLens')/relative)
        print(archive_path.name, archive_path.stat().st_size//1_000_000, 'MB', flush=True)


if __name__ == '__main__':
    main()
