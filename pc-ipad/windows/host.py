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

from protocol import (MAGIC, VIDEO, AUDIO, INFO, ERROR, ACK, PAD, BYE, HEARTBEAT, TOUCH,
                      LatestFrame, fit_size, packet, proof, read_exact, read_packet, validate_pad)

VERSION = "0.2.0"
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


def make_encoder(width, height, fps):
    import av
    from fractions import Fraction
    codec = av.CodecContext.create("libx264", "w")
    codec.width, codec.height = width, height
    codec.pix_fmt = "yuv420p"
    codec.time_base = Fraction(1, fps)
    codec.framerate = Fraction(fps, 1)
    codec.bit_rate = 2500000
    codec.options = {"preset": "ultrafast", "tune": "zerolatency", "profile": "baseline",
                     "x264-params": "repeat-headers=1:annexb=1:bframes=0:keyint=30:scenecut=0"}
    codec.open()
    return codec


class Session:
    def __init__(self, connection, gamepad, fps, size, audio, report, mode="gamepad", monitor=None):
        self.sock = connection
        self.gamepad = gamepad
        self.fps, self.size, self.audio = fps, size, audio
        self.report = report
        self.mode,self.monitor=mode,monitor
        self.stop = threading.Event()
        self.ack = threading.Event()
        self.latest = LatestFrame()
        self.audio_frames = collections.deque(maxlen=2)
        self.audio_lock = threading.Lock()
        self.capture_error = None
        self.threads = []
        self.width = self.height = 0

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
        try:
            import mss
            import numpy as np
            with mss.mss() as capture:
                monitor = self.monitor or capture.monitors[1]
                monitor={key:monitor[key] for key in ('left','top','width','height')}
                if self.mode=='touch':self.gamepad.set_monitor(monitor)
                self.width, self.height = fit_size(monitor["width"], monitor["height"], self.size)
                period = 1 / self.fps
                while not self.stop.is_set():
                    started = time.monotonic()
                    image = capture.grab(monitor)
                    # Copy so the single latest frame owns its backing memory.
                    self.latest.put(np.array(image, dtype=np.uint8, copy=True))
                    self.stop.wait(max(0, period - (time.monotonic() - started)))
        except Exception as exc:
            self.capture_error = exc
            self.stop.set()

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
                    self.gamepad.events(json.loads(body))
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
        with self.audio_lock:
            audio = self.audio_frames.popleft() if self.audio_frames else None
        if audio:
            self.sock.sendall(packet(AUDIO, audio))

    def watchdog(self):
        while not self.stop.wait(0.1):
            self.gamepad.expire()

    def run(self):
        import av
        try:
            capture_thread = threading.Thread(target=self.capture, daemon=True)
            capture_thread.start()
            self.threads.append(capture_thread)
            sequence, raw = self.latest.take_after(0, 3)
            if raw is None:
                raise RuntimeError("Não foi possível capturar o monitor: " + str(self.capture_error))
            encoder = make_encoder(self.width, self.height, self.fps)
            info = {"version": 1, "width": self.width, "height": self.height, "fps": self.fps,
                    "audio": self.audio, "sampleRate": 44100, "channels": 2, "mode":self.mode, "gamepad": "Xbox 360" if self.mode=="gamepad" else None}
            self.sock.sendall(packet(INFO, json.dumps(info).encode()))
            for target in ([self.receive, self.watchdog, self.capture_audio] if self.audio else [self.receive, self.watchdog]):
                worker = threading.Thread(target=target, daemon=True)
                self.threads.append(worker)
                worker.start()
            self.report(f"iPad conectado · {self.width} × {self.height} · {self.fps} FPS alvo")
            pts = 0
            while not self.stop.is_set():
                frame = av.VideoFrame.from_ndarray(raw, format="bgra").reformat(self.width, self.height, format="yuv420p")
                frame.pts = pts
                pts += 1
                encoded = b"".join(bytes(p) for p in encoder.encode(frame))
                if not encoded:
                    raise RuntimeError("O encoder H.264 não produziu um frame imediato")
                # Drop raw captures BEFORE encoding; never drop dependent H.264 packets.
                self.ack.clear()
                self.sock.sendall(packet(VIDEO, encoded))
                deadline = time.monotonic() + 3
                while not self.stop.is_set() and not self.ack.is_set():
                    self.gamepad.expire()
                    self.send_audio()
                    if time.monotonic() > deadline:
                        raise TimeoutError("O iPad não confirmou a decodificação do vídeo")
                    self.ack.wait(0.005)
                self.send_audio()
                sequence, next_frame = self.latest.take_after(sequence)
                if next_frame is not None:
                    raw = next_frame
        finally:
            self.close()
            for worker in self.threads:
                worker.join(timeout=1)


