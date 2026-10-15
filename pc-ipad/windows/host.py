"""Windows 11 host. No Android/ADB dependency; never installs drivers silently."""
import argparse
import collections
import json
import logging
import os
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from protocol import (MAGIC, VIDEO, AUDIO, INFO, ERROR, ACK, PAD, BYE, HEARTBEAT, TOUCH, CLIENT_INFO, NOTICE,
                      LatestFrame, fit_size, packet, proof, read_exact, read_packet, validate_pad, validate_display, display_id, display_orientation)

VERSION = "0.4.3"
DRIVER_URL = "https://github.com/ViGEm/ViGEmBus/releases/tag/v1.22.0"


class XboxPad:
    def __init__(self):
        try:
            import vgamepad as vg
            self.vg = vg
            self.device = vg.VX360Gamepad()
        except Exception as exc:
            raise RuntimeError("Instale o ViGEmBus e reinicie o programa para criar o gamepad Xbox.") from exc
        self.lock = threading.Lock()
        self.last = time.monotonic()

    def apply(self, state):
        state = validate_pad(state)
        with self.lock:
            self.device.reset()
            for name in self.vg.XUSB_BUTTON:
                if int(name) & state["buttons"]:
                    self.device.press_button(button=name)
            self.device.left_joystick_float(x_value_float=state["lx"], y_value_float=state["ly"])
            self.device.right_joystick_float(x_value_float=state["rx"], y_value_float=state["ry"])
            self.device.left_trigger_float(value_float=state["lt"])
            self.device.right_trigger_float(value_float=state["rt"])
            self.device.update()
            self.last = time.monotonic()

    def neutral(self):
        with self.lock:
            self.device.reset()
            self.device.update()
            self.last = time.monotonic()

    def expire(self):
        if time.monotonic() - self.last > 0.8:
            self.neutral()


def make_encoder(width, height, fps, quality='balanced'):
    import av
    from fractions import Fraction
    codec = av.CodecContext.create("libx264", "w")
    codec.width, codec.height = width, height
    codec.pix_fmt = "yuv420p"
    codec.time_base = Fraction(1, fps)
    codec.framerate = Fraction(fps, 1)
    from video_options import bitrate
    codec.bit_rate = bitrate(quality)
    codec.options = {"preset": "ultrafast", "tune": "zerolatency", "profile": "baseline",
                     "x264-params": "repeat-headers=1:annexb=1:bframes=0:keyint=30:scenecut=0"}
    codec.open()
    return codec


