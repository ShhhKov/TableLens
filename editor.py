#!/usr/bin/env python3
"""TableLens: local spreadsheet editor with source preview."""
import argparse
import csv
import base64
import sys
import ssl
import copy
import hashlib
import io
import json
import locale
import os
import plistlib
from pathlib import Path
import re
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache
import tempfile
import threading
import time
import webbrowser
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, parse_qs, quote


sys.path.insert(0, str(Path(__file__).resolve().parent / 'libraries'))
from table_formats import TableFile, SUPPORTED

from source_preview import SourcePreview

# Ссылки с http(s):// или голые адреса вроде www.site.ru и google.com/page. Голый домен
# считается ссылкой только с известной зоной, чтобы file.txt, v1.2 и почта оставались текстом.
# Шаблон совместим с JavaScript и передаётся в editor.html как есть.
_LETTER = r'a-z\d\u0400-\u04ff'
_LABEL = rf'[{_LETTER}](?:[{_LETTER}-]*[{_LETTER}])?'
_ZONES = ('com|ru|org|net|info|biz|io|su|рф|рус|ua|by|kz|uz|am|ge|kg|me|co|uk|de|fr|eu|us|it|es|nl'
          '|ch|at|jp|cn|ca|au|app|dev|ai|edu|gov|pro|online|site|shop|store|tech|tv|xyz|ws|top|ltd')
URL_PATTERN = (rf'https?://[^\s<>"|]+|(?<![{_LETTER}_@./:-])(?:www\.{_LABEL}(?:\.{_LABEL})+|(?:{_LABEL}\.)+(?:{_ZONES}))'
               rf'(?![{_LETTER}_@-]|\.[{_LETTER}])(?::\d{{1,5}})?(?:[/?#][^\s<>"|]*)?')
URL = re.compile(URL_PATTERN, re.IGNORECASE)


def find_urls(text):
    return [url if re.match(r'https?://', url, re.IGNORECASE) else 'https://' + url
            for url in (match.rstrip('.,;)]}') for match in URL.findall(text))]


ACTIONS = ('approve', 'reject', 'rewiev')


def mac_preferences():
    """Read the current global macOS preferences without changing them."""
    try:
        result = subprocess.run(['/usr/bin/defaults', 'export', 'NSGlobalDomain', '-'],
                                capture_output=True, timeout=2, check=True)
        preferences = plistlib.loads(result.stdout)
        return preferences if isinstance(preferences, dict) else {}
    except (OSError, subprocess.SubprocessError, ValueError, plistlib.InvalidFileException):
        return {}


def system_language():
    """Use the device UI language; languages other than Russian use English."""
    if sys.platform == 'win32':
        import ctypes
        try:
            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if language_id:
                return 'ru' if language_id & 0x3ff == 0x19 else 'en'
        except (OSError, AttributeError):
            pass
    elif sys.platform == 'darwin':
        languages = mac_preferences().get('AppleLanguages', [])
        if isinstance(languages, list) and languages and isinstance(languages[0], str):
            return 'ru' if re.match(r'^ru(?:[-_]|$)', languages[0], re.IGNORECASE) else 'en'
    selected = (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES')
                or os.environ.get('LANG') or locale.getlocale()[0] or '')
    # LANGUAGE can override the message locale, except in the C/POSIX locale.
    if selected.split('.')[0].upper() not in ('C', 'POSIX'):
        selected = os.environ.get('LANGUAGE', '').split(':')[0] or selected
    return 'ru' if re.match(r'^ru(?:[_\-.]|$)', selected, re.IGNORECASE) else 'en'


def system_theme():
    """Read desktop preferences; let the browser decide if unavailable."""
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                return 'dark' if value == 0 else 'light'
        except (ImportError, OSError):
            return 'auto'
    if sys.platform == 'darwin':
        preferences = mac_preferences()
        if preferences:
            return 'dark' if preferences.get('AppleInterfaceStyle') == 'Dark' else 'light'
        return 'auto'
    if not sys.platform.startswith('linux'):
        return 'auto'
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    if 'kde' in desktop:
        import configparser
        config = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            config.read(Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'kdeglobals')
            scheme = config.get('General', 'ColorScheme', fallback='')
            if scheme:
                return 'dark' if 'dark' in scheme.lower() else 'light'
        except (OSError, configparser.Error):
            pass
    for key in ('color-scheme', 'gtk-theme'):
        try:
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', key],
                capture_output=True, text=True, timeout=2, check=True)
            value = result.stdout.strip().strip("'\"").lower()
            if key == 'color-scheme' and value in ('prefer-dark', 'prefer-light'):
                return value.removeprefix('prefer-')
            if key == 'gtk-theme' and 'dark' in value:
                return 'dark'
        except (OSError, subprocess.SubprocessError):
            pass
    return 'auto'


