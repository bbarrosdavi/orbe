#!/usr/bin/env python3
"""Controle do overlay de voz.

Uso: orb_control.py toggle|trigger|hide|quit|dismiss|hold|release

`hold` e `release` são para o próprio Jarvis chamar (skill voice-orb-hold):
`hold` desliga o timeout de inatividade, e a sessão passa a durar até uma
dispensa explícita; `release` devolve o timeout sem encerrar a sessão.
"""
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import orbe_config as vcfg  # noqa: E402

SOCK = vcfg.RUNTIME / "orbe.sock"
CMD = vcfg.RUNTIME / "orbe.cmd"


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
    """Sobe o serviço (systemd ou launchd) se ele não estiver rodando."""
    try:
        if vcfg.servico_estado() != "active":
            vcfg.servico_iniciar()
            time.sleep(0.5)
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
