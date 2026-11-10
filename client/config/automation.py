"""Local automatic maintenance settings, deliberately outside cloud content."""
import json
from pathlib import Path


def load(path):
    config=json.loads(Path(path).read_text())
    if not {'version','linux_theme','deployment','logs'} <= set(config) or set(config)-{'version','linux_theme','deployment','logs','backups'} or type(config['version']) is not int or config['version']!=1 or type(config['linux_theme']) is not bool:
        raise ValueError('Invalid automation configuration')
    from client.maintenance.backup_retention import DEFAULT
    config.setdefault('backups',dict(DEFAULT))
    backups=config['backups']
    if (not isinstance(backups,dict) or set(backups)!=set(DEFAULT) or type(backups['enabled']) is not bool
            or any(type(backups[k]) is not int or backups[k]<1 for k in ('retention_days','keep_minimum','interval_seconds'))):
        raise ValueError('Invalid backup retention policy')
    deploy=config['deployment'];logs=config['logs']
    if set(deploy)!={'enabled','idle_seconds','retry_seconds','commands'} or set(logs)!={'enabled','retention_days','max_file_bytes'}:
        raise ValueError('Invalid maintenance policy')
    if type(deploy['enabled']) is not bool or type(logs['enabled']) is not bool:raise ValueError('Invalid enabled flag')
    for key in ('idle_seconds','retry_seconds'):
        if type(deploy[key]) is not int or deploy[key]<0 or (key=='retry_seconds' and deploy[key]<1):raise ValueError('Invalid deployment interval')
    for key in ('retention_days','max_file_bytes'):
        if type(logs[key]) is not int or logs[key]<1:raise ValueError('Invalid log retention')
    if not isinstance(deploy['commands'],dict) or set(deploy['commands'])-{'windows','macos','linux'}:raise ValueError('Invalid deployment platforms')
    for argv in deploy['commands'].values():
        if not isinstance(argv,list) or not argv or not all(isinstance(a,str) and a for a in argv) or not Path(argv[0]).is_absolute():raise ValueError('Deployment command must be an absolute argv list')
    return config
