#!/usr/bin/env python3
"""Despacho do orbe: roda um perfil do Hermes em segundo plano e devolve o
resultado ao daemon de voz, que faz o Jarvis relatar em voz.

Uso (o Jarvis chama pelo terminal):
  orbe_despacho.py <perfil> "<tarefa>"

Volta na hora: o trabalho segue desacoplado do turno de voz. Ao terminar, a
resposta final do perfil vai para o socket de controle do daemon como
``relato {json}``; a saída inteira fica em ~/.hermes/profiles/jarvis/despachos/.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERMES = str(Path.home() / ".local/bin/hermes")
PROFILES = Path.home() / ".hermes/profiles"
SAIDAS = PROFILES / "jarvis" / "despachos"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbe_config as vcfg  # noqa: E402

CTL_SOCK = str(vcfg.RUNTIME / "orbe-ctl.sock")
TETO_SEC = 2 * 3600
# O relato vira mensagem no chat do Jarvis; o resto fica no arquivo.
RELATO_MAX = 6000


def perfis() -> list[str]:
    return ["default"] + sorted(p.name for p in PROFILES.iterdir()
                                if p.is_dir() and not p.name.startswith(("_", ".")))


def relatar(rel: dict) -> None:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect(CTL_SOCK)
        s.sendall(("relato " + json.dumps(rel, ensure_ascii=False) + "\n").encode())
    finally:
        s.close()


def executar(perfil: str, tarefa: str) -> None:
    SAIDAS.mkdir(parents=True, exist_ok=True)
    arq = SAIDAS / f"{time.strftime('%Y%m%d_%H%M%S')}_{perfil}.md"
    argv = [HERMES] + ([] if perfil == "default" else ["-p", perfil]) + [
        "chat", "-q", tarefa, "--oneshot", "--yolo"]
    # Chamado de dentro do terminal do Jarvis, o ambiente traz o HERMES_HOME e
    # a sessão dele; herdado, o "default" rodaria o próprio Jarvis.
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("HERMES_") and any(p in k for p in ("HOME", "PROFILE", "SESSION")))}
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TETO_SEC,
                           stdin=subprocess.DEVNULL, cwd=str(Path.home()), env=env)
        saida = r.stdout.strip()
        if r.returncode != 0:
            saida = (saida + f"\n\n[falhou com código {r.returncode}]\n"
                     + r.stderr.strip()[-2000:]).strip()
    except subprocess.TimeoutExpired:
        saida = f"[cancelado: passou de {TETO_SEC // 60} minutos]"
    arq.write_text(f"# Despacho para {perfil}\n\n## Pedido\n\n{tarefa}\n\n"
                   f"## Resultado\n\n{saida}\n", encoding="utf-8")
    resultado = saida if len(saida) <= RELATO_MAX else (
        saida[:RELATO_MAX] + "\n\n[cortado; o resto está no arquivo]")
    relatar({"perfil": perfil, "tarefa": tarefa, "resultado": resultado,
             "arquivo": str(arq)})


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--executar":
        executar(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) != 3 or not sys.argv[2].strip():
        sys.exit('uso: orbe_despacho.py <perfil> "<tarefa>"')
    perfil, tarefa = sys.argv[1], sys.argv[2].strip()
    validos = perfis()
    if perfil not in validos:
        sys.exit(f"perfil inexistente: {perfil}. Perfis: {', '.join(validos)}")
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "--executar", perfil, tarefa],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    print(f"Despachado para {perfil}. O resultado volta por voz quando terminar.")


if __name__ == "__main__":
    main()