class Editor:
    def __init__(self, path, options=None):
        self.folder = Path(path).parent.resolve()
        self.allowed = {Path(path).resolve()}
        self.load(path, options)

    def load(self, path, options=None):
        path = Path(path).resolve()
        if path not in self.allowed:
            raise ValueError('Файл недоступен в этом сеансе.')
        source_raw = path.read_bytes()
        suffix = '.xlsx' if path.suffix.lower() in ('.xls', '.xlsb') else path.suffix
        output_path = path.with_name(path.stem + '.edited' + suffix)
        output_exists = output_path.exists()
        raw = output_path.read_bytes() if output_exists else source_raw
        self.table = TableFile(output_path if output_exists else path, raw, options)
        self.path, self.headers, self.rows = path, self.table.headers, self.table.rows
        self.output_path = output_path
        self.source_digest = hashlib.sha256(source_raw).digest()
        self.output_digest = hashlib.sha256(raw).digest() if output_exists else None
        self.digest = hashlib.sha256(raw).digest()
        self.columns = [{'index': i, 'name': name or f'Колонка {i+1}',
                         'mode': 'read' if name == 'examples' or any(URL.search(row[i]) for row in self.rows[:50] if i < len(row)) else 'edit',
                         'review': name in ('proposed_name', 'distinguishing'),
                         'choices': list(ACTIONS) if name == 'action' else []}
                        for i, name in enumerate(self.headers)]
        self.search_column = next((i for i, name in enumerate(self.headers) if name == 'examples'), 0)
        self.backup = None
        self.backup_created = False
        self.revision = secrets.token_hex(12)
        self.position = 0
        self.skipped = set()
        self.processed = set()
        self.cycle = None
        self.layout_width = 51
        try:
            progress = json.loads(self.progress_path.read_text(encoding='utf-8'))
            self.position = min(max(int(progress['position']), 0), max(len(self.rows) - 1, 0))
            self.skipped = {index for index in progress.get('skipped', [])
                            if type(index) is int and 0 <= index < len(self.rows)}
            self.processed = {index for index in progress.get('processed', [])
                              if type(index) is int and 0 <= index < len(self.rows)}
            width = progress.get('layout_width', 51)
            if type(width) in (int, float) and 5 <= width <= 95:
                self.layout_width = width
            stored_columns = progress.get('columns')
            if self.valid_columns(stored_columns):
                self.columns = [{**col, 'name': self.headers[i] or f'Колонка {i+1}'}
                                for i, col in enumerate(stored_columns)]
            selected = progress.get('search_column', self.search_column)
            if type(selected) is int and 0 <= selected < len(self.headers):
                self.search_column = selected
            cycle = progress.get('cycle')
            if self.valid_cycle(cycle):
                self.cycle = cycle
                self.position = cycle['queue'][0]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @property
    def progress_path(self):
        sheet_key = hashlib.sha256(str(self.table.sheet).encode()).hexdigest()[:10] if self.table.sheet else 'text'
        header_key = 'header' if self.table.has_header else 'noheader'
        return self.path.with_name(self.path.name + '.' + sheet_key + '.' + header_key + '.editor-progress.json')

    def valid_cycle(self, cycle):
        if not isinstance(cycle, dict):
            return False
        origin, queue, rules = cycle.get('origin'), cycle.get('queue'), cycle.get('rules')
        return (type(origin) is int and 0 <= origin < len(self.rows)
                and isinstance(queue, list) and bool(queue)
                and len(set(queue)) == len(queue)
                and all(type(index) is int and 0 <= index < len(self.rows) for index in queue)
                and isinstance(rules, list) and bool(rules)
                and all(isinstance(rule, dict) and type(rule.get('column')) is int
                        and 0 <= rule['column'] < len(self.headers)
                        and self.columns[rule['column']]['review'] and self.columns[rule['column']]['mode'] == 'edit'
                        and isinstance(rule.get('old'), str) and isinstance(rule.get('new'), str)
                        for rule in rules)
                and type(cycle.get('total')) is int and cycle['total'] >= len(queue))

    def write_progress(self, position, skipped, processed, cycle):
        payload = {'position': position, 'skipped': sorted(skipped),
                   'processed': sorted(processed), 'cycle': cycle,
                   'layout_width': self.layout_width, 'columns': self.columns,
                   'search_column': self.search_column, 'options': self.table.options}
        self.atomic_write(self.progress_path, json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def main_step(self, index, direction=1, processed=None, skipped=None):
        processed = self.processed if processed is None else processed
        skipped = self.skipped if skipped is None else skipped
        number = index + direction
        while 0 <= number < len(self.rows):
            if number not in processed and number not in skipped:
                return number
            number += direction
        return None

    def cycle_after_current(self, cycle, processed, skipped=None):
        cycle['queue'].pop(0)
        if cycle['queue']:
            return cycle['queue'][0], cycle
        next_index = self.main_step(cycle['origin'], processed=processed, skipped=skipped)
        return (cycle['origin'] if next_index is None else next_index), None

    def view(self, index=None):
        if index is None:
            index = self.position
        index = min(max(int(index), 0), max(len(self.rows) - 1, 0))
        if self.cycle and index != self.cycle['queue'][0]:
            raise ValueError('Завершите просмотр совпадений или отложите оставшиеся.')
        values = self.rows[index] if self.rows else []
        values = values + [''] * (len(self.headers) - len(values))
        visible_values = [value for column, value in zip(self.columns, values) if column['mode'] != 'hidden']
        links = list(dict.fromkeys(url for value in visible_values for url in find_urls(value)))
        for column in self.columns:
            if column['mode'] != 'hidden':
                for link in self.table.links.get((index, column['index']), []):
                    if link.startswith(('http://', 'https://')) and link not in links:
                        links.append(link)
        match_counts = {
            str(column): sum((row[column] if column < len(row) else '') == values[column]
                             for row in self.rows)
            for column, name in enumerate(self.headers) if self.columns[column]['review'] and self.columns[column]['mode'] == 'edit'
        }
        name_column = next((column['index'] for column in self.columns if column['mode'] != 'hidden'), None)
        skipped = [{'index': number,
                    'name': (self.rows[number][name_column]
                             if name_column is not None and name_column < len(self.rows[number]) else '')}
                   for number in sorted(self.skipped)]
        return {'file': self.path.name, 'files': sorted(p.name for p in self.allowed),
                'headers': self.headers, 'values': values, 'index': index,
                'total': len(self.rows), 'links': links, 'revision': self.revision,
                'columns': self.columns, 'match_counts': match_counts,
                'sheet': self.table.sheet, 'sheets': self.table.sheets, 'options': self.table.options,
                'notice': self.table.notice, 'search_column': self.search_column,
                'cell_links': {str(col['index']): self.table.links.get((index, col['index']), []) for col in self.columns if col['mode'] != 'hidden'},
                'output_ready': self.output_path.exists(),
                'review_columns': [col['index'] for col in self.columns if col['review'] and col['mode'] == 'edit'],
                'cycle': self.cycle_view(index, values),
                'next_index': self.main_step(index), 'prev_index': self.main_step(index, -1),
                'processed': sorted(self.processed),
                'layout_width': self.layout_width,
                'skipped': skipped, 'is_skipped': index in self.skipped,
                'output_file': self.output_path.name,
                'backup': str(self.backup) if self.backup else None}

    def cycle_view(self, index, values):
        if not self.cycle:
            return None
        suggestions = [{'column': rule['column'], 'name': self.headers[rule['column']],
                        'old': rule['old'], 'new': rule['new']}
                       for rule in self.cycle['rules'] if values[rule['column']] == rule['old']]
        return {'origin': self.cycle['origin'], 'current': self.cycle['queue'][0],
                'remaining': len(self.cycle['queue']), 'total': self.cycle['total'],
                'suggestions': suggestions if index == self.cycle['queue'][0] else []}

    def save(self, data):
        if data.get('revision') != self.revision:
            raise ValueError('Данные изменились в другом окне. Перезагрузите страницу.')
        index, values = data['index'], data['values']
        if not isinstance(index, int) or not 0 <= index < len(self.rows):
            raise ValueError('Неверный номер строки.')
        if self.cycle and index != self.cycle['queue'][0]:
            raise ValueError('Сначала завершите просмотр текущего совпадения или отложите цикл.')
        if len(values) != len(self.headers) or any(not isinstance(v, str) for v in values):
            raise ValueError('Неверный набор полей.')
        current = self.rows[index] + [''] * (len(self.headers) - len(self.rows[index]))
        changes = []
        for column, (old, new) in enumerate(zip(current, values)):
            if old == new:
                continue
            name = self.headers[column]
            if self.columns[column]['mode'] != 'edit':
                raise ValueError(f'Колонку {name} редактировать запрещено.')
            choices = self.columns[column]['choices']
            if choices and new not in choices:
                raise ValueError(f'Выберите допустимое значение для {name}.')
            changes.append((column, old, new))
        self.check_files()
        cycle = copy.deepcopy(self.cycle)
        if cycle is None:
            rules = [{'column': column, 'old': old, 'new': new}
                     for column, old, new in changes if self.columns[column]['review'] and self.columns[column]['mode'] == 'edit']
            queue = []
            for rule in rules:
                column = rule['column']
                for number, row in enumerate(self.rows):
                    if (number != index and number not in queue
                            and (row[column] if column < len(row) else '') == rule['old']):
                        queue.append(number)
            if queue:
                cycle = {'origin': index, 'queue': queue, 'rules': rules, 'total': len(queue)}
        updated_rows, replacements = [], []
        for column, old, new in changes:
            replacements.append({'column': self.headers[column], 'count': 0})
        for row_index, row in enumerate(self.rows):
            updated = list(row)
            for change_index, (column, old, new) in enumerate(changes):
                applies = row_index == index
                if applies and (row[column] if column < len(row) else '') == old:
                    if column >= len(updated):
                        updated.extend([''] * (column + 1 - len(updated)))
                    updated[column] = new
                    replacements[change_index]['count'] += 1
            updated_rows.append(updated)
        raw = self.table.serialize(updated_rows)
        if not self.backup_created:
            if self.output_path.exists():
                backup = self.output_path.with_name(self.output_path.name + '.' + time.strftime('%Y%m%d-%H%M%S') + '.' + secrets.token_hex(3) + '.bak')
                with backup.open('xb') as stream:
                    stream.write(self.output_path.read_bytes())
                self.backup = backup
        self.atomic_write(self.output_path, raw)
        self.backup_created = True
        self.table = TableFile(self.output_path, raw, self.table.options)
        self.rows = self.table.rows
        self.digest = hashlib.sha256(raw).digest()
        self.output_digest = self.digest
        self.revision = secrets.token_hex(12)
        cycle_finished = False
        if self.cycle:
            self.processed.add(index)
            self.skipped.discard(index)
            self.position, cycle = self.cycle_after_current(cycle, self.processed)
            cycle_finished = cycle is None
        elif cycle:
            self.position = cycle['queue'][0]
        elif data.get('next'):
            following = self.main_step(index)
            self.position = index if following is None else following
        else:
            self.position = index
        self.cycle = cycle
        if data.get('next') or cycle:
            self.skipped.discard(index)
        warning = None
        try:
            self.write_progress(self.position, self.skipped, self.processed, self.cycle)
        except OSError:
            warning = 'Таблица сохранена, но записать прогресс на диск не удалось.'
        result = self.view()
        result['warning'] = warning
        result['replacements'] = replacements
        result['cycle_finished'] = cycle_finished
        return result

    def skip(self, data):
        if data.get('revision') != self.revision:
            raise ValueError('Данные изменились в другом окне. Перезагрузите страницу.')
        index = data['index']
        if type(index) is not int or not 0 <= index < len(self.rows):
            raise ValueError('Неверный номер строки.')
        self.check_files()
        if self.cycle and index != self.cycle['queue'][0]:
            raise ValueError('Сначала завершите просмотр текущего совпадения или отложите цикл.')
        skipped = set(self.skipped)
        if data.get('skip', True):
            skipped.add(index)
        else:
            skipped.discard(index)
        cycle = copy.deepcopy(self.cycle)
        cycle_finished = False
        if data.get('next') and cycle:
            position, cycle = self.cycle_after_current(cycle, self.processed, skipped)
            cycle_finished = cycle is None
        elif data.get('next'):
            following = self.main_step(index, skipped=skipped)
            position = index if following is None else following
        else:
            position = index
        self.write_progress(position, skipped, self.processed, cycle)
        self.skipped, self.position, self.cycle = skipped, position, cycle
        self.revision = secrets.token_hex(12)
        result = self.view()
        result['cycle_finished'] = cycle_finished
        return result

    def end_cycle(self, data):
        if data.get('revision') != self.revision or not self.cycle:
            raise ValueError('Цикл изменился. Перезагрузите страницу.')
        self.check_files()
        skipped = self.skipped | set(self.cycle['queue'])
        following = self.main_step(self.cycle['origin'], skipped=skipped)
        position = self.cycle['origin'] if following is None else following
        self.write_progress(position, skipped, self.processed, None)
        self.skipped, self.position, self.cycle = skipped, position, None
        self.revision = secrets.token_hex(12)
        result = self.view()
        result['cycle_finished'] = True
        return result

    def set_layout(self, data):
        width = data.get('width')
        if data.get('file') != self.path.name or type(width) not in (int, float) or not 5 <= width <= 95:
            raise ValueError('Неверная ширина панели или выбран другой файл.')
        previous = self.layout_width
        self.layout_width = width
        try:
            self.write_progress(self.position, self.skipped, self.processed, self.cycle)
        except OSError:
            self.layout_width = previous
            raise
        return {'ok': True}

    def valid_columns(self, columns):
        return (isinstance(columns, list) and len(columns) == len(self.headers)
                and all(isinstance(col, dict) and col.get('index') == i
                        and col.get('mode') in ('edit', 'read', 'hidden')
                        and type(col.get('review')) is bool
                        and isinstance(col.get('choices'), list)
                        and all(isinstance(value, str) for value in col['choices'])
                        for i, col in enumerate(columns)))

    def configure(self, data):
        if data.get('revision') != self.revision or self.cycle:
            raise ValueError('Сначала завершите цикл совпадений или перезагрузите страницу.')
        columns, search_column = data.get('columns'), data.get('search_column')
        if (not self.valid_columns(columns) or type(search_column) is not int
                or not 0 <= search_column < len(self.headers)
                or not any(col['mode'] != 'hidden' for col in columns)
                or columns[search_column]['mode'] == 'hidden'):
            raise ValueError('Проверьте настройки колонок. Хотя бы одна должна быть видна.')
        previous = self.columns, self.search_column
        self.columns = [{**col, 'name': self.headers[i] or f'Колонка {i+1}'} for i, col in enumerate(columns)]
        self.search_column = search_column
        try:
            self.write_progress(self.position, self.skipped, self.processed, self.cycle)
        except OSError:
            self.columns, self.search_column = previous
            raise
        self.revision = secrets.token_hex(12)
        return self.view(data.get('index', self.position))

    def check_files(self):
        if hashlib.sha256(self.path.read_bytes()).digest() != self.source_digest:
            raise ValueError('Исходный TSV изменён другой программой. Откройте файл заново.')
        current_digest = (hashlib.sha256(self.output_path.read_bytes()).digest()
                          if self.output_path.exists() else None)
        if current_digest != self.output_digest:
            raise ValueError('Файл результата изменён другой программой. Откройте файл заново.')

    @staticmethod
    def atomic_write(path, raw):
        fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                os.chmod(name, path.stat().st_mode & 0o777)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


BLOCKED_SOURCE = ('Сайт сбросил соединение: похоже, он заблокирован у вашего провайдера. '
                  'Включите VPN для всей системы, а не только для браузера.')


@lru_cache(maxsize=8)
def fetch_source(url):
    try:
        return download_source(url)
    except OSError as error:
        # DPI blocking shows up as a reset or a cut TLS handshake, not an HTTP error.
        if isinstance(getattr(error, 'reason', error), (ConnectionResetError, ssl.SSLEOFError)):
            raise ValueError(BLOCKED_SOURCE) from None
        raise


def download_source(url):
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 TableLens', 'Accept-Encoding': 'identity'})
    try:
        from pip._vendor import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with urlopen(request, timeout=25, context=context) as response:
        raw = response.read(40_000_001)
        if len(raw) > 40_000_000:
            raise ValueError('Источник больше 40 МБ. Откройте его в отдельной вкладке.')
        final_url = response.geturl()
        mime = response.headers.get_content_type()
        if raw.startswith(b'%PDF-') or mime == 'application/pdf':
            return raw, 'application/pdf', final_url
        if mime not in ('text/html', 'application/xhtml+xml', 'text/plain'):
            raise ValueError('Этот формат не поддерживается для встроенного просмотра.')
        charset = response.headers.get_content_charset()
        if not charset:
            meta = re.search(br'charset\s*=\s*[\x22\x27]?([\w-]+)', raw[:8192], re.I)
            charset = meta.group(1).decode('ascii') if meta else 'utf-8'
        try:
            content = raw.decode(charset)
        except (UnicodeError, LookupError):
            content = raw.decode('utf-8', errors='replace')
        return ({'kind': 'text' if mime == 'text/plain' else 'html', 'html': content, 'url': final_url},
                'application/json; charset=utf-8', final_url)


def default_storage_dir():
    if getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        else:
            base = Path.home() / '.local' / 'share'
        return base / 'TableLens' / 'workspace'
    return Path(__file__).resolve().parent / 'workspace'


def validate_browser_url(target):
    if not isinstance(target, str) or len(target) > 8192:
        raise ValueError('Введите корректный адрес HTTP или HTTPS.')
    try:
        parsed = urlsplit(target)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(character.isspace() for character in target)):
            raise ValueError
        parsed.port
    except ValueError:
        raise ValueError('Введите корректный адрес HTTP или HTTPS.') from None
    return target