class Session:
    def __init__(self, connection, gamepad, fps, size, audio, report, mode="gamepad", monitor=None,
                 host_id='', client_size=(1024, 768), client_display_id=None, wake_key=None, client_orientation=None,
                 show_cursor=True, quality='balanced', metrics=None):
        self.sock = connection
        self.gamepad = gamepad
        self.fps, self.size, self.audio = fps, size, audio
        self.report = report
        self.mode,self.monitor=mode,monitor
        self.show_cursor=show_cursor;self.quality=quality;self.metrics=metrics
        self.stop = threading.Event()
        self.ack = threading.Event()
        self.latest = LatestFrame()
        self.audio_frames = collections.deque(maxlen=2)
        self.audio_lock = threading.Lock()
        self.capture_error = None
        self.threads = []
        self.width = self.height = 0
        self.host_id = host_id
        self.wake_key = wake_key
        self.notices = collections.deque(maxlen=1)
        self.last_input_error = None
        self.display_lock = threading.Lock()
        self.client_size = client_size
        self.client_orientation = client_orientation
        self.display_generation = 0
        self.client_display_id = client_display_id
        self.geometry_ready = threading.Event()
        self.geometry_ready.set()
        self.input_ready=threading.Event();self.input_ready.set()

    def change_monitor(self,monitor):
        with self.display_lock:
            self.geometry_ready.clear();self.input_ready.clear();self.gamepad.neutral()
            self.monitor=dict(monitor);self.display_generation+=1

    def configure_video(self,fps,size,quality):
        from video_options import bitrate
        bitrate(quality)
        if fps not in (15,20,30) or size not in (640,800,1024):raise ValueError('Configuração de vídeo inválida')
        with self.display_lock:
            if (fps,size,quality)==(self.fps,self.size,self.quality):return
            self.geometry_ready.clear()
            if size!=self.size:self.input_ready.clear();self.gamepad.neutral()
            self.fps,self.size,self.quality=fps,size,quality;self.display_generation+=1

    def display_preferences(self, body):
        value = json.loads(body)
        size = validate_display(value)
        identity = display_id(value)
        orientation = display_orientation(value)
        with self.display_lock:
            self.geometry_ready.clear()
            self.input_ready.clear()
            self.gamepad.neutral()
            self.client_size = size
            self.client_orientation = orientation
            self.display_generation += 1
            self.client_display_id = identity

    def info(self):
        return {"version": 1, "appVersion": VERSION, "hostId": self.host_id, "name": socket.gethostname(),
                "width": self.width, "height": self.height, "fps": self.fps, "audio": self.audio,
                "displayId": self.client_display_id, "orientation": self.client_orientation, "wakeKey": self.wake_key,
                "sampleRate": 44100, "channels": 2, "mode": self.mode,
                "gamepad": "Xbox 360" if self.mode == 'gamepad' else None}

    def close(self):
        self.stop.set()
        self.ack.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.gamepad.neutral()

    def capture(self):
        cursor=None
        try:
            import mss
            import numpy as np
            from contextlib import ExitStack
            from desktop import fit_target, set_ipad_resolution, monitors
            with ExitStack() as capture_stack:
                capture=capture_stack.enter_context(mss.mss())
                monitor = self.monitor or capture.monitors[1];requested=self.monitor
                previous = None
                next_geometry_check = 0
                cursor_retry_at=0;transient_since=None
                while not self.stop.is_set():
                    started = time.monotonic()
                    with self.display_lock:
                        source=self.monitor;target=self.client_size;generation=self.display_generation
                        period=1/self.fps;size=self.size
                    if source is not requested:
                        monitor=dict(source);requested=source;previous=None;next_geometry_check=0
                    if monitor.get('device') and started >= next_geometry_check:
                        next_geometry_check = started + 1
                        available=monitors()
                        current = next((m for m in available if m['device']==monitor['device']),None)
                        if current is None:
                            if not available:
                                if transient_since is None:
                                    transient_since=started
                                    with self.display_lock:
                                        self.geometry_ready.clear();self.input_ready.clear();self.gamepad.neutral();self.display_generation+=1
                                if started-transient_since>3:raise RuntimeError('Nenhuma tela disponível no Windows')
                                next_geometry_check=0;self.stop.wait(.1);continue
                            current=next((m for m in available if m['left']==0 and m['top']==0),available[0])
                            self.change_monitor(current);self.report('Tela removida; continuando no monitor principal.');continue
                        if any(current[k]!=monitor[k] for k in ('left','top','width','height')):
                            with self.display_lock:
                                self.geometry_ready.clear()
                                self.input_ready.clear()
                                self.gamepad.neutral()
                                self.display_generation += 1
                            monitor = current
                            previous = None
                            generation=self.display_generation
                    if target != previous:
                        if monitor.get('virtual'):
                            try:
                                monitor = set_ipad_resolution(monitor, *target)
                            except RuntimeError as exc:
                                self.report('Resolução do monitor virtual: ' + str(exc))
                        if self.mode == 'touch':
                            self.gamepad.neutral()
                            self.gamepad.set_monitor(monitor)
                        previous = target
                    width, height = fit_target(monitor['width'], monitor['height'], *target, size)
                    rect = {key: monitor[key] for key in ('left', 'top', 'width', 'height')}
                    try:image = capture.grab(rect)
                    except (mss.exception.ScreenShotError,OSError):
                        if transient_since is None:
                            transient_since=started
                            with self.display_lock:
                                self.geometry_ready.clear();self.input_ready.clear();self.gamepad.neutral();self.display_generation+=1
                        if started-transient_since>3:raise
                        if self.stop.is_set():break
                        capture.close()
                        while not self.stop.is_set():
                            try:
                                capture=capture_stack.enter_context(mss.mss());break
                            except (mss.exception.ScreenShotError,OSError):
                                if time.monotonic()-transient_since>3:raise
                                self.stop.wait(.1)
                        next_geometry_check=0;self.stop.wait(.1);continue
                    transient_since=None
                    image=np.array(image,dtype=np.uint8,copy=True)
                    if self.show_cursor and started>=cursor_retry_at:
                        try:
                            if cursor is None:
                                from cursor_capture import CursorRenderer
                                cursor=CursorRenderer()
                            cursor.apply(image,rect)
                        except (OSError,ValueError):
                            cursor_retry_at=started+2;logging.exception('Cursor overlay unavailable')
                            if cursor:cursor.close();cursor=None
                            self.report('Vídeo continua; não foi possível desenhar o ponteiro nesta sessão.')
                    # Copy so the single latest frame owns its backing memory.
                    with self.display_lock:
                        if source is self.monitor and generation==self.display_generation:
                            self.latest.put((image, width, height, target, generation))
                    self.stop.wait(max(0, period - (time.monotonic() - started)))
        except Exception as exc:
            self.capture_error = exc
            self.stop.set()
        finally:
            if cursor:cursor.close()

    def capture_audio(self):
        try:
            import soundcard as sc
            import numpy as np
            speaker = sc.default_speaker()
            microphone = sc.get_microphone(id=speaker.id, include_loopback=True)
            with microphone.recorder(samplerate=44100, channels=2, blocksize=512) as recorder:
                while not self.stop.is_set():
                    samples = recorder.record(numframes=512)
                    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                    with self.audio_lock:
                        self.audio_frames.append(pcm)
        except Exception as exc:
            logging.exception("Audio capture unavailable")
            self.report("Vídeo conectado; áudio indisponível: " + str(exc))

    def receive(self):
        try:
            while not self.stop.is_set():
                kind, body = read_packet(self.sock)
                if kind == ACK and not body:
                    self.ack.set()
                elif kind == PAD and self.mode=="gamepad" and len(body) <= 2048:
                    self.gamepad.apply(json.loads(body))
                elif kind == TOUCH and self.mode=="touch" and len(body)<=8192:
                    with self.display_lock:
                        if self.input_ready.is_set():
                            from touchscreen import TouchInjectionError
                            try:
                                self.gamepad.events(json.loads(body))
                                self.last_input_error = None
                            except TouchInjectionError as exc:
                                self.gamepad.neutral()
                                if self.last_input_error != exc.code:
                                    self.report(str(exc))
                                    logging.warning('Touch injection refused: code %s',exc.code)
                                    self.notices.append({'scope':'input','recoverable':True,'message':str(exc),'code':exc.code})
                                self.last_input_error = exc.code
                elif kind == CLIENT_INFO and len(body) <= 512:
                    self.display_preferences(body)
                elif kind == HEARTBEAT and not body:
                    pass  # Liveness does not extend a held gamepad state.
                elif kind == BYE:
                    break
                else:
                    raise ValueError("Comando desconhecido")
        except Exception:
            logging.exception("Connection ended")
        finally:
            self.stop.set()
            self.ack.set()
            self.gamepad.neutral()

    def send_audio(self):
        if self.notices:
            self.sock.sendall(packet(NOTICE,json.dumps(self.notices.popleft()).encode()))
        with self.audio_lock:
            audio = self.audio_frames.popleft() if self.audio_frames else None
        if audio:
            self.sock.sendall(packet(AUDIO, audio))

    def watchdog(self):
        while not self.stop.wait(0.1):
            self.gamepad.expire()

    def run(self):
        import av
        from video_options import StreamStats
        stats=StreamStats(time.monotonic())
        try:
            capture_thread = threading.Thread(target=self.capture, daemon=True)
            capture_thread.start()
            self.threads.append(capture_thread)
            sequence, raw = self.latest.take_after(0, 3)
            if raw is None:
                raise RuntimeError("Não foi possível capturar o monitor: " + str(self.capture_error))
            encoder = None
            for target in ([self.receive, self.watchdog, self.capture_audio] if self.audio else [self.receive, self.watchdog]):
                worker = threading.Thread(target=target, daemon=True)
                self.threads.append(worker)
                worker.start()
            pts = 0
            while not self.stop.is_set():
                if isinstance(raw, tuple):
                    image, width, height, target = raw[:4]
                    with self.display_lock:
                        current_target = self.client_size
                        generation = self.display_generation
                    frame_generation = raw[4] if len(raw)>4 else generation
                    if target != current_target or frame_generation != generation:
                        sequence, next_frame = self.latest.take_after(sequence)
                        if next_frame is not None:
                            raw = next_frame
                        continue
                else:
                    image, width, height = raw, self.width, self.height
                    frame_generation = self.display_generation
                if encoder is None or (width, height) != (self.width, self.height) or not self.geometry_ready.is_set():
                    with self.display_lock:quality=self.quality;fps=self.fps
                    candidate = make_encoder(width, height, fps) if quality=='balanced' else make_encoder(width,height,fps,quality)
                    with self.display_lock:
                        if frame_generation != self.display_generation:
                            continue
                        self.width, self.height = width, height
                        encoder = candidate
                        pts = 0
                        self.sock.sendall(packet(INFO, json.dumps(self.info()).encode()))
                    self.report(f"iPad conectado · {width} × {height} · {self.fps} FPS alvo · {self.mode}")
                encode_started=time.monotonic()
                frame = av.VideoFrame.from_ndarray(image, format="bgra").reformat(self.width, self.height, format="yuv420p")
                frame.pts = pts
                pts += 1
                encoded = b"".join(bytes(p) for p in encoder.encode(frame))
                encode_time=time.monotonic()-encode_started
                if not encoded:
                    raise RuntimeError("O encoder H.264 não produziu um frame imediato")
                with self.display_lock:
                    if frame_generation!=self.display_generation:continue
                # Drop raw captures BEFORE encoding; never drop dependent H.264 packets.
                self.ack.clear()
                sent_at=time.monotonic()
                self.sock.sendall(packet(VIDEO, encoded))
                deadline = time.monotonic() + 3
                while not self.stop.is_set() and not self.ack.is_set():
                    self.gamepad.expire()
                    self.send_audio()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("O iPad não confirmou a decodificação do vídeo")
                    # Event.wait wakes immediately on ACK; the timeout only services audio.
                    self.ack.wait(min(0.005, remaining))
                if not self.stop.is_set():
                    with self.display_lock:
                        if frame_generation==self.display_generation:
                            self.geometry_ready.set();self.input_ready.set()
                    sample=stats.record(time.monotonic(),len(encoded),time.monotonic()-sent_at,encode_time)
                    if sample and self.metrics:self.metrics(sample)
                self.send_audio()
                sequence, next_frame = self.latest.take_after(sequence)
                if next_frame is not None:
                    raw = next_frame
            if self.capture_error:
                raise RuntimeError('Captura interrompida: '+str(self.capture_error))
        finally:
            self.close()
            for worker in self.threads:
                worker.join(timeout=1)


