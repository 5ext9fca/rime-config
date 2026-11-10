"""Minimal event-only Wayland idle client; no input contents or disk state.

Wire interfaces: wl_display/registry/callback, wl_seat v1 and
ext_idle_notifier_v1 v2. Keep the connection across maintenance polls; a sync
barrier drains queued resumed events before reporting idle. Failure is unknown.
"""
import os
from pathlib import Path
import socket
import struct
import threading
import time


def words(*values):
    return struct.pack('=' + 'I' * len(values), *values)


def string(value):
    data=value.encode()+b'\0'
    return words(len(data))+data+b'\0'*((-len(data))%4)


class Monitor:
    def __init__(self, path, threshold):
        self.sock=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.next_id=2
        self.free=[]
        self.registry=None
        self.globals={}
        self.notifications={}
        self.seat_globals=set()
        self.manager_global=None
        self.barrier=None
        self.done=False
        try:
            self.sock.settimeout(1)
            self.sock.connect(str(path))
            self.registry=self.allocate()
            self.send(1, 1, words(self.registry))
            self.roundtrip()
            managers=[(name, version) for name,(interface,version) in self.globals.items()
                      if interface=='ext_idle_notifier_v1' and version>=2]
            seats=[name for name,(interface,_) in self.globals.items() if interface=='wl_seat']
            if not managers or not seats:raise ValueError('Input idle notifier v2 or seat unavailable')
            self.manager_global=managers[0][0]
            manager=self.bind(self.manager_global, 'ext_idle_notifier_v1', 2)
            for name in seats:
                self.seat_globals.add(name)
                seat=self.bind(name, 'wl_seat', 1)
                notification=self.allocate()
                self.notifications[notification]=False
                self.send(manager, 2, words(notification, threshold*1000, seat))
            self.roundtrip()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.sock.close()

    def allocate(self):
        if self.free:return self.free.pop()
        value=self.next_id
        self.next_id+=1
        return value

    def send(self, target, opcode, payload=b''):
        self.sock.sendall(words(target, ((len(payload)+8)<<16)|opcode)+payload)

    def bind(self, name, interface, version):
        ident=self.allocate()
        self.send(self.registry, 0, words(name)+string(interface)+words(version,ident))
        return ident

    def receive(self, size, deadline):
        data=b''
        while len(data)<size:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Wayland roundtrip timed out')
            self.sock.settimeout(remaining)
            chunk=self.sock.recv(size-len(data))
            if not chunk:raise ConnectionError('Wayland disconnected')
            data+=chunk
        return data

    def event(self, target, opcode, data):
        if target==1:
            if opcode==0:raise ConnectionError('Wayland protocol error')
            if opcode==1:
                ident,=struct.unpack('=I',data)
                self.free.append(ident)
        elif target==self.registry:
            if opcode==0:
                name,length=struct.unpack_from('=II',data)
                interface=data[8:8+length-1].decode()
                version,=struct.unpack_from('=I',data,8+((length+3)//4)*4)
                # New seats require a fresh observation of every input seat.
                if self.notifications and interface=='wl_seat':raise ConnectionError('Wayland seats changed')
                self.globals[name]=(interface,version)
            elif opcode==1:
                name,=struct.unpack('=I',data)
                if name in self.seat_globals or name==self.manager_global:
                    raise ConnectionError('Wayland idle globals removed')
                self.globals.pop(name,None)
        elif target in self.notifications:
            if opcode not in (0,1):raise ValueError('Unknown idle event')
            self.notifications[target]=opcode==0
        elif target==self.barrier and opcode==0:
            self.done=True

    def roundtrip(self):
        self.sock.settimeout(1)
        self.barrier=self.allocate()
        self.done=False
        self.send(1,0,words(self.barrier))
        deadline=time.monotonic()+1
        while not self.done:
            target,header=struct.unpack('=II',self.receive(8,deadline))
            size=header>>16
            if size<8 or size%4:raise ValueError('Invalid Wayland frame')
            self.event(target,header&0xffff,self.receive(size-8,deadline))
        self.barrier=None

    def idle(self):
        self.roundtrip()
        return bool(self.notifications) and all(self.notifications.values())


class Provider:
    def __init__(self):
        self.lock=threading.Lock()
        self.monitor=None
        self.key=None

    def close(self):
        if self.monitor:self.monitor.close()
        self.monitor=None
        self.key=None

    def input_idle(self,threshold):
        """Return True/False when observed, None when unavailable."""
        with self.lock:
            try:
                display=os.environ.get('WAYLAND_DISPLAY')
                if not display:raise ValueError('No Wayland session')
                path=Path(display)
                if not path.is_absolute():
                    runtime=os.environ.get('XDG_RUNTIME_DIR')
                    if not runtime:raise ValueError('No runtime directory')
                    path=Path(runtime)/path
                stat=path.stat()
                key=(os.getpid(),str(path),stat.st_dev,stat.st_ino,threshold)
                if key!=self.key:
                    self.close()
                    if not 0<threshold<=4294967:raise ValueError('Invalid idle threshold')
                    self.monitor=Monitor(path,threshold)
                    self.key=key
                return self.monitor.idle()
            except (OSError,ValueError,struct.error,UnicodeError):
                self.close()
                return None
