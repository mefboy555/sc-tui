"""Воспроизведение через mpv с управлением по IPC-сокету."""

import json
import os
import select
import socket
import subprocess
import sys
import termios
import time
import tty

from . import ui

SOCKET_PATH = "/tmp/scplayer_mpv.sock"
REPEAT_ICON = {"off": "", "all": " 🔁", "one": " 🔂"}


class MPVController:
    """Оборачивает процесс mpv и общение с ним через unix-сокет."""

    def __init__(self):
        self.socket_path = SOCKET_PATH
        self.process = None

    def start(self, url: str) -> None:
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        self.process = subprocess.Popen(
            ["mpv", "--no-video", "--quiet",
             f"--input-ipc-server={self.socket_path}", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if os.path.exists(self.socket_path):
                return
            time.sleep(0.1)
        raise RuntimeError("mpv не создал IPC-сокет")

    def _rpc(self, command: list) -> dict | None:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(self.socket_path)
            sock.send((json.dumps({"command": command}) + "\n").encode())
            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.close()
            return json.loads(data.decode().splitlines()[0]) if data else None
        except Exception:
            return None

    def get(self, name: str, default=None):
        resp = self._rpc(["get_property", name])
        if resp and resp.get("error") == "success":
            return resp.get("data", default)
        return default

    def set(self, name: str, value) -> None:
        self._rpc(["set_property", name, value])

    def cmd(self, *args) -> None:
        self._rpc(list(args))

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)


def play(stream_url: str, title: str, cfg,
         queue_pos: int | None = None, queue_len: int | None = None) -> str:
    """
    Проигрывает трек и обрабатывает клавиши до конца трека или выхода.
    Возвращает: 'ended' | 'quit' | 'next' | 'prev'
    """
    mpv = MPVController()
    step = int(cfg.get("volume_step", 5))
    max_vol = int(cfg.get("max_volume", 150))
    seek_step = int(cfg.get("seek_step", 10))
    qinfo = f"[{queue_pos}/{queue_len}] " if queue_len else ""
    reason = "ended"

    def render() -> None:
        paused = mpv.get("pause", False)
        pos = mpv.get("time-pos")
        dur = mpv.get("duration")
        vol = int(mpv.get("volume", 100))
        muted = mpv.get("mute", False)

        state = "ПАУЗА" if paused else "ИГРАЕТ"
        vol_str = "MUTE" if muted else f"{vol:3d}%"
        filled = max(0, min(15, int(min(vol, 100) / 100 * 15)))
        bar = "█" * filled + "░" * (15 - filled)
        rep = REPEAT_ICON.get(cfg.get("repeat", "off"), "")

        line = (f"{qinfo}[{state}]{rep} {ui.fmt_time(pos)}/{ui.fmt_time(dur)} | "
                f"🔊 {vol_str} [{bar}] {title[:26]}")
        sys.stdout.write("\r\033[K" + line)
        sys.stdout.flush()

    try:
        mpv.start(stream_url)
        mpv.set("volume", float(cfg.get("volume", 100)))
        print(ui.help_line(cfg))
        print()

        old = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        try:
            while mpv.alive:
                render()
                if select.select([sys.stdin], [], [], 0.25)[0]:
                    key = ui.read_key()
                    if key == "\x03":              # Ctrl+C — выход всегда
                        reason = "quit"
                        break
                    action = cfg.action_for(key)
                    vol = mpv.get("volume", 100)
                    if action == "volume_up":
                        mpv.set("volume", min(max_vol, vol + step))
                    elif action == "volume_down":
                        mpv.set("volume", max(0, vol - step))
                    elif action == "mute":
                        mpv.set("mute", not mpv.get("mute", False))
                    elif action == "pause":
                        mpv.cmd("cycle", "pause")
                    elif action == "seek_forward":
                        mpv.cmd("seek", seek_step)
                    elif action == "seek_back":
                        mpv.cmd("seek", -seek_step)
                    elif action == "repeat":
                        cfg.cycle_repeat()
                    elif action == "next_track":
                        reason = "next"
                        break
                    elif action == "prev_track":
                        reason = "prev"
                        break
                    elif action == "quit":
                        reason = "quit"
                        break
                    render()
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
            vol = mpv.get("volume")
            if vol is not None:
                cfg.data["volume"] = int(vol)
                cfg.save_config()
    except KeyboardInterrupt:
        reason = "quit"
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        reason = "quit"
    finally:
        ui.clear_line()
        mpv.stop()

    return reason