class Host:
    def __init__(self, report):
        self.report = report
        self.stop_event = threading.Event()
        self.listener = None
        self.session = None
        self.pad = None
        self.thread = None
        self.pending_connection=None

    def start(self, fps=30, longest=1024, audio=True, port=8090, mode="wifi", monitor=None, device_id=None):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("O host já está ativo")
        if mode not in ('wifi','usb'):raise ValueError('Modo inválido')
        if mode=='usb':
            from touchscreen import TouchScreen
            self.pad=TouchScreen()
        else:self.pad=XboxPad()
        self.stop_event.clear()
        self.pin = f"{secrets.randbelow(1000000):06d}"
        self.monitor=monitor
        if mode=='wifi':
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(("0.0.0.0", port));self.listener.listen(1);self.listener.settimeout(0.5)
            self.thread=threading.Thread(target=self.serve,args=(fps,longest,audio),daemon=True)
        else:self.thread=threading.Thread(target=self.serve_usb,args=(fps,longest,audio,device_id),daemon=True)
        self.thread.start()
        return self.pin

    def authenticate(self,connection):
        import hmac
        connection.settimeout(5)
        connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        connection.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,32768)
        nonce=secrets.token_bytes(32);connection.sendall(MAGIC+nonce)
        if not hmac.compare_digest(read_exact(connection,32),proof(self.pin,nonce)):
            connection.sendall(b"\x00");raise PermissionError('PIN incorreto; conexão recusada')
        connection.sendall(b"\x01");connection.settimeout(3)

    def serve_usb(self,fps,longest,audio,device_id):
        from usbmux import list_devices,connect_device
        while not self.stop_event.is_set():
            connection=None
            try:
                devices=list_devices()
                if device_id is not None:devices=[d for d in devices if d['DeviceID']==device_id]
                if len(devices)!=1:raise RuntimeError('Selecione um único iPad USB na lista e abra Aguardar PC no iPad')
                connection=connect_device(devices[0]['DeviceID']);self.pending_connection=connection
                self.authenticate(connection)
                self.session=Session(connection,self.pad,fps,longest,audio,self.report,'touch',self.monitor)
                self.session.run()
            except Exception as exc:
                if not self.stop_event.is_set():self.report('USB: '+str(exc))
            finally:
                if connection:connection.close()
                self.pending_connection=None;self.session=None;self.pad.neutral()
            self.stop_event.wait(1)
        self.report('Monitor USB parado')

    def serve(self, fps, longest, audio):
        import hmac
        while not self.stop_event.is_set():
            try:
                connection, peer = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.pending_connection=connection
                self.authenticate(connection)
                self.session = Session(connection, self.pad, fps, longest, audio, self.report, 'gamepad',self.monitor)
                self.session.run()
            except Exception as exc:
                logging.exception("Session error")
                self.report("Conexão encerrada: " + str(exc))
            finally:
                connection.close()
                self.session = None
                self.pending_connection=None
                self.pad.neutral()
        self.report("Transmissão parada")

    def stop(self):
        self.stop_event.set()
        if self.session:
            self.session.close()
        if self.pending_connection:
            try:self.pending_connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        if self.listener:
            self.listener.close()
        if self.pad:
            self.pad.neutral()


def local_addresses():
    values = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    return ", ".join(sorted(ip for ip in values if not ip.startswith("127."))) or "Consulte o IP nas configurações de rede"


