#!/usr/bin/env python3
"""Claude Code num pseudo-terminal do orbe, que confirma sozinho o aviso dos
canais de desenvolvimento.

O canal do orbe (server:orbe) entra pelo --dangerously-load-development-channels,
e o Claude pergunta a cada abertura se é para desenvolvimento local; na conta
Max não há lista própria de canais aprovados que dispense a pergunta. Quem abre
a sessão é o orbe (o atalho ou o relógio), e a janela pode nem estar em foco:
o Enter vai direto na entrada deste processo, nunca pelo teclado do sistema.

Só responde a esse aviso, reconhecido pelo texto e com a primeira opção ("I am
using this for local development") marcada, nos primeiros [PRAZO] segundos da
sessão: um Enter e, se a tela não reagir, mais um. Qualquer outra tela (o aviso
do modo bypass, que tem "No, exit" marcado) passa intacta, nos dois sentidos.

    hermes_voice_aceite.py claude [argumentos do claude...]
"""

import errno
import fcntl
import os
import pty
import re
import select
import signal
import sys
import termios
import time
import tty

# a tela do Claude sem cores nem movimentos de cursor, e sem espaços (o Ink às
# vezes avança o cursor em vez de escrever o espaço)
AVISO = "Loadingdevelopmentchannels"
OPCAO = "❯1.Iamusingthisforlocaldevelopment"
ANSI = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[PX^_][^\x1b]*\x1b\\|[@-Z\\-_])")
PRAZO = 60.0        # o aviso vem logo na abertura
CALMA = 0.25        # a tela parou de desenhar: a lista já aceita o Enter
REACAO = 1.5        # sem nada novo na tela depois do Enter, ele não pegou
TENTATIVAS = 2


def escrever(fd: int, dados: bytes) -> None:
    while dados:
        n = os.write(fd, dados)
        dados = dados[n:]


def copiar_tamanho(fd: int) -> None:
    try:
        ws = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, ws)
    except OSError:
        pass


def tela(cru: bytes) -> str:
    return "".join(ANSI.sub(b"", cru).decode("utf-8", "replace").split())


def main(argv: list[str]) -> int:
    if not argv:
        print("uso: hermes_voice_aceite.py claude [args...]", file=sys.stderr)
        return 2
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        os.execvp(argv[0], argv)

    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvp(argv[0], argv)
        finally:
            os._exit(127)

    copiar_tamanho(fd)
    signal.signal(signal.SIGWINCH, lambda *_: copiar_tamanho(fd))
    antigo = termios.tcgetattr(0)
    tty.setraw(0)
    try:
        prazo = time.monotonic() + PRAZO
        cru = b""                   # o fim do que o Claude desenhou, enquanto vale procurar
        visto = None                # o aviso está na tela desde então
        enviados = 0
        enviado_em = 0.0
        saida_em = time.monotonic()
        entradas = [fd, 0]
        while True:
            vigiando = enviados < TENTATIVAS and time.monotonic() < prazo
            espera = CALMA if vigiando and visto is not None else None
            try:
                prontos, _, _ = select.select(entradas, [], [], espera)
            except InterruptedError:
                continue
            agora = time.monotonic()
            if fd in prontos:
                try:
                    dados = os.read(fd, 65536)
                except OSError as e:
                    if e.errno != errno.EIO:
                        raise
                    dados = b""
                if not dados:
                    break
                escrever(1, dados)
                saida_em = agora
                if vigiando:
                    cru = (cru + dados)[-32768:]
                    if enviados and agora - enviado_em < REACAO:
                        # a tela mudou depois do Enter: o aviso foi embora
                        visto = None
                        enviados = TENTATIVAS
                    elif visto is None:
                        t = tela(cru)
                        if AVISO in t and OPCAO in t:
                            visto = agora
            if 0 in prontos:
                dados = os.read(0, 65536)
                if dados:
                    escrever(fd, dados)
                else:
                    entradas.remove(0)
            if vigiando and visto is not None:
                calmo = agora - saida_em >= CALMA
                sem_reacao = enviados == 0 or agora - enviado_em >= REACAO
                if calmo and sem_reacao:
                    escrever(fd, b"\r")
                    enviados += 1
                    enviado_em = agora
                    cru = b""
    finally:
        termios.tcsetattr(0, termios.TCSAFLUSH, antigo)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
