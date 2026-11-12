"""Apply authoritative Fcitx preferences through its live configuration API."""
import copy
import json
from pathlib import Path
import time
from client.storage.filesystem import atomic_write
from client.storage.config_paths import safe_path
from client.storage.file_lock import lock_exclusive

BUNDLE='fcitx5/input.json'


def desired(config,global_config,rime_config):
    if set(config)!={'version','remove_trigger_keys','add_trigger_keys','remove_alt_trigger_keys','behavior','rime'} or config['version']!=1:
        raise ValueError('Invalid frontend preference bundle')
    if set(config['behavior'])!={'ActiveByDefault','ShareInputState','DefaultPageSize'} or set(config['rime'])!={'InputState','SwitchInputMethodBehavior'}:
        raise ValueError('Invalid frontend preference scope')
    for field in ('remove_trigger_keys','add_trigger_keys','remove_alt_trigger_keys'):
        if not isinstance(config[field],list) or not all(isinstance(k,str) and k for k in config[field]):raise ValueError('Invalid shortcut list')
    if config['behavior']['ActiveByDefault'] not in ('True','False') or config['behavior']['ShareInputState'] not in ('No','Program','All') or config['behavior']['DefaultPageSize'] not in map(str,range(1,11)):
        raise ValueError('Invalid frontend behavior')
    if config['rime']['InputState'] not in ('No','Program','All','Follow Global Configuration') or config['rime']['SwitchInputMethodBehavior'] not in ('Clear','Commit raw input','Commit composing text','Commit commit preview'):
        raise ValueError('Invalid Rime frontend behavior')
    result=copy.deepcopy(global_config);rime=copy.deepcopy(rime_config)
    hotkey=result.setdefault('Hotkey',{})
    for key,remove,add in [('TriggerKeys',config['remove_trigger_keys'],config['add_trigger_keys']),('AltTriggerKeys',config['remove_alt_trigger_keys'],[])]:
        original=hotkey.get(key,{})
        keys=list(original.values()) if isinstance(original,dict) else []
        keys=[k for k in keys if k not in remove]
        keys.extend(k for k in add if k not in keys)
        hotkey[key]={str(i):key for i,key in enumerate(keys)} if keys else ''
    result.setdefault('Behavior',{}).update(config['behavior'])
    rime.update(config['rime'])
    return result,rime


class FcitxConfig:
    def __init__(self):
        from gi.repository import Gio,GLib
        self.GLib=GLib
        self.proxy=Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION,Gio.DBusProxyFlags.DO_NOT_AUTO_START,None,
            'org.fcitx.Fcitx5','/controller','org.fcitx.Fcitx.Controller1',None)
    def get(self,uri):
        return self.proxy.call_sync('GetConfig',self.GLib.Variant('(s)',(uri,)),0,10000,None).unpack()[0]
    def set(self,uri,value):
        def variant(obj):
            if isinstance(obj,dict):return self.GLib.Variant('a{sv}',{k:variant(v) for k,v in obj.items()})
            return self.GLib.Variant('s',obj)
        self.proxy.call_sync('SetConfig',self.GLib.Variant('(sv)',(uri,variant(value))),0,10000,None)


def apply(source,state,dry_run=False,client=None):
    path=safe_path(Path(source),BUNDLE)
    if not path.exists():return 'absent'
    config=json.loads(path.read_bytes())
    if dry_run:
        desired(config,{},{});return 'planned'
    state=Path(state);safe_path(state);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with safe_path(state,'lock').open('a') as lock:
        lock_exclusive(lock)
        client=client or FcitxConfig()
        uris=('fcitx://config/global','fcitx://config/addon/rime')
        before=[client.get(uri) for uri in uris]
        after=desired(config,*before)
        if list(after)==before:return 'unchanged'
        backup=state/'backups'/str(time.time_ns())
        atomic_write(backup/'before.json',json.dumps(dict(zip(uris,before))).encode())
        changed=[]
        try:
            for uri,old,new in zip(uris,before,after):
                if old==new:continue
                if client.get(uri)!=old:raise ValueError('Concurrent frontend configuration edit')
                changed.append((uri,old))
                client.set(uri,new)
                if client.get(uri)!=new:raise ValueError('Frontend preferences not acknowledged')
        except BaseException:
            for uri,old in reversed(changed):client.set(uri,old)
            raise
        from client.maintenance.backup_retention import completed
        completed(backup)
        return 'applied'
