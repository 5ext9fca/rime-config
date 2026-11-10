bind = '0.0.0.0:8080'
workers = 1
threads = 4
timeout = 60
worker_tmp_dir = '/tmp'
accesslog = None
errorlog = '-'
umask = 0o077

# Application-owned daily logs; Docker only retains bounded bootstrap output.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client.maintenance.logs import DailyLog
stream = DailyLog(Path('/data/logs'), {'enabled': True, 'retention_days': 30, 'max_file_bytes': 10485760})
logconfig_dict = {
    'version': 1, 'disable_existing_loggers': False,
    'root': {'handlers': ['managed'], 'level': 'INFO'},
    'formatters': {'standard': {'format': '%(asctime)s %(levelname)s %(message)s'}},
    'handlers': {'managed': {'class': 'logging.StreamHandler', 'stream': stream, 'formatter': 'standard'}},
    'loggers': {'gunicorn.error': {'handlers': ['managed'], 'level': 'INFO', 'propagate': False},
                'gunicorn.access': {'handlers': [], 'level': 'WARNING', 'propagate': False}},
}
