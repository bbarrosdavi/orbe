#!/usr/bin/python3
"""Controle do overlay de voz.

Uso: orb_control.py toggle|trigger|hide|quit|dismiss|hold|release

`hold` e `release` são para o próprio Jarvis chamar (skill voice-orb-hold):
`hold` desliga o timeout de inatividade, e a sessão passa a durar até uma
dispensa explícita; `release` devolve o timeout sem encerrar a sessão.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

SOCK = Path(f"/run/user/{os.getuid()}/hermes-voice-orb.sock")
CMD = Path(f"/run/user/{os.getuid()}/hermes-voice.cmd")


def sock(msg: str):
    if not SOCK.exists():
        return
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        s.connect(str(SOCK))
        s.sendall((msg.strip() + "\n").encode())
    except OSError:
        pass
    finally:
        s.close()


def ensure_daemon():
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "hermes-voice.service"],
            timeout=1,
        )
        if r.returncode != 0:
            subprocess.run(
                ["systemctl", "--user", "start", "hermes-voice.service"],
                timeout=3,
            )
            time.sleep(0.3)
    except Exception:
        pass


def main():
    op = (sys.argv[1] if len(sys.argv) > 1 else "toggle").lower()
    if op in ("hide", "quit"):
        sock(op)
        return
    if op in ("dismiss", "stop", "tchau"):
        CMD.write_text("dismiss\n")
        sock("hide")
        return
    if op in ("hold", "segura", "keep"):
        CMD.write_text("hold\n")
        return
    if op in ("release", "solta", "unhold"):
        CMD.write_text("release\n")
        return
    if op in ("toggle", "trigger", "wake", "start"):
        ensure_daemon()
        CMD.write_text(f"{op}\n")
        return
    print("uso: orb_control.py toggle|trigger|hide|quit|dismiss|hold|release", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
