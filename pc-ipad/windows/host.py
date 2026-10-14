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
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from protocol import (MAGIC, VIDEO, AUDIO, INFO, ERROR, ACK, PAD, BYE, HEARTBEAT,
                      LatestFrame, fit_size, packet, proof, read_exact, read_packet, validate_pad)

VERSION = "0.1.0"
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
    def __init__(self, connection, gamepad, fps, size, audio, report):
        self.sock = connection
        self.gamepad = gamepad
        self.fps, self.size, self.audio = fps, size, audio
        self.report = report
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
                monitor = capture.monitors[1]
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
                elif kind == PAD and len(body) <= 2048:
                    self.gamepad.apply(json.loads(body))
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
                    "audio": self.audio, "sampleRate": 44100, "channels": 2, "gamepad": "Xbox 360"}
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

    def start(self, fps=30, longest=1024, audio=True, port=8090):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("O host já está ativo")
        self.pad = XboxPad()
        self.stop_event.clear()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("0.0.0.0", port))
        self.listener.listen(1)
        self.listener.settimeout(0.5)
        self.pin = f"{secrets.randbelow(1000000):06d}"
        self.thread = threading.Thread(target=self.serve, args=(fps, longest, audio), daemon=True)
        self.thread.start()
        return self.pin

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
                connection.settimeout(5)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32768)
                nonce = secrets.token_bytes(32)
                connection.sendall(MAGIC + nonce)
                if not hmac.compare_digest(read_exact(connection, 32), proof(self.pin, nonce)):
                    connection.sendall(b"\x00")
                    self.report("PIN incorreto; tentativa recusada")
                    self.stop_event.wait(2)
                    continue
                connection.sendall(b"\x01")
                connection.settimeout(3)
                self.session = Session(connection, self.pad, fps, longest, audio, self.report)
                self.session.run()
            except Exception as exc:
                logging.exception("Session error")
                self.report("Conexão encerrada: " + str(exc))
            finally:
                connection.close()
                self.session = None
                self.pad.neutral()
        self.report("Transmissão parada")

    def stop(self):
        self.stop_event.set()
        if self.session:
            self.session.close()
        if self.listener:
            self.listener.close()
        if self.pad:
            self.pad.neutral()


def local_addresses():
    values = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    return ", ".join(sorted(ip for ip in values if not ip.startswith("127."))) or "Consulte o IP nas configurações de rede"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Shock Stream · PC → iPad")
        self.root.geometry("650x560")
        self.root.minsize(560, 530)
        self.root.configure(bg="#101721")
        self.messages = queue.Queue()
        self.host = Host(self.messages.put)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground="#243343", foreground="white", padding=8)
        self.label("SHOCK STREAM", 26, "#4ce2bc", pady=(28, 8))
        self.label("Seu PC. Seu jogo. Seu iPad.", 14, "#becbd8", pady=(0, 22))
        self.label("IP do computador: " + local_addresses(), 12, "white", pady=6)
        self.label("No iPad, informe este IP, a porta 8090 e o PIN abaixo.", 11, "#a0b4c8", pady=6)
        self.pin = self.label("— — — — — —", 32, "#4ce2bc", pady=12)
        row = tk.Frame(self.root, bg="#101721")
        row.pack(pady=10)
        self.fps = ttk.Combobox(row, values=["30 FPS", "20 FPS", "15 FPS"], width=10, state="readonly")
        self.fps.set("30 FPS")
        self.fps.pack(side="left", padx=8)
        self.size = ttk.Combobox(row, values=["1024 px", "800 px", "640 px"], width=10, state="readonly")
        self.size.set("1024 px")
        self.size.pack(side="left", padx=8)
        self.audio = tk.BooleanVar(value=True)
        tk.Checkbutton(self.root, text="Transmitir áudio do PC", variable=self.audio, bg="#101721", fg="white", selectcolor="#243343", activebackground="#101721").pack(pady=6)
        self.start_button = tk.Button(self.root, text="Iniciar transmissão", command=self.start, bg="#4ce2bc", fg="#101721", font=("Segoe UI", 13, "bold"), relief="flat", padx=24, pady=10)
        self.start_button.pack(pady=8)
        tk.Button(self.root, text="Parar", command=self.stop, bg="#243343", fg="white", relief="flat", padx=25, pady=6).pack()
        self.state = self.label("Aguardando · gamepad Xbox virtual via ViGEmBus", 11, "#a0b4c8", pady=12)
        tk.Button(self.root, text="Instalar driver do gamepad (ViGEmBus)", command=lambda: webbrowser.open(DRIVER_URL), bg="#101721", fg="#4ce2bc", relief="flat").pack()
        self.root.after(100, self.poll)

    def label(self, text, size, color, pady):
        label = tk.Label(self.root, text=text, bg="#101721", fg=color, font=("Segoe UI", size), wraplength=600)
        label.pack(pady=pady)
        return label

    def start(self):
        try:
            pin = self.host.start(int(self.fps.get().split()[0]), int(self.size.get().split()[0]), self.audio.get())
            self.pin.config(text=" ".join(pin))
            self.state.config(text="Pronto para conectar · permita acesso à rede privada no Firewall")
            self.start_button.config(state="disabled")
        except Exception as exc:
            self.host.stop()
            messagebox.showerror("Não foi possível iniciar", str(exc))

    def stop(self):
        self.host.stop()
        self.start_button.config(state="normal")
        self.pin.config(text="— — — — — —")

    def poll(self):
        while not self.messages.empty():
            self.state.config(text=self.messages.get())
        self.root.after(100, self.poll)

    def quit(self):
        self.host.stop()
        self.root.destroy()


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
        encoder = make_encoder(128, 72, 30)
        image = av.VideoFrame.from_ndarray(np.zeros((72, 128, 3), dtype=np.uint8), format="rgb24")
        encoded = b"".join(bytes(p) for p in encoder.encode(image.reformat(format="yuv420p")))
        assert b"\x00\x00\x00\x01" in encoded
        print("PASS: bundled libraries, H.264 baseline encoder, immediate Annex-B output")
        return
    folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShockStream"
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=folder / "host.log", level=logging.INFO, format="%(asctime)s %(message)s")
    App().root.mainloop()


if __name__ == "__main__":
    main()
