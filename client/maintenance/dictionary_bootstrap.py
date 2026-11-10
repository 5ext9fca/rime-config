"""Build missing dictionaries through Rime, publish only to absent database paths."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from client.storage.snapshots import snapshots, checked
from client.core.dictionary_format import validate_snapshot, component
from client.storage.filesystem import atomic_write, is_link


def publish_new(source,destination):
    """Atomic no-replace rename. Never emulate with exists()+ordinary rename."""
    source=Path(source);destination=Path(destination)
    checked(source,directory=source.is_dir());checked(destination,directory=source.is_dir())
    if os.name=='nt':
        os.rename(source,destination)  # Windows rename fails if destination exists.
        return
    libc=C.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        fn=libc.renamex_np;fn.argtypes=[C.c_char_p,C.c_char_p,C.c_uint]
        fn.restype=C.c_int;result=fn(os.fsencode(source),os.fsencode(destination),4)  # RENAME_EXCL
    else:
        fn=libc.renameat2;fn.argtypes=[C.c_int,C.c_char_p,C.c_int,C.c_char_p,C.c_uint]
        fn.restype=C.c_int;result=fn(-100,os.fsencode(source),-100,os.fsencode(destination),1)
    if result:
        error=C.get_errno()
        raise OSError(error,os.strerror(error),str(destination))
    fd=os.open(destination.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def native_builder(platform,deployer=None):
    if platform=='windows':
        if not deployer:raise ValueError('初始化用户词典需要已安装的小狼毫部署器')
        library=checked(Path(deployer).with_name('rime.dll'))
        def build(stage,name):
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(library),str(stage),name],
                           check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return build
    if platform=='macos':
        from client.platforms.macos.squirrel_maintenance import frontend
        binary,_=frontend();manager=binary.with_name('rime_dict_manager')
    elif platform=='linux':
        located=shutil.which('rime_dict_manager')
        if not located:raise ValueError('首次导入需要安装 rime_dict_manager')
        manager=Path(located)
    else:raise ValueError('Unsupported native dictionary bootstrap platform')
    if not manager.is_file():raise ValueError('原生词典管理程序不存在')
    def build(stage,name):
        for path in sorted((stage/'inputs').glob('*/'+name+'.userdb.txt')):
            subprocess.run([str(manager),'--restore',str(path)],cwd=stage,check=True,timeout=120,
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        subprocess.run([str(manager),'--backup',name],cwd=stage,check=True,timeout=120,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    return build


def ensure(target,sync_dir,device,names,session,platform,deployer=None,builder=None):
    from client.maintenance.native_sync import database_names
    target=Path(target);sync_dir=Path(sync_dir);session=Path(session);component(device)
    current=database_names(target)
    devices=[p.name for p in checked(sync_dir,directory=True).iterdir() if p.is_dir()] if sync_dir.exists() else []
    incoming=snapshots(sync_dir,devices,names)
    missing=sorted({Path(key).name.removesuffix('.userdb.txt') for key in incoming}-current)
    if not missing:return []
    build=builder or native_builder(platform,deployer)
    record={'status':'running','names':missing,'published':[],'inputs':{k:hashlib.sha256(v).hexdigest() for k,v in incoming.items() if Path(k).name.removesuffix('.userdb.txt') in missing}}
    receipt=session/'bootstrap.json';atomic_write(receipt,json.dumps(record).encode())
    try:
        for name in missing:
            component(name)
            # Same filesystem is required for atomic publication. Rime never sees
            # these isolated DBs until the native worker has closed them.
            with tempfile.TemporaryDirectory(prefix='.rime-bootstrap-',dir=target) as folder:
                stage=Path(folder).resolve()
                atomic_write(stage/'installation.yaml',('installation_id: '+device+'\n').encode())
                atomic_write(stage/'.bootstrap-only',b'1')
                for key,data in incoming.items():
                    if Path(key).name==name+'.userdb.txt':atomic_write(stage/'inputs'/key,data)
                build(stage,name)
                exported=stage/'sync'/device/(name+'.userdb.txt')
                validate_snapshot(checked(exported).read_bytes(),device,name)
                candidates=[p for p in stage.iterdir() if p.name in (name+'.userdb',name+'.userdb.kct')]
                if len(candidates)!=1:raise ValueError('原生初始化没有产生唯一用户数据库')
                source=candidates[0]
                entries=[source]+list(source.rglob('*')) if source.is_dir() else [source]
                for path in entries:
                    if is_link(path) or not (path.is_file() or path.is_dir()):raise ValueError('原生初始化输出包含异常路径')
                    if os.name!='nt':path.chmod(0o600 if path.is_file() else 0o700)
                    if path.is_file():
                        with path.open('rb') as stream:os.fsync(stream.fileno())
                if os.name!='nt':
                    for directory in sorted((p for p in entries if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
                        descriptor=os.open(directory,os.O_RDONLY)
                        try:os.fsync(descriptor)
                        finally:os.close(descriptor)
                if name in database_names(target):raise FileExistsError('用户数据库已被其他进程创建')
                publish_new(source,target/source.name)
                record['published'].append(name)
                atomic_write(receipt,json.dumps(record).encode())
        record['status']='success';return record['published']
    except BaseException:
        record['status']='failed';raise
    finally:atomic_write(receipt,json.dumps(record).encode())


def worker(library,stage,name):
    """Windows levers API worker: only accepts our disposable staging folder."""
    from client.platforms.rime_api import function
    stage=Path(stage).resolve();component(name)
    if not stage.name.startswith('.rime-bootstrap-') or not (stage/'.bootstrap-only').is_file():
        raise ValueError('原生初始化仅允许隔离目录')
    class Traits(C.Structure):
        _fields_=[('data_size',C.c_int)]+[(n,C.c_char_p) for n in ('shared_data_dir','user_data_dir','distribution_name','distribution_code_name','distribution_version','app_name')]+[('modules',C.POINTER(C.c_char_p)),('min_log_level',C.c_int),('log_dir',C.c_char_p),('prebuilt_data_dir',C.c_char_p),('staging_dir',C.c_char_p)]
    class Module(C.Structure):
        _fields_=[('data_size',C.c_int),('name',C.c_char_p),('initialize',C.c_void_p),('finalize',C.c_void_p),('get_api',C.c_void_p)]
    names='custom_settings_init custom_settings_destroy load_settings save_settings customize_bool customize_int customize_double customize_string is_first_run settings_is_modified settings_get_config switcher_settings_init get_available_schema_list get_selected_schema_list schema_list_destroy get_schema_id get_schema_name get_schema_version get_schema_author get_schema_description get_schema_file_path select_schemas get_hotkeys set_hotkeys user_dict_iterator_init user_dict_iterator_destroy next_user_dict backup_user_dict restore_user_dict'.split()
    class Levers(C.Structure):_fields_=[('data_size',C.c_int)]+[(n,C.c_void_p) for n in names]
    lib=C.CDLL(str(library));traits=Traits();traits.data_size=C.sizeof(Traits)-4
    (stage/'shared').mkdir();(stage/'logs').mkdir()
    traits.shared_data_dir=str(stage/'shared').encode();traits.user_data_dir=str(stage).encode();traits.log_dir=str(stage/'logs').encode();traits.app_name=b'rime.bootstrap'
    function(lib,'RimeSetup',None,C.POINTER(Traits))(C.byref(traits));function(lib,'RimeDeployerInitialize',None,C.c_void_p)(None)
    try:
        if not function(lib,'RimeRunTask',C.c_int,C.c_char_p)(b'installation_update'):raise ValueError('隔离安装初始化失败')
        module=function(lib,'RimeFindModule',C.POINTER(Module),C.c_char_p)(b'levers')
        if not module or not module.contents.get_api:raise ValueError('缺少原生 levers 模块')
        api=C.CFUNCTYPE(C.POINTER(Levers))(module.contents.get_api)().contents
        if api.data_size+4<C.sizeof(Levers):raise ValueError('原生 levers API 版本不支持恢复')
        restore=C.CFUNCTYPE(C.c_int,C.c_char_p)(api.restore_user_dict);backup=C.CFUNCTYPE(C.c_int,C.c_char_p)(api.backup_user_dict)
        for path in sorted((stage/'inputs').glob('*/'+name+'.userdb.txt')):
            validate_snapshot(checked(path).read_bytes(),path.parent.name,name)
            if not restore(str(path).encode()):raise ValueError('原生首次合并失败')
        if not backup(name.encode()):raise ValueError('原生首次导出校验失败')
    finally:function(lib,'RimeFinalize',None)()


if __name__=='__main__':
    if len(sys.argv)!=5 or sys.argv[1]!='--worker':raise SystemExit('仅供内部隔离原生工作进程调用')
    worker(sys.argv[2],sys.argv[3],sys.argv[4])
