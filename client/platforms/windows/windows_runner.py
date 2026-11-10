"""pythonw entry point: keep the client in the task process and capture its logs."""
import os
from pathlib import Path
import runpy
import sys
import traceback
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))


def main():
    from client.storage.config_paths import safe_path
    log = Path(os.environ['LOCALAPPDATA']) / 'rime-config/logs/service.log'
    safe_path(log.parent, log.name)
    log.parent.mkdir(parents=True, exist_ok=True)
    # Retain one previous log on process startup; never discard logs on uninstall.
    if log.exists() and log.stat().st_size > 10 * 1024 * 1024:
        safe_path(log.parent, 'service.log.1')
        os.replace(log, log.with_name('service.log.1'))
    with log.open('a', encoding='utf-8', buffering=1) as stream:
        sys.stdout = sys.stderr = stream
        try:
            sys.argv = sys.argv[1:]
            runpy.run_path(sys.argv[0], run_name='__main__')
        except SystemExit:
            raise
        except BaseException:
            traceback.print_exc()
            raise SystemExit(1)


if __name__ == '__main__':
    main()
