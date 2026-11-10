"""Version-checked stable librime C API prefix (rime_api.h, v1+)."""
import ctypes as C
import re

NAMES = 'setup set_notification_handler initialize finalize start_maintenance is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy deploy_schema deploy_config_file sync_user_data create_session find_session destroy_session cleanup_stale_sessions cleanup_all_sessions process_key commit_composition clear_composition get_commit free_commit get_context free_context get_status free_status set_option get_option set_property get_property get_schema_list free_schema_list get_current_schema select_schema schema_open config_open config_close config_get_bool config_get_int config_get_double config_get_string config_get_cstring config_update_signature config_begin_map config_next config_end simulate_key_sequence register_module find_module run_task get_shared_data_dir get_user_data_dir get_sync_dir get_user_id get_user_data_sync_dir config_init config_load_string'.split()
class API(C.Structure):
    _fields_=[('data_size',C.c_int)]+[(name,C.c_void_p) for name in NAMES]

def function(lib,name,result,*arguments):
    try:
        fn=getattr(lib,name)
        fn.restype=result;fn.argtypes=list(arguments)
        return fn
    except AttributeError:
        key=re.sub(r'(?<!^)(?=[A-Z])','_',name.removeprefix('Rime')).lower().replace('c_string','cstring')
        if key not in NAMES:raise ValueError('Unsupported librime API: '+key)
        get=lib.rime_get_api;get.restype=C.POINTER(API);get.argtypes=[]
        pointer=get()
        offset=getattr(API,key).offset
        if not pointer or pointer.contents.data_size+C.sizeof(C.c_int)<offset+C.sizeof(C.c_void_p):
            raise ValueError('Installed librime API is too old')
        address=getattr(pointer.contents,key)
        if not address:raise ValueError('Installed librime API is unavailable')
        return C.CFUNCTYPE(result,*arguments)(address)


from pathlib import Path

def configured_sync_dir(target, dll):
    """Read YAML through librime without setup, deployment or identity writes."""
    lib = C.CDLL(str(dll))
    config = C.c_void_p()
    load = function(lib,'RimeConfigLoadString',C.c_int,C.POINTER(C.c_void_p),C.c_char_p)
    get = function(lib,'RimeConfigGetCString',C.c_char_p,C.POINTER(C.c_void_p),C.c_char_p)
    close = function(lib,'RimeConfigClose',C.c_int,C.POINTER(C.c_void_p))
    try:
        if not load(C.byref(config), (target / 'installation.yaml').read_bytes()):
            raise ValueError('无法读取原生 installation.yaml')
        value = get(C.byref(config), b'sync_dir')
        path = Path(value.decode('utf-8')) if value else target / 'sync'
        if not path.is_absolute():
            raise ValueError('原生 sync_dir 必须使用绝对路径')
        return path
    finally:
        close(C.byref(config))

