"""Serialize OpenSSL engine calls while allowing concurrent, nonblocking video/control IO."""
import select
import socket
import ssl
import threading
import time


class TLSChannel:
    is_tls=True
    def __init__(self,connection):
        self.connection=connection;self.timeout=connection.gettimeout()
        self.lock=threading.Lock();self.send_lock=threading.Lock();connection.setblocking(False)

    def _wait(self,reading,deadline):
        remaining=None if deadline is None else deadline-time.monotonic()
        if remaining is not None and remaining<=0:raise socket.timeout('TLS IO timeout')
        try:
            if self.fileno()<0:raise ConnectionError('TLS closed')
            readable,writable,_=select.select([self] if reading else [],[] if reading else [self],[],min(.1,remaining) if remaining is not None else .1)
        except ValueError as exc:raise ConnectionError('TLS closed') from exc
        if not readable and not writable and deadline is not None and time.monotonic()>=deadline:
            raise socket.timeout('TLS IO timeout')

    def recv(self,length):
        deadline=None if self.timeout is None else time.monotonic()+self.timeout
        while True:
            try:
                with self.lock:return self.connection.recv(length)
            except ssl.SSLWantReadError:self._wait(True,deadline)
            except ssl.SSLWantWriteError:self._wait(False,deadline)

    def sendall(self,data):
        deadline=None if self.timeout is None else time.monotonic()+self.timeout
        view=memoryview(data);offset=0
        with self.send_lock:
            while offset<len(view):
                try:
                    with self.lock:count=self.connection.send(view[offset:offset+16384])
                    if not count:raise ConnectionError('TLS closed')
                    offset+=count
                except ssl.SSLWantReadError:self._wait(True,deadline)
                except ssl.SSLWantWriteError:self._wait(False,deadline)

    def settimeout(self,value):self.timeout=value
    def setsockopt(self,*args):return self.connection.setsockopt(*args)
    def fileno(self):return self.connection.fileno()
    def pending(self):
        with self.lock:return self.connection.pending()
    def shutdown(self,how):
        with self.lock:return self.connection.shutdown(how)
    def close(self):
        with self.lock:self.connection.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
