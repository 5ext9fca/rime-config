import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import client.platforms.linux.wayland_idle as w
from client.maintenance.idle import IdleProvider
from client.maintenance import idle as idle_module


class Compositor:
    def __init__(self,path):
        self.listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.listener.bind(str(path));self.listener.listen();self.listener.settimeout(.2)
        self.stopped=False
        self.events=[];self.notifications=[];self.requests=[];self.conn=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def send(self,target,opcode,payload=b''):
        self.conn.sendall(w.words(target,((len(payload)+8)<<16)|opcode)+payload)

    def read(self,n):
        data=b''
        while len(data)<n:
            part=self.conn.recv(n-len(data))
            if not part:raise EOFError
            data+=part
        return data

    def run(self):
        try:
            while not self.stopped:
                try:
                    self.conn,_=self.listener.accept();break
                except socket.timeout:continue
            if self.conn is None:return
            while True:
                target,header=struct.unpack('=II',self.read(8))
                opcode=header&65535;data=self.read((header>>16)-8)
                if target==1 and opcode==1:
                    self.registry,=struct.unpack('=I',data)
                    for name,interface,version in [(10,'wl_seat',1),(11,'wl_seat',1),(20,'ext_idle_notifier_v1',2)]:
                        self.send(self.registry,0,w.words(name)+w.string(interface)+w.words(version))
                elif target==1 and opcode==0:
                    callback,=struct.unpack('=I',data)
                    events,self.events=self.events,[]
                    for obj,op,payload in events:self.send(obj,op,payload)
                    self.send(callback,0,w.words(0));self.send(1,1,w.words(callback))
                elif target==self.registry:
                    name,length=struct.unpack_from('=II',data)
                    if name==20:self.manager=struct.unpack_from('=I',data,len(data)-4)[0]
                elif target==self.manager:
                    self.requests.append((opcode,struct.unpack('=III',data)))
                    self.notifications.append(struct.unpack_from('=I',data)[0])
        except (OSError,EOFError):pass

    def close(self):
        self.stopped=True
        if self.conn:
            try:self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.conn.close()
        self.listener.close();self.thread.join(2)


@unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Requires Unix domain sockets')
class IdleTests(unittest.TestCase):
    def setUp(self):
        self.provider=w.Provider()
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'wayland-test'
        self.server=Compositor(self.path)
    def tearDown(self):
        self.provider.close()
        self.server.close();self.temp.cleanup()

    def test_wire_all_seats_resume_and_barrier_reuse(self):
        monitor=w.Monitor(self.path,30)
        try:
            self.assertFalse(monitor.idle())
            self.assertEqual([r[0] for r in self.server.requests],[2,2])
            self.assertTrue(all(r[1][1]==30000 for r in self.server.requests))
            a,b=self.server.notifications
            self.server.events=[(a,0,b'')];self.assertFalse(monitor.idle())
            self.server.events=[(b,0,b'')];self.assertTrue(monitor.idle())
            self.server.events=[(a,1,b'')];self.assertFalse(monitor.idle())
            for _ in range(100):monitor.idle()
            self.assertLess(monitor.next_id,15)
            self.server.events=[(monitor.registry,1,w.words(10))]
            with self.assertRaises(ConnectionError):monitor.idle()
        finally:monitor.close()

    def test_disconnect_discards_idle_state(self):
        with patch.dict(os.environ,{'WAYLAND_DISPLAY':str(self.path)}):
            self.assertFalse(self.provider.input_idle(30))
            self.server.events=[(n,0,b'') for n in self.server.notifications]
            self.assertTrue(self.provider.input_idle(30))
            self.server.close()
            self.assertIsNone(self.provider.input_idle(30));self.assertIsNone(self.provider.monitor)

    def test_changed_session_or_threshold_reinitializes(self):
        with patch.dict(os.environ,{'WAYLAND_DISPLAY':str(self.path)}),patch.object(w,'Monitor') as factory:
            factory.return_value.idle.return_value=False
            self.assertFalse(self.provider.input_idle(30));self.assertFalse(self.provider.input_idle(30))
            self.assertEqual(factory.call_count,1)
            self.provider.input_idle(60);self.assertEqual(factory.call_count,2)
            with patch.dict(os.environ,{'WAYLAND_DISPLAY':''}):self.assertIsNone(self.provider.input_idle(60))
            self.assertIsNone(self.provider.monitor)

    def test_maintenance_rechecks_after_preparation(self):
        import client.platforms.linux.fcitx_maintenance as f
        from types import SimpleNamespace
        target=Path.home()/'.local/share/fcitx5/rime'
        call=Mock();prepare=Mock();idle=Mock(side_effect=[True,False])
        with patch.dict(os.environ,{'XDG_DATA_HOME':str(Path.home()/'.local/share')}),patch.object(f.subprocess,'run',side_effect=[SimpleNamespace(stdout='(uint32 123,)'),SimpleNamespace(stdout='-- cursor: test')]):
            result=f._run(target,30,Path(self.temp.name),'sync',call,idle,prepare)
        self.assertEqual(result['status'],'deferred')
        prepare.assert_called_once()
        self.assertFalse(any(args[0]=='SetConfig' for args,kwargs in call.call_args_list))

    def test_wayland_fallback_only_queries_lock(self):
        with patch.dict(os.environ,{'WAYLAND_DISPLAY':'wayland-0'}),patch.object(w.Provider,'input_idle',return_value=None),patch.object(idle_module.subprocess,'run',return_value=Mock(stdout='(true,)')) as run:
            self.assertTrue(IdleProvider('linux').observe(30).permits_maintenance)
            self.assertEqual(run.call_count,1)
            self.assertIn('org.freedesktop.ScreenSaver.GetActive',run.call_args.args[0])

if __name__=='__main__':unittest.main()
