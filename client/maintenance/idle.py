"""Input activity observations, independent of cloud/configuration synchronization."""
from dataclasses import dataclass
import ctypes
import ctypes.wintypes
import os
import re
import subprocess
import time

@dataclass(frozen=True)
class Observation:
    state: str
    source: str
    observed_at: float
    reason: str = ''

    @property
    def permits_maintenance(self):return self.state=='idle'


class IdleProvider:
    def __init__(self,platform):
        self.platform=platform
        self.wayland=None

    def close(self):
        if self.wayland:self.wayland.close()
        self.wayland=None

    def observe(self,threshold):
        source=self.platform+'-input'
        try:
            if threshold==0:return Observation('idle','policy',time.monotonic(),'threshold-disabled')
            if self.platform=='linux':return self.linux(threshold)
            elapsed=windows_seconds() if self.platform=='windows' else macos_seconds()
            return Observation('idle' if elapsed>=threshold else 'active',source,time.monotonic())
        except (OSError,ValueError,subprocess.SubprocessError):
            return Observation('unknown',source,time.monotonic(),'unavailable')

    def linux(self,threshold):
        active=None
        if os.environ.get('WAYLAND_DISPLAY'):
            if self.wayland is None:
                from client.platforms.linux.wayland_idle import Provider
                self.wayland=Provider()
            active=self.wayland.input_idle(threshold)
            if active is True:return Observation('idle','wayland-input',time.monotonic())
        else:
            for path in ('/ScreenSaver','/org/freedesktop/ScreenSaver'):
                try:
                    text=dbus(path,'GetSessionIdleTime')
                    match=re.search(r'(\d+),',text)
                    if match:
                        active=int(match[1])>=threshold
                        if active:return Observation('idle','session-idle',time.monotonic())
                except (OSError,subprocess.SubprocessError):pass
        try:
            if dbus('/ScreenSaver','GetActive').strip()=='(true,)':
                return Observation('idle','session-lock',time.monotonic())
        except (OSError,subprocess.SubprocessError):pass
        return Observation('active' if active is False else 'unknown',
            'wayland-input' if os.environ.get('WAYLAND_DISPLAY') else 'session-idle',time.monotonic(),
            'threshold-not-reached' if active is False else 'unavailable')


def dbus(path,method):
    return subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.ScreenSaver',
        '--object-path',path,'--method','org.freedesktop.ScreenSaver.'+method],
        check=True,capture_output=True,text=True,timeout=5).stdout


def windows_seconds():
    W=ctypes.wintypes
    class LastInput(ctypes.Structure):
        _fields_=[('cbSize',W.UINT),('dwTime',W.DWORD)]
    data=LastInput(ctypes.sizeof(LastInput),0)
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetLastInputInfo.argtypes=[ctypes.POINTER(LastInput)];user.GetLastInputInfo.restype=W.BOOL
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetTickCount.restype=W.DWORD
    if not user.GetLastInputInfo(ctypes.byref(data)):raise ctypes.WinError(ctypes.get_last_error())
    return ((kernel.GetTickCount()-data.dwTime)&0xffffffff)/1000


def macos_seconds():
    api=ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    fn=api.CGEventSourceSecondsSinceLastEventType
    fn.argtypes=[ctypes.c_int,ctypes.c_uint32];fn.restype=ctypes.c_double
    return fn(1,0xffffffff)
