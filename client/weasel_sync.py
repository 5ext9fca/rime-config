"""Run the installed Weasel /sync once and verify its native completion log."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

from dictionaries import checked, snapshots
from identity import installation_id
from sync import atomic_write


def idle_seconds():
    class LastInput(C.Structure):
        _fields_ = [('cbSize', W.UINT), ('dwTime', W.DWORD)]
    data = LastInput(C.sizeof(LastInput), 0)
    user = C.WinDLL('user32', use_last_error=True)
    user.GetLastInputInfo.argtypes, user.GetLastInputInfo.restype = [C.POINTER(LastInput)], W.BOOL
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetTickCount.restype = W.DWORD
    if not user.GetLastInputInfo(C.byref(data)):
        raise C.WinError(C.get_last_error())
    return ((kernel.GetTickCount() - data.dwTime) & 0xffffffff) / 1000


def registered_target():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Rime\Weasel') as key:
            value, kind = winreg.QueryValueEx(key, 'RimeUserDir')
            if kind == winreg.REG_SZ and value:
                return Path(os.path.abspath(value))
    except FileNotFoundError:
        pass
    return Path(os.environ['APPDATA']) / 'Rime'


def configured_sync_dir(target, dll):
    """Read YAML through librime without setup, deployment or identity writes."""
    lib = C.CDLL(str(dll))
    config = C.c_void_p()
    load = lib.RimeConfigLoadString
    load.argtypes, load.restype = [C.POINTER(C.c_void_p), C.c_char_p], C.c_int
    get = lib.RimeConfigGetCString
    get.argtypes, get.restype = [C.POINTER(C.c_void_p), C.c_char_p], C.c_char_p
    close = lib.RimeConfigClose
    close.argtypes, close.restype = [C.POINTER(C.c_void_p)], C.c_int
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


def deployer_busy():
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes, kernel.OpenMutexW.restype = [W.DWORD, W.BOOL, W.LPCWSTR], W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.OpenMutexW(0x100000, False, 'WeaselDeployerMutex')
    if handle:
        kernel.CloseHandle(handle)
        return True
    if C.get_last_error() != 2:
        raise C.WinError(C.get_last_error())
    return False


def ipc(command, session=0, body=''):
    advapi = C.WinDLL('advapi32', use_last_error=True)
    advapi.GetUserNameW.argtypes = [W.LPWSTR, C.POINTER(W.DWORD)]
    username, size = C.create_unicode_buffer(256), W.DWORD(256)
    if not advapi.GetUserNameW(username, C.byref(size)):
        raise C.WinError(C.get_last_error())
    kernel = C.WinDLL('kernel32', use_last_error=True)
    call = kernel.CallNamedPipeW
    call.argtypes = [W.LPCWSTR, C.c_void_p, W.DWORD, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), W.DWORD]
    call.restype = W.BOOL
    data = struct.pack('<III', 0x8000 + command, 0, session) + (body + '\0').encode('utf-16le') if body else struct.pack('<III', 0x8000 + command, 0, session)
    message = C.create_string_buffer(data)
    reply, count = C.create_string_buffer(65536), W.DWORD()
    if not call('\\\\.\\pipe\\' + username.value + '\\WeaselNamedPipe', message, len(data),
                reply, len(reply), C.byref(count), 3000) or count.value < 4:
        raise OSError('无法确认小狼毫原生 IPC 完成')
    return struct.unpack('<I', reply.raw[:4])[0]


def resume():
    """Recovery only, after our child exited and no deployer owns the mutex."""
    if deployer_busy():
        raise ValueError('其他原生部署正在运行，不抢占维护模式')
    ipc(10)


def probe():
    session = ipc(2, body='action=session\nsession.client_app=rime-config.exe\nsession.client_type=tsf\n.\n')
    if not session:
        raise ValueError('小狼毫未恢复，无法创建空输入会话')
    try:
        if ipc(1, session) != session:
            raise ValueError('小狼毫空会话校验失败')
    finally:
        ipc(3, session)


def verify_log(text, names):
    totals = re.findall(r'(\d+) tasks ran: (\d+) success, (\d+) failure', text)
    if not totals or tuple(map(int, totals[-1])) != (3, 3, 0):
        raise ValueError('未确认原生安装检查、配置备份和词典同步全部成功')
    processed = set(re.findall(r"synchronize user dict '([^']+)'", text))
    if processed != set(names):
        raise ValueError('原生日志处理的词典与预检查范围不同')
    if re.search(r'^E\d{4,8}\s', text, re.MULTILINE):
        raise ValueError('原生同步日志包含错误，停止上传')


def run(deployer, target, sync_dir, device, names, session):
    if os.name != 'nt':
        raise ValueError('--weasel-deployer 仅适用于 Windows 原生')
    deployer = checked(Path(os.path.abspath(deployer)))
    if deployer.name.casefold() != 'weaseldeployer.exe' or not deployer.is_file():
        raise ValueError('请指定已安装的 WeaselDeployer.exe')
    dll = checked(deployer.with_name('rime.dll'))
    if registered_target() != target or installation_id(target) != device:
        raise ValueError('原生 /sync 的注册目录或安装身份与项目目标不同')
    if configured_sync_dir(target, dll) != sync_dir:
        raise ValueError('原生 sync_dir 与项目交换目录不一致')
    if deployer_busy():
        raise ValueError('小狼毫正在部署或同步，稍后重试')
    # Native /sync backs up top-level YAML/TXT as well. Preserve old copies,
    # but never add these files to the personal configuration upload scope.
    own = checked(sync_dir / device, directory=True)
    if own.exists():
        for path in own.iterdir():
            if path.suffix in ('.yaml', '.txt'):
                atomic_write(session / 'native-before' / path.name, checked(path).read_bytes())
    log_dir = Path(os.environ['TEMP']) / 'rime.weasel'
    started = time.time()
    child = subprocess.Popen([str(deployer), '/sync'], creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if child.wait(timeout=180) != 0:
            raise ValueError('WeaselDeployer /sync 返回失败')
        logs = [p for p in log_dir.glob(f'*.INFO.*.{child.pid}.log') if p.stat().st_mtime >= started - 2]
        if len(logs) != 1:
            raise ValueError('未找到本次原生进程的唯一完成日志')
        text = logs[0].read_text(encoding='utf-8', errors='replace')
        verify_log(text, names)
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--probe'],
                       check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        exported = snapshots(sync_dir, [device], names)
        for name in names:
            path = sync_dir / device / (name + '.userdb.txt')
            if f'{device}/{name}.userdb.txt' not in exported or path.stat().st_mtime < started - 2:
                raise ValueError('未确认本次原生导出已更新全部快照')
        return {'status': 'success', 'names': sorted(names), 'pid': child.pid, 'log': str(logs[0]),
                'tasks_succeeded': 3, 'input_service_probe': 'passed'}
    except BaseException:
        if child.poll() is None:
            child.kill()
        child.wait()
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--resume'],
                           check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            print('原生同步失败，恢复请求未确认；保留快照和备份，下轮重试。', file=sys.stderr)
        raise


if __name__ == '__main__':
    if sys.argv[1:] == ['--resume']:
        resume()
    elif sys.argv[1:] == ['--probe']:
        probe()
    else:
        raise SystemExit('此模块由全量原生同步流程调用')
