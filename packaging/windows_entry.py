"""Windowless Windows entry point; diagnostics live beside persistent user data."""
import ctypes
from pathlib import Path
import sys
import traceback

import editor


def launch():
    log_path = editor.default_storage_dir().parent / 'TableLens.log'
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8', buffering=1) as log:
            stdout, stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = log
            try:
                editor.main()
            except Exception:
                traceback.print_exc()
                raise
            finally:
                sys.stdout, sys.stderr = stdout, stderr
    except Exception as error:
        message = (f'Не удалось запустить TableLens: {error}\n\nЖурнал: {log_path}'
                   if editor.system_language() == 'ru' else
                   f'TableLens could not start: {error}\n\nLog: {log_path}')
        ctypes.windll.user32.MessageBoxW(None, message, 'TableLens', 0x10)
        raise SystemExit(1)


if __name__ == '__main__':
    launch()