class Host:
    def __init__(self, report, identity=None, metrics=None):
        self.report = report
        self.metrics=metrics;self.show_cursor=True;self.quality='balanced';self.video_params=None
        if identity is None:
            from settings import load_settings
            identity = load_settings()
        self.identity = identity
        self.pin = identity['pin']
        self.stop_event = threading.Event()
        self.listener = self.session = self.pad = self.thread = self.advertiser = None
        self.workers = []
        self.active_lock = threading.Lock()
        self.connections_lock = threading.Lock()
        self.connections = set()
        self.resume_event = threading.Event()

    def start(self, fps=30, longest=1024, audio=True, port=8090, mode="auto", monitor=None,
              device_id=None, input_mode='touch', device_serial=None, show_cursor=True,quality='balanced'):
        from video_options import bitrate
        bitrate(quality);self.show_cursor=show_cursor;self.quality=quality
        self.video_params=(fps,longest,quality)
        if any(worker.is_alive() for worker in self.workers) or (self.advertiser and self.advertiser.thread.is_alive()):
            raise RuntimeError('Aguarde o encerramento da transmissão anterior')
        if mode not in ('auto', 'wifi', 'usb') or input_mode not in ('touch', 'gamepad'):
            raise ValueError('Modo inválido')
        if input_mode == 'touch':
            from touchscreen import TouchScreen
            self.pad = TouchScreen()
        else:
            self.pad = XboxPad()
        self.input_mode, self.monitor = input_mode, monitor
        self.resume_event.clear()
        self.stop_event.clear()
        self.workers = []
        if mode in ('auto', 'wifi'):
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(('0.0.0.0', port))
            self.listener.listen(2)
            self.listener.settimeout(0.5)
            self.workers.append(threading.Thread(target=self.serve, args=(fps, longest, audio), daemon=True))
            from discovery import Advertiser
            self.advertiser = Advertiser(self.identity['hostId'], self.listener.getsockname()[1], self.report)
        if mode in ('auto', 'usb'):
            self.workers.append(threading.Thread(target=self.serve_usb,
                                args=(fps, longest, audio, device_id, device_serial), daemon=True))
        self.thread = self.workers[0]
        for worker in self.workers:
            worker.start()
        return self.pin

    def change_monitor(self,monitor):
        self.monitor=dict(monitor)
        if self.session:self.session.change_monitor(monitor)

    def configure_video(self,fps,size,quality):
        from video_options import bitrate
        bitrate(quality)
        if fps not in (15,20,30) or size not in (640,800,1024):raise ValueError('Configuração de vídeo inválida')
        self.video_params=(fps,size,quality);self.quality=quality
        if self.session:self.session.configure_video(fps,size,quality)

    def cursor_enabled(self,enabled):
        self.show_cursor=bool(enabled)
        if self.session:self.session.show_cursor=self.show_cursor

    def authenticate(self, connection):
        import hmac
        connection.settimeout(5)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32768)
        nonce = secrets.token_bytes(32)
        connection.sendall(MAGIC + nonce)
        if not hmac.compare_digest(read_exact(connection, 32), proof(self.pin, nonce)):
            connection.sendall(b"\x00")
            raise PermissionError('PIN incorreto; conexão recusada')
        connection.sendall(b"\x01")
        # New clients send their panel orientation immediately. Old clients still work.
        import select
        client_size = (1024, 768)
        self.auth_client_display_id = None
        self.auth_client_orientation = None
        if select.select([connection], [], [], 1)[0]:
            kind, body = read_packet(connection)
            if kind != CLIENT_INFO or len(body) > 512:
                raise ValueError('Informações iniciais do iPad inválidas')
            value = json.loads(body)
            client_size = validate_display(value)
            self.auth_client_display_id = display_id(value)
            self.auth_client_orientation = display_orientation(value)
        connection.settimeout(3)
        return client_size

    def run_connection(self, connection, fps, longest, audio, transport):
        # Both transports race for one owner; rejected attempts must never reset its input.
        if not self.active_lock.acquire(blocking=False):
            connection.close()
            return
        with self.connections_lock:
            self.connections.add(connection)
        try:
            if self.stop_event.is_set():
                return
            client_size = self.authenticate(connection)
            if self.video_params:fps,longest,self.quality=self.video_params
            self.session = Session(connection, self.pad, fps, longest, audio, self.report,
                                   self.input_mode, self.monitor, self.identity['hostId'], client_size,
                                   self.auth_client_display_id, self.identity.get('wakeKey'),
                                   client_orientation=self.auth_client_orientation,show_cursor=self.show_cursor,
                                   quality=self.quality,metrics=self.metrics)
            self.report('Conexão ' + transport + ' autenticada')
            self.session.run()
        finally:
            connection.close()
            with self.connections_lock:
                self.connections.discard(connection)
            self.session = None
            self.pad.neutral()
            self.active_lock.release()

    def serve_usb(self, fps, longest, audio, device_id, selected_serial=None):
        from usbmux import list_devices, connect_device
        from wake import RetryBudget,request_usb,AUTO,RESUME
        from usb_presence import apple_usb_present,AttachmentTracker
        previous_error = None
        budget=RetryBudget();attachment=AttachmentTracker();attachment_epoch=0
        pending_attachment=False
        while not self.stop_event.is_set():
            try:
                present=apple_usb_present(selected_serial)
                new_attachment=attachment.observe(present)
                if new_attachment:
                    attachment_epoch+=1
                    pending_attachment=True
                elif present is False:
                    pending_attachment=False
                if self.active_lock.locked():
                    self.stop_event.wait(1)
                    continue
                devices = list_devices()
                if selected_serial:
                    devices = [d for d in devices if d.get('Properties', {}).get('SerialNumber') == selected_serial]
                elif device_id is not None:
                    devices = [d for d in devices if d['DeviceID'] == device_id]
                if not devices:
                    raise RuntimeError('Nenhum iPad USB encontrado. Conecte o cabo e confirme Confiar.')
                if len(devices) != 1:
                    raise RuntimeError('Há vários aparelhos USB. Selecione o iPad na lista.')
                selected_serial = devices[0].get('Properties', {}).get('SerialNumber')
                current_device=(selected_serial,devices[0]['DeviceID'])
                budget.reset((current_device,attachment_epoch))
                try:
                    connection = connect_device(devices[0]['DeviceID'])
                except (ConnectionError,RuntimeError,OSError) as stream_error:
                    explicit=self.resume_event.is_set() or pending_attachment
                    if not self.identity.get('wakeKey') or not budget.allow(explicit=explicit):
                        raise stream_error
                    self.resume_event.clear()
                    result=request_usb(devices[0]['DeviceID'],self.identity,RESUME if explicit else AUTO)
                    state=result['status']
                    if state not in ('launch_requested','already_active'):
                        if state in ('locked','paused'):
                            budget.attempts=max(0,budget.attempts-1)
                        messages={'paused':'Abertura automática pausada no iPad. Use Retomar iPad ou ative a opção no aplicativo.',
                                  'locked':'Desbloqueie o iPad para abrir o Shock Stream.',
                                  'unsupported':'O iOS não disponibilizou a abertura automática; abra o aplicativo manualmente.',
                                  'launch_failed':'O iOS recusou abrir o aplicativo. Consulte Diagnóstico no iPad e abra manualmente.'}
                        raise RuntimeError(messages.get(state,'Abra o app no iPad e emparelhe uma vez.'))
                    pending_attachment=False
                    self.report('Solicitação de abertura enviada ao iPad; aguardando o aplicativo…')
                    connection=None;deadline=time.monotonic()+5
                    while not self.stop_event.is_set() and time.monotonic()<deadline:
                        try:connection=connect_device(devices[0]['DeviceID']);break
                        except (ConnectionError,RuntimeError,OSError):self.stop_event.wait(.25)
                    if connection is None:raise RuntimeError('O app ainda não confirmou a abertura. Abra-o no iPad ou consulte o Diagnóstico.')
                previous_error = None
                pending_attachment=False
                self.resume_event.clear()
                self.run_connection(connection, fps, longest, audio, 'USB')
            except Exception as exc:
                message = str(exc)
                if not self.stop_event.is_set() and message != previous_error:
                    logging.warning('USB connection: %s', message)
                    self.report('USB: ' + message)
                previous_error = message
            self.stop_event.wait(2)

    def serve(self, fps, longest, audio):
        listener = self.listener
        while not self.stop_event.is_set():
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.run_connection(connection, fps, longest, audio, 'Wi-Fi')
            except Exception as exc:
                logging.exception('Session error')
                if not self.stop_event.is_set():
                    self.report('Conexão encerrada: ' + str(exc))

    def stop(self):
        self.stop_event.set()
        self.resume_event.clear()
        if self.advertiser:
            self.advertiser.close()
            if not self.advertiser.thread.is_alive():self.advertiser = None
        if self.session:
            self.session.close()
        with self.connections_lock:
            for connection in list(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.listener:
            self.listener.close()
            self.listener = None
        if self.pad:
            self.pad.neutral()


def local_addresses():
    values = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    return ", ".join(sorted(ip for ip in values if not ip.startswith("127."))) or "Consulte o IP nas configurações de rede"


class App:
    def __init__(self,headless=False,background=False):
        from settings import load_settings
        self.headless = headless
        self.tray=None
        self.closing=False
        self.screen_chosen=False
        self.settings = {'hostId':'0'*32, 'pin':'123456'} if headless else load_settings()
        from desktop import dpi_aware
        dpi_aware()
        self.root=tk.Tk();self.root.title("Shock Stream · Wi-Fi e monitor USB")
        if headless:self.root.withdraw()
        height=min(740,self.root.winfo_screenheight()-100)
        self.root.geometry(f"760x{height}");self.root.minsize(700,560);self.root.configure(bg="#101721")
        canvas=tk.Canvas(self.root,bg="#101721",highlightthickness=0)
        scrollbar=tk.Scrollbar(self.root,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(canvas,bg="#101721")
        window=canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        self.root.bind_all('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
        self.messages=queue.Queue();self.host=Host(self.messages.put, self.settings,metrics=self.on_metrics);self.screens=[];self.usb_devices=[]
        self.root.protocol("WM_DELETE_WINDOW",self.hide)
        style=ttk.Style();style.theme_use("clam")
        style.configure("TCombobox",fieldbackground="#243343",foreground="white",padding=6)
        self.label("SHOCK STREAM",25,"#4ce2bc",(16,4))
        self.label("Seu iPad como monitor touch por Wi-Fi ou USB",12,"#becbd8",(0,8))
        self.ip=self.label("IP do PC: "+local_addresses(),11,"white",3)
        self.mode=ttk.Combobox(self.body,values=["Automático · Wi-Fi + USB","Somente Wi-Fi","Somente USB"],state="readonly",width=30)
        self.mode.current(max(0,min(2,self.settings.get('transport',0))));self.mode.pack(pady=5);self.mode.bind('<<ComboboxSelected>>',self.mode_changed)
        self.control=ttk.Combobox(self.body,values=["Monitor touch · tela livre","Gamepad virtual na tela"],state="readonly",width=30)
        self.control.current(max(0,min(1,self.settings.get('input',0))));self.control.pack(pady=3);self.control.bind('<<ComboboxSelected>>',self.mode_changed)
        self.hint=self.label("Abra o app do iPad. Ele procura o PC automaticamente. PIN apenas no primeiro uso.",11,"#a0b4c8",3)
        self.pin=self.label("— — — — — —",28,"#4ce2bc",4)
        self.label("Tela transmitida",11,"#becbd8",2)
        screenrow=tk.Frame(self.body,bg="#101721");screenrow.pack(pady=4)
        self.screen=ttk.Combobox(screenrow,state="readonly",width=62);self.screen.pack(side='left',padx=4)
        self.screen.bind('<<ComboboxSelected>>',self.screen_changed)
        self.button(screenrow,"Atualizar",self.refresh_screens).pack(side='left')
        self.usbrow=tk.Frame(self.body,bg="#101721")
        self.device=ttk.Combobox(self.usbrow,state="readonly",width=50);self.device.pack(side='left',padx=4)
        self.button(self.usbrow,"Detectar iPad",self.refresh_usb).pack(side='left')
        options=tk.Frame(self.body,bg="#101721");options.pack(pady=6)
        self.fps=ttk.Combobox(options,values=["30 FPS","20 FPS","15 FPS"],width=10,state="readonly");self.fps.set("30 FPS");self.fps.pack(side='left',padx=5)
        self.size=ttk.Combobox(options,values=["1024 px","800 px","640 px"],width=10,state="readonly");self.size.set("1024 px");self.size.pack(side='left',padx=5)
        self.audio=tk.BooleanVar(value=True)
        tk.Checkbutton(options,text="Áudio do PC",variable=self.audio,bg="#101721",fg="white",selectcolor="#243343",activebackground="#101721").pack(side='left',padx=8)
        self.quality=ttk.Combobox(self.body,values=['Equilibrado · padrão atual','Texto mais nítido · mais dados','Economizar rede · menos dados'],state='readonly',width=40)
        self.quality.current(max(0,min(2,self.settings.get('videoQuality',0))));self.quality.pack(pady=3)
        for option in (self.fps,self.size,self.quality):option.bind('<<ComboboxSelected>>',self.video_changed)
        self.cursor=tk.BooleanVar(value=self.settings.get('showCursor',True))
        tk.Checkbutton(self.body,text='Mostrar ponteiro do mouse na transmissão',variable=self.cursor,command=self.cursor_changed,bg='#101721',fg='white',selectcolor='#243343',activebackground='#101721').pack(pady=3)
        self.stats=self.label('Sem transmissão ativa',10,'#a0b4c8',3)
        actions=tk.Frame(self.body,bg="#101721");actions.pack(pady=7)
        self.start_button=self.button(actions,"Iniciar",self.start,True);self.start_button.pack(side='left',padx=8)
        self.button(actions,"Parar",self.stop).pack(side='left',padx=8)
        self.button(actions,"Retomar iPad USB",self.resume_ipad).pack(side='left',padx=8)
        self.button(actions,"Sair",self.quit).pack(side='left',padx=8)
        self.auto=tk.BooleanVar(value=self.settings.get('autoStart',True))
        tk.Checkbutton(self.body,text="Ficar pronto para conectar ao abrir este programa",variable=self.auto,command=self.save_preferences,bg="#101721",fg="white",selectcolor="#243343",activebackground="#101721").pack(pady=3)
        from tray_support import startup_enabled
        self.login_start=tk.BooleanVar(value=False if headless else startup_enabled())
        tk.Checkbutton(self.body,text="Iniciar com o Windows e ficar na bandeja",variable=self.login_start,command=self.toggle_startup,bg="#101721",fg="white",selectcolor="#243343",activebackground="#101721").pack(pady=3)
        self.state=self.label("Prepare o suporte Apple para USB e o monitor virtual para preencher toda a tela.",11,"#a0b4c8",8)
        self.label("Preparação pelo aplicativo",13,"#4ce2bc",5)
        drivers=tk.Frame(self.body,bg="#101721");drivers.pack(pady=5)
        self.button(drivers,"Instalar gamepad",self.install_gamepad).pack(side='left',padx=5)
        self.button(drivers,"Criar segundo monitor",self.install_monitor).pack(side='left',padx=5)
        self.button(drivers,"Preparar USB Apple",self.prepare_usb).pack(side='left',padx=5)
        display=tk.Frame(self.body,bg="#101721");display.pack(pady=5)
        self.button(display,"Estender área de trabalho",self.extend).pack(side='left',padx=5)
        self.button(display,"Remover monitor virtual",self.remove_monitor).pack(side='left',padx=5)
        self.button(display,"Verificar monitor",self.monitor_diagnostic).pack(side='left',padx=5)
        self.label("Instaladores incluídos · suporte Apple preparado pelo Windows · autorização do Windows quando necessária",9,"#a0b4c8",6)
        self.mode_changed();self.root.after(100,self.poll)
        if not headless:
            try:
                from tray_support import Tray
                self.tray=Tray(self.messages.put,self.show,self.resume_ipad,self.stop,self.quit)
                if background:self.root.after(500,lambda:self.hide(background=True))
            except Exception as exc:self.messages.put('Bandeja indisponível: '+str(exc))
        if not headless and self.auto.get():self.root.after(500,self.start)

    def label(self,text,size,color,pady):
        label=tk.Label(self.body,text=text,bg="#101721",fg=color,font=("Segoe UI",size),wraplength=680)
        label.pack(pady=pady);return label

    def button(self,parent,text,command,accent=False):
        return tk.Button(parent,text=text,command=command,bg="#4ce2bc" if accent else "#243343",fg="#101721" if accent else "white",relief='flat',font=("Segoe UI",11),padx=12,pady=7)

    def mode_changed(self,event=None):
        if self.host.thread and self.host.thread.is_alive():self.stop()
        usb=self.mode.current()!=1
        if usb:
            self.usbrow.pack(after=self.screen.master,pady=4)
            if not self.headless:self.refresh_usb()
        else:self.usbrow.pack_forget()
        self.hint.config(text="Abra o app no iPad. PIN uma vez; reconexão automática depois. USB: confirme Confiar." if usb else "Mesma rede Wi-Fi. O iPad localiza este PC sem digitar IP. PIN no primeiro uso.")
        self.refresh_screens()

    def save_preferences(self):
        if self.headless:return
        from settings import save_settings
        self.settings.update(transport=self.mode.current(),input=self.control.current(),autoStart=self.auto.get())
        self.settings.update(showCursor=self.cursor.get(),videoQuality=self.quality.current())
        if self.screen.current()>=0:self.settings['screenDevice']=self.screens[self.screen.current()]['device']
        save_settings(self.settings)

    def toggle_startup(self):
        try:
            from tray_support import set_startup
            set_startup(self.login_start.get())
            if self.login_start.get():self.auto.set(True);self.save_preferences()
            self.state.config(text='Inicialização com o Windows atualizada. Mantenha o programa nesta pasta.')
        except Exception as exc:
            self.login_start.set(not self.login_start.get());messagebox.showerror('Inicialização do Windows',str(exc))

    def show(self):
        self.root.deiconify();self.root.lift()

    def hide(self,background=False):
        if self.tray and self.tray.ready.is_set():self.root.withdraw()
        elif background:self.show()
        else:self.quit()

    def resume_ipad(self):
        if self.mode.current()==1:self.mode.current(0);self.mode_changed()
        if not any(worker.is_alive() for worker in self.host.workers):self.start()
        self.host.resume_event.set()
        self.state.config(text='Retomada USB solicitada. O iPad deve estar emparelhado e com abertura automática ativada.')

    def screen_changed(self,event=None):
        self.screen_chosen=True
        self.save_preferences()
        if self.screen.current()>=0:
            self.host.change_monitor(self.screens[self.screen.current()])
            self.state.config(text='Tela selecionada. Imagem e touch serão ajustados na conexão atual.')

    def video_changed(self,event=None):
        quality=('balanced','text','economy')[max(0,self.quality.current())]
        self.host.configure_video(int(self.fps.get().split()[0]),int(self.size.get().split()[0]),quality)
        self.save_preferences()

    def cursor_changed(self):
        self.host.cursor_enabled(self.cursor.get());self.save_preferences()

    def on_metrics(self,value):
        def apply():
            if self.host.session:
                self.stats.config(text=f"{value['fps']:.1f} FPS reais · vídeo {value['mbps']:.2f} Mb/s · resposta {value['ack_ms']:.0f} ms")
        self.messages.put(apply)

    def refresh_screens(self):
        try:
            from desktop import monitors
            previous=self.screen.current();self.screens=monitors()
            self.screen['values']=[f"{'Monitor principal' if m.get('primary') else 'Monitor virtual' if m['virtual'] else 'Monitor'} {i+1} · {m['width']}×{m['height']} · {m['adapter']}" for i,m in enumerate(self.screens)]
            if self.screens:
                virtual=next((i for i,m in enumerate(self.screens) if m['virtual']),None)
                remembered=next((i for i,m in enumerate(self.screens) if m['device']==self.settings.get('screenDevice')),None)
                choice=remembered if self.screen_chosen and remembered is not None else virtual if self.control.current()==0 and virtual is not None else max(0,min(previous,len(self.screens)-1))
                self.screen.current(choice)
                if virtual is None and self.control.current()==0:
                    self.state.config(text='Somente tela física disponível: ela pode ter proporção wide. Criar segundo monitor fornece 1024×768; Nova área de trabalho do Windows não cria monitor.')
        except Exception as exc:self.state.config(text=str(exc))

    def refresh_usb(self):
        if self.host.thread and self.host.thread.is_alive():
            self.state.config(text='Pare a transmissão antes de selecionar outro iPad.');return
        def work():
            try:
                from usbmux import list_devices
                devices=list_devices()
                def apply():
                    self.usb_devices=devices
                    self.device['values']=['Automático · único iPad conectado']+["Apple USB · "+d.get('Properties',{}).get('SerialNumber',str(d['DeviceID'])) for d in devices]
                    self.device.current(0)
                    if devices:self.state.config(text="iPad detectado. Abra o app no iPad; informe o PIN no primeiro uso.")
                    else:self.state.config(text="USB aguardando cabo/Confiar. A descoberta Wi-Fi continua disponível no modo automático.")
                self.messages.put(apply)
            except Exception as exc:self.messages.put(str(exc))
        threading.Thread(target=work,daemon=True).start()

    def background(self,label,action,refresh=False):
        self.state.config(text=label)
        def work():
            try:
                result=action()
                self.messages.put(result if isinstance(result,str) else "Etapa concluída."+(" Reinicie o PC para concluir a instalação." if result in (3010,1641) else ""))
                if refresh:self.messages.put(self.refresh_screens)
            except Exception as exc:self.messages.put(str(exc))
        threading.Thread(target=work,daemon=True).start()

    def install_gamepad(self):
        self.stop()
        from setup_manager import install_gamepad
        self.background("Abrindo o instalador do gamepad incluído no aplicativo…",install_gamepad)

    def install_monitor(self):
        self.stop()
        from setup_manager import monitor_driver
        def install_and_extend():
            result=monitor_driver()
            if result==0:
                from desktop import ensure_virtual_monitor
                for attempt in range(10):
                    try:ensure_virtual_monitor();break
                    except RuntimeError:
                        if attempt==9:raise
                    time.sleep(0.5)
                self.messages.put(self.select_virtual)
            return result
        self.background("O Windows solicitará autorização para instalar o monitor virtual…",install_and_extend,True)

    def remove_monitor(self):
        self.stop()
        from setup_manager import monitor_driver
        self.background("O Windows solicitará autorização para remover o monitor virtual…",lambda:monitor_driver(True),True)

    def prepare_usb(self):
        self.stop()
        from setup_manager import prepare_apple_usb
        def prepare():
            result=prepare_apple_usb()
            self.messages.put(self.refresh_usb)
            return result
        self.background("Preparando o suporte USB Apple pelo Windows. Internet necessária na primeira instalação…",prepare)

    def extend(self):
        from desktop import ensure_virtual_monitor
        def activate():
            ensure_virtual_monitor();self.messages.put(self.select_virtual)
            return 'Monitor virtual ativo. Ele será ajustado à proporção do iPad ao conectar.'
        self.background("Ativando o monitor virtual como segunda tela…",activate,True)

    def select_virtual(self):
        self.screen_chosen=False;self.refresh_screens()
        choice=next((i for i,m in enumerate(self.screens) if m.get('virtual')),None)
        if choice is not None:
            self.screen.current(choice);self.host.change_monitor(self.screens[choice]);self.save_preferences()

    def monitor_diagnostic(self):
        from desktop import virtual_monitor_status
        self.background('Verificando telas e driver do monitor virtual…',lambda:virtual_monitor_status()['message'])

    def start(self):
        try:
            if self.screen.current()<0:raise RuntimeError('Selecione uma tela para transmitir')
            device_id=device_serial=None
            if self.device.current()>0:
                device=self.usb_devices[self.device.current()-1]
                device_id=device['DeviceID'];device_serial=device.get('Properties',{}).get('SerialNumber')
            pin=self.host.start(int(self.fps.get().split()[0]),int(self.size.get().split()[0]),self.audio.get(),mode=('auto','wifi','usb')[self.mode.current()],monitor=self.screens[self.screen.current()],device_id=device_id,device_serial=device_serial,input_mode='touch' if self.control.current()==0 else 'gamepad',show_cursor=self.cursor.get(),quality=('balanced','text','economy')[max(0,self.quality.current())])
            self.save_preferences()
            self.pin.config(text=' '.join(pin));self.start_button.config(state='disabled')
            self.screen.config(state='readonly');self.device.config(state='disabled')
            selected=self.screens[self.screen.current()]
            self.state.config(text="Pronto. O monitor virtual acompanhará 1024×768 ou 768×1024 do iPad." if selected.get('virtual') else "Espelhando tela física: a proporção original pode deixar barras. Use Criar segundo monitor para uma área 4:3 completa no iPad.")
        except Exception as exc:self.host.stop();messagebox.showerror("Não foi possível iniciar",str(exc))

    def stop(self):
        self.host.stop();self.start_button.config(state='normal');self.pin.config(text="— — — — — —")
        self.stats.config(text='Sem transmissão ativa')
        self.screen.config(state='readonly');self.device.config(state='readonly')

    def poll(self):
        while not self.messages.empty():
            message=self.messages.get()
            if callable(message):message()
            else:self.state.config(text=message)
        self.root.after(100,self.poll)

    def quit(self):
        if self.closing:return
        self.closing=True;self.host.stop()
        if self.tray:self.tray.stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import av
        import numpy as np
        import mss, soundcard, importlib.util, ctypes
        from discovery import service_info
        from tray_support import icon_image
        import pystray._win32
        from cursor_capture import CursorRenderer
        renderer=CursorRenderer()
        try:
            renderer.user.LoadCursorW.argtypes=[ctypes.c_void_p,ctypes.c_void_p];renderer.user.LoadCursorW.restype=ctypes.c_void_p
            cursor=renderer.user.LoadCursorW(None,ctypes.c_void_p(32512))
            sample=np.full((64,64,4),128,dtype=np.uint8)
            assert renderer.draw_icon(sample,dict(left=0,top=0,width=64,height=64),cursor,8,8)
            assert np.any(sample[:,:,:3]!=128)
        finally:renderer.close()
        assert icon_image().size==(64,64)
        assert service_info('0'*32,8090,['192.168.1.2']).port==8090
        # Importing vgamepad itself connects to the bus, which is absent on build runners.
        spec = importlib.util.find_spec('vgamepad')
        assert spec and spec.submodule_search_locations
        dll = Path(next(iter(spec.submodule_search_locations))) / 'win/vigem/client/x64/ViGEmClient.dll'
        assert dll.is_file(), 'ViGEmClient DLL is missing from the package'
        ctypes.WinDLL(str(dll))
        from setup_manager import resource_root
        root=resource_root()
        if getattr(sys,'frozen',False):
            assert (root/'DriverSetup.exe').is_file()
            assert (root/'drivers/ViGEmBus.exe').is_file()
            assert (root/'drivers/vdd/MttVDD.inf').is_file()
            result=subprocess.run([str(root/'DriverSetup.exe'),'--self-test'],creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode==0
        encoder = make_encoder(128, 72, 30)
        image = av.VideoFrame.from_ndarray(np.zeros((72, 128, 3), dtype=np.uint8), format="rgb24")
        encoded = b"".join(bytes(p) for p in encoder.encode(image.reformat(format="yuv420p")))
        assert b"\x00\x00\x00\x01" in encoded
        app=App(headless=True);app.root.update_idletasks()
        assert len(app.mode['values'])==3 and len(app.control['values'])==2
        app.quit()
        print("PASS: bundled libraries, H.264 baseline encoder, immediate Annex-B output")
        return
    folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShockStream"
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=folder / "host.log", level=logging.INFO, format="%(asctime)s %(message)s",encoding='utf-8')
    from tray_support import InstanceGuard
    instance=InstanceGuard()
    try:
        if instance.owner:App(background=args.background).root.mainloop()
        elif not args.background:instance.show_existing()
    finally:instance.close()


if __name__ == "__main__":
    main()