class App:
    def __init__(self,headless=False):
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
        self.messages=queue.Queue();self.host=Host(self.messages.put);self.screens=[];self.usb_devices=[]
        self.root.protocol("WM_DELETE_WINDOW",self.quit)
        style=ttk.Style();style.theme_use("clam")
        style.configure("TCombobox",fieldbackground="#243343",foreground="white",padding=6)
        self.label("SHOCK STREAM",25,"#4ce2bc",(16,4))
        self.label("Wi-Fi para jogar · USB para usar o iPad como monitor touch",12,"#becbd8",(0,8))
        self.ip=self.label("IP do PC: "+local_addresses(),11,"white",3)
        self.mode=ttk.Combobox(self.body,values=["Wi-Fi · Gamepad","USB · Monitor touch"],state="readonly",width=28)
        self.mode.set("Wi-Fi · Gamepad");self.mode.pack(pady=5);self.mode.bind('<<ComboboxSelected>>',self.mode_changed)
        self.hint=self.label("No iPad: Wi-Fi, IP do PC e PIN. Porta 8090.",11,"#a0b4c8",3)
        self.pin=self.label("— — — — — —",28,"#4ce2bc",4)
        self.label("Tela transmitida",11,"#becbd8",2)
        screenrow=tk.Frame(self.body,bg="#101721");screenrow.pack(pady=4)
        self.screen=ttk.Combobox(screenrow,state="readonly",width=62);self.screen.pack(side='left',padx=4)
        self.button(screenrow,"Atualizar",self.refresh_screens).pack(side='left')
        self.usbrow=tk.Frame(self.body,bg="#101721")
        self.device=ttk.Combobox(self.usbrow,state="readonly",width=50);self.device.pack(side='left',padx=4)
        self.button(self.usbrow,"Detectar iPad",self.refresh_usb).pack(side='left')
        options=tk.Frame(self.body,bg="#101721");options.pack(pady=6)
        self.fps=ttk.Combobox(options,values=["30 FPS","20 FPS","15 FPS"],width=10,state="readonly");self.fps.set("30 FPS");self.fps.pack(side='left',padx=5)
        self.size=ttk.Combobox(options,values=["1024 px","800 px","640 px"],width=10,state="readonly");self.size.set("1024 px");self.size.pack(side='left',padx=5)
        self.audio=tk.BooleanVar(value=True)
        tk.Checkbutton(options,text="Áudio do PC",variable=self.audio,bg="#101721",fg="white",selectcolor="#243343",activebackground="#101721").pack(side='left',padx=8)
        actions=tk.Frame(self.body,bg="#101721");actions.pack(pady=7)
        self.start_button=self.button(actions,"Iniciar",self.start,True);self.start_button.pack(side='left',padx=8)
        self.button(actions,"Parar",self.stop).pack(side='left',padx=8)
        self.state=self.label("Escolha o modo e prepare os drivers abaixo na primeira utilização.",11,"#a0b4c8",8)
        self.label("Preparação pelo aplicativo",13,"#4ce2bc",5)
        drivers=tk.Frame(self.body,bg="#101721");drivers.pack(pady=5)
        self.button(drivers,"Instalar gamepad",self.install_gamepad).pack(side='left',padx=5)
        self.button(drivers,"Criar segundo monitor",self.install_monitor).pack(side='left',padx=5)
        self.button(drivers,"Preparar USB Apple",self.prepare_usb).pack(side='left',padx=5)
        display=tk.Frame(self.body,bg="#101721");display.pack(pady=5)
        self.button(display,"Estender área de trabalho",self.extend).pack(side='left',padx=5)
        self.button(display,"Remover monitor virtual",self.remove_monitor).pack(side='left',padx=5)
        self.label("Instaladores incluídos · suporte Apple preparado pelo Windows · autorização do Windows quando necessária",9,"#a0b4c8",6)
        self.refresh_screens();self.root.after(100,self.poll)

    def label(self,text,size,color,pady):
        label=tk.Label(self.body,text=text,bg="#101721",fg=color,font=("Segoe UI",size),wraplength=680)
        label.pack(pady=pady);return label

    def button(self,parent,text,command,accent=False):
        return tk.Button(parent,text=text,command=command,bg="#4ce2bc" if accent else "#243343",fg="#101721" if accent else "white",relief='flat',font=("Segoe UI",11),padx=12,pady=7)

    def mode_changed(self,event=None):
        if self.host.thread and self.host.thread.is_alive():self.stop()
        usb=self.mode.current()==1
        if usb:self.usbrow.pack(after=self.screen.master,pady=4);self.refresh_usb()
        else:self.usbrow.pack_forget()
        self.hint.config(text="No iPad: USB, PIN do PC e Aguardar PC. Conecte o cabo e confirme Confiar." if usb else "No iPad: Wi-Fi, IP do PC e PIN. Porta 8090.")
        self.refresh_screens()

    def refresh_screens(self):
        try:
            from desktop import monitors
            previous=self.screen.current();self.screens=monitors()
            self.screen['values']=[f"{'Monitor virtual' if m['virtual'] else 'Tela'} {i+1} · {m['width']}×{m['height']} · {m['adapter']}" for i,m in enumerate(self.screens)]
            if self.screens:
                virtual=next((i for i,m in enumerate(self.screens) if m['virtual']),None)
                choice=virtual if self.mode.current()==1 and virtual is not None else max(0,min(previous,len(self.screens)-1))
                self.screen.current(choice)
        except Exception as exc:self.state.config(text=str(exc))

    def refresh_usb(self):
        def work():
            try:
                from usbmux import list_devices
                devices=list_devices()
                def apply():
                    self.usb_devices=devices
                    self.device['values']=["Apple USB · "+d.get('Properties',{}).get('SerialNumber',str(d['DeviceID'])) for d in devices]
                    if devices:self.device.current(0);self.state.config(text="iPad detectado. Abra USB no app do iPad e informe o PIN.")
                    else:self.state.config(text="Nenhum iPad USB encontrado. Conecte o cabo e confirme Confiar.")
                self.messages.put(apply)
            except Exception as exc:self.messages.put(str(exc))
        threading.Thread(target=work,daemon=True).start()

    def background(self,label,action,refresh=False):
        self.state.config(text=label)
        def work():
            try:
                result=action()
                self.messages.put("Etapa concluída."+(" Reinicie o PC para concluir a instalação." if result in (3010,1641) else ""))
                if refresh:self.messages.put(self.refresh_screens)
            except Exception as exc:self.messages.put(str(exc))
        threading.Thread(target=work,daemon=True).start()

    def install_gamepad(self):
        from setup_manager import install_gamepad
        self.background("Abrindo o instalador do gamepad incluído no aplicativo…",install_gamepad)

    def install_monitor(self):
        from setup_manager import monitor_driver
        def install_and_extend():
            result=monitor_driver()
            if result==0:
                from desktop import monitors,extend_desktop
                for _ in range(10):
                    if any(m['virtual'] for m in monitors()):extend_desktop();break
                    time.sleep(0.5)
            return result
        self.background("O Windows solicitará autorização para instalar o monitor virtual…",install_and_extend,True)

    def remove_monitor(self):
        self.stop()
        from setup_manager import monitor_driver
        self.background("O Windows solicitará autorização para remover o monitor virtual…",lambda:monitor_driver(True),True)

    def prepare_usb(self):
        from setup_manager import prepare_apple_usb
        self.background("Preparando o suporte USB Apple pelo Windows. Internet necessária na primeira instalação…",prepare_apple_usb)

    def extend(self):
        from desktop import extend_desktop
        self.background("Estendendo a área de trabalho…",extend_desktop,True)

    def start(self):
        try:
            if self.screen.current()<0:raise RuntimeError('Selecione uma tela para transmitir')
            usb=self.mode.current()==1;device_id=None
            if usb:
                if self.device.current()<0:raise RuntimeError('Clique Detectar iPad e selecione o aparelho USB')
                device_id=self.usb_devices[self.device.current()]['DeviceID']
            pin=self.host.start(int(self.fps.get().split()[0]),int(self.size.get().split()[0]),self.audio.get(),mode='usb' if usb else 'wifi',monitor=self.screens[self.screen.current()],device_id=device_id)
            self.pin.config(text=' '.join(pin));self.start_button.config(state='disabled')
            self.state.config(text="USB pronto: informe este PIN no iPad e toque Aguardar PC." if usb else "Wi-Fi pronto: conecte o iPad com o IP e este PIN.")
        except Exception as exc:self.host.stop();messagebox.showerror("Não foi possível iniciar",str(exc))

    def stop(self):
        self.host.stop();self.start_button.config(state='normal');self.pin.config(text="— — — — — —")

    def poll(self):
        while not self.messages.empty():
            message=self.messages.get()
            if callable(message):message()
            else:self.state.config(text=message)
        self.root.after(100,self.poll)

    def quit(self):self.host.stop();self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import av
        import numpy as np
        import mss, soundcard, importlib.util, ctypes
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
        assert len(app.mode['values'])==2
        app.quit()
        print("PASS: bundled libraries, H.264 baseline encoder, immediate Annex-B output")
        return
    folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShockStream"
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=folder / "host.log", level=logging.INFO, format="%(asctime)s %(message)s")
    App().root.mainloop()


if __name__ == "__main__":
    main()