def main():
    parser = argparse.ArgumentParser(description='TableLens: таблицы и источники')
    parser.add_argument('file', nargs='?', type=Path)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--storage-dir', type=Path, help='Папка для копий и результатов')
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    storage = args.storage_dir or default_storage_dir()
    storage.mkdir(parents=True, exist_ok=True)
    documents = {}
    for metadata_path in storage.glob('*/document.json'):
        try:
            meta = json.loads(metadata_path.read_text(encoding='utf-8'))
            path = (metadata_path.parent / meta['name']).resolve()
            if path.is_relative_to(metadata_path.parent.resolve()) and path.is_file():
                documents[metadata_path.parent.name] = {'path': path, 'options': meta.get('options', {})}
        except (OSError, ValueError, TypeError, KeyError):
            pass
    editor = None
    document_id = None
    token = secrets.token_urlsafe(32)
    html = ((folder / 'editor.html').read_text(encoding='utf-8')
            .replace('__TOKEN__', token).replace('__SYSTEM_LANGUAGE__', system_language())
            .replace('__SYSTEM_THEME__', system_theme())
            .replace('__SOURCE_BROWSER_ENABLED__', 'true')
            .replace('__URL_PATTERN__', json.dumps(URL_PATTERN)))
    editor_lock = threading.RLock()
    preview = SourcePreview()

    def current_view(index=None):
        if editor is None:
            return {'empty': True, 'recent': [{'id': key, 'name': value['path'].name}
                                            for key, value in documents.items()]}
        result = editor.view(index)
        result['document_id'] = document_id
        return result

    def import_document(name, raw):
        name = Path(name.replace('\\', '/')).name
        if not name or name in ('.', '..') or len(name)>240 or '\x00' in name:
            raise ValueError('Некорректное имя файла.')
        if Path(name).suffix.lower() not in SUPPORTED:
            raise ValueError('Выберите TSV, CSV, TXT, XLSX, XLSM, ODS, XLS или XLSB.')
        key = hashlib.sha256(name.encode()+b'\0'+raw).hexdigest()[:24]
        target = storage/key/name
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            Editor.atomic_write(target, raw)
        documents[key] = documents.get(key, {'path': target, 'options': {}})
        return key

    def open_document(key, options=None):
        nonlocal editor, document_id
        if key not in documents:
            raise ValueError('Выберите файл заново.')
        entry = documents[key]
        selected_options = options if options is not None else entry['options']
        candidate = Editor(entry['path'], selected_options)
        editor, document_id = candidate, key
        entry['options'] = candidate.table.options
        Editor.atomic_write(entry['path'].parent/'document.json', json.dumps(
            {'name': entry['path'].name, 'options': entry['options']}, ensure_ascii=False).encode('utf-8'))
        return current_view()

    if args.file:
        try:
            open_document(import_document(args.file.name, args.file.read_bytes()))
        except (OSError, ValueError) as error:
            parser.error(str(error))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, payload, content_type='application/json; charset=utf-8', filename=None, source_url=None):
            raw = (payload if isinstance(payload, bytes) else payload.encode('utf-8')
                   if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if source_url:
                self.send_header('Content-Location', quote(source_url, safe=":/?#[]@!$&'()*+,;=%"))
            if filename:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''"+quote(filename))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            address = urlsplit(self.path)
            authorized = parse_qs(address.query).get('token') == [token]
            if not authorized:
                self.respond(403, {'error': 'Нет доступа.'})
                return
            if address.path == '/':
                self.respond(200, html, 'text/html; charset=utf-8')
            elif address.path.startswith('/assets/'):
                name = address.path.removeprefix('/assets/')
                if name not in ('pdf.mjs', 'pdf.worker.mjs'):
                    self.respond(404, {'error': 'Файл не найден.'})
                    return
                self.respond(200, (folder/'assets'/name).read_bytes(), 'text/javascript; charset=utf-8')
            elif address.path == '/download':
                with editor_lock:
                    if editor is None or not editor.output_path.exists():
                        self.respond(404, {'error': 'Сначала сохраните изменения.'})
                    else:
                        self.respond(200, editor.output_path.read_bytes(), 'application/octet-stream', editor.output_path.name)
            else:
                self.respond(404, {'error': 'Страница не найдена.'})

        def do_POST(self):
            if self.headers.get('X-Editor-Token') != token:
                self.respond(403, {'error': 'Нет доступа.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 75_000_000:
                    raise ValueError('Некорректный размер запроса. Максимальный размер файла 50 МБ.')
                data = json.loads(self.rfile.read(length))
                if self.path in ('/api/source', '/api/browser-source'):
                    if self.path == '/api/browser-source':
                        target = validate_browser_url(data.get('url'))
                    else:
                        with editor_lock:
                            if editor is None:
                                raise ValueError('Сначала выберите таблицу.')
                            links = editor.view(data['index'])['links']
                            target = data.get('url', links[0] if links else None)
                            if target not in links and not preview.permits(target):
                                raise ValueError('В строке нет такой ссылки.')
                    if data.get('reload') is True:
                        fetch_source.cache_clear()
                        preview.resource.cache_clear()
                    result, mime, source_url = fetch_source(target)
                    if isinstance(result, dict):
                        result = preview.prepare(result)
                    self.respond(200, result, mime, source_url=source_url)
                    return
                with editor_lock:
                    self.editor_action(data)
            except Exception as error:
                # Return a useful error instead of dropping the connection on format errors.
                self.respond(400, {'error': str(error) or type(error).__name__})

        def editor_action(self, data):
            if self.path == '/api/row':
                result = current_view(data.get('index'))
            elif self.path == '/api/recent':
                result = {'recent': [{'id': key, 'name': value['path'].name}
                                     for key, value in documents.items()]}
            elif self.path == '/api/import':
                raw = base64.b64decode(data['content'], validate=True)
                if len(raw)>50_000_000:
                    raise ValueError('Максимальный размер файла 50 МБ.')
                key = import_document(data['name'], raw)
                result = open_document(key, data.get('options'))
            elif self.path == '/api/load':
                result = open_document(data['document_id'], data.get('options'))
            elif self.path == '/api/shutdown':
                self.respond(200, {'ok': True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            else:
                if editor is None:
                    raise ValueError('Сначала выберите таблицу.')
                if self.path == '/api/save':
                    result = editor.save(data)
                elif self.path == '/api/config':
                    result = editor.configure(data)
                elif self.path == '/api/skip':
                    result = editor.skip(data)
                elif self.path == '/api/cycle-end':
                    result = editor.end_cycle(data)
                elif self.path == '/api/layout':
                    result = editor.set_layout(data)
                else:
                    self.respond(404, {'error': 'Неизвестная команда.'})
                    return
                result['document_id'] = document_id
            self.respond(200, result)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    preview.parent_origin = f'http://127.0.0.1:{server.server_port}'
    address = f'http://127.0.0.1:{server.server_port}/?token={token}'
    print('TableLens:', address, flush=True)
    print('Для остановки нажмите «Закрыть приложение» или Ctrl+C.', flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        preview.close()


if __name__ == '__main__':
    main()
