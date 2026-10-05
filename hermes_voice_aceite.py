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

Também cola no prompt o pedido de voz que o canal do orbe manda (socket em
$XDG_RUNTIME_DIR/hermes-voice/terminais/<pid do claude>.sock): assim a fala
aparece inteira no chat, como digitada; a mensagem de canal o Claude Code
desenha cortada em 60 caracteres. Só cola com o prompt vazio (nada digitado
desde o último Enter), em pedaços abaixo do limite em que o Claude Code troca
a colagem por "[Pasted text #n]", e só aperta o Enter depois de ver o texto na
tela: um diálogo aberto (uma permissão, uma lista) não recebe o Enter. Sem
isso, o canal manda o pedido como mensagem de canal.

    hermes_voice_aceite.py claude [argumentos do claude...]
"""

import errno
import fcntl
import json
import os
import pty
import re
import select
import signal
import socket
import sys
import termios
import threading
import time
import tty
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hermes_voice_config as vcfg  # noqa: E402  (só stdlib)

# a tela do Claude sem cores nem movimentos de cursor, e sem espaços (o Ink às
# vezes avança o cursor em vez de escrever o espaço)
AVISO = "Loadingdevelopmentchannels"
OPCAO = "❯1.Iamusingthisforlocaldevelopment"
ANSI = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[PX^_][^\x1b]*\x1b\\|[@-Z\\-_])")
PRAZO = 60.0        # o aviso vem logo na abertura
CALMA = 0.25        # a tela parou de desenhar: a lista já aceita o Enter
REACAO = 1.5        # sem nada novo na tela depois do Enter, ele não pegou
TENTATIVAS = 2

TERMINAIS = vcfg.RUNTIME / "hermes-voice" / "terminais"
PEDACO = 700        # o Claude Code troca colagem de mais de 800 caracteres por "[Pasted text #n]"
APARECER = 2.0      # quanto o texto colado tem para aparecer na tela antes do Enter


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


def achou(t: str, alvo: str) -> bool:
    """[alvo] em [t] com até um quinto das letras faltando: o Claude Code só
    redesenha as células que mudaram, e a letra que já estava naquela célula
    não vem de novo (medido: o código do pedido veio com 7 das 8 letras)."""
    folga = len(alvo) // 5
    for i in range(len(t)):
        k = alvo.find(t[i], 0, folga + 1)
        if k < 0:
            continue
        faltam, j = k, i + 1
        k += 1
        while k < len(alvo) and j < len(t):
            achado = alvo.find(t[j], k, k + folga - faltam + 1)
            if achado < 0:
                break
            faltam += achado - k
            k, j = achado + 1, j + 1
        if faltam + len(alvo) - k <= folga:
            return True
    return False


class Prompt:
    """O que o usuário tem no prompt e o que a tela mostrou, para colar o
    pedido do orbe sem misturar com um rascunho e sem Enter num diálogo."""

    def __init__(self, fd: int):
        self.fd = fd
        self.trava = threading.Lock()       # as escritas no terminal do Claude
        self.rascunho = False
        self._esc = 0                       # 0 fora de sequência; 1 depois do ESC; 2 dentro do CSI
        self._colando = False               # o usuário colando (o colado é rascunho)
        self.saida = b""
        self.vigiando = False

    def teclas(self, dados: bytes):
        """Acompanha o que o usuário digita: texto e as setas do histórico viram
        rascunho; Enter, Ctrl+C e Ctrl+U o limpam. As outras sequências de escape
        (a rolagem, o mouse, o foco) não contam."""
        for b in dados:
            if self._esc == 1:
                self._esc = 2 if b in (0x5B, 0x4F) else 0       # CSI ou SS3; ESC solto
                continue
            if self._esc == 2:
                if 0x40 <= b <= 0x7E:
                    self._esc = 0
                    if b == 0x7E:                               # ESC[200~ e ESC[201~: colagem
                        self._colando = not self._colando
                        if not self._colando:
                            self.rascunho = True
                    elif b in (0x41, 0x42):                     # seta para cima ou baixo: o histórico
                        self.rascunho = True
                continue
            if b == 0x1B:
                self._esc = 1
            elif b in (0x0D, 0x03, 0x15):
                self.rascunho = False
            elif b >= 0x20 and b != 0x7F:
                self.rascunho = True

    def viu(self, dados: bytes):
        if self.vigiando:
            self.saida = (self.saida + dados)[-65536:]

    def colar(self, texto: str, alvo: str) -> str:
        """Cola [texto] e dá Enter quando [alvo] aparece na tela; "" se foi."""
        if self.rascunho:
            return "rascunho"
        self.saida, self.vigiando = b"", True
        try:
            with self.trava:
                for i in range(0, len(texto), PEDACO):
                    escrever(self.fd, b"\x1b[200~" + texto[i:i + PEDACO].encode() + b"\x1b[201~")
                    time.sleep(0.03)
            fim = time.monotonic() + APARECER
            while not achou(tela(self.saida), alvo):
                if time.monotonic() > fim:
                    return "nao_apareceu"
                time.sleep(0.1)
            time.sleep(0.1)
            with self.trava:
                if self.rascunho:
                    return "rascunho"
                escrever(self.fd, b"\r")
            return ""
        finally:
            self.vigiando = False


def servir(prompt: Prompt, pid: int):
    """O socket do canal: {"tipo": "colar", "texto", "alvo"} -> {"ok", "motivo"}."""
    try:
        TERMINAIS.mkdir(parents=True, exist_ok=True, mode=0o700)
        caminho = TERMINAIS / f"{pid}.sock"
        caminho.unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(caminho))
        os.chmod(caminho, 0o600)
        srv.listen(2)
    except OSError:
        return None

    def laco():
        while True:
            try:
                cli, _ = srv.accept()
            except OSError:
                return
            with cli:
                try:
                    cli.settimeout(5)
                    m = json.loads(cli.makefile("rb").readline() or b"{}")
                    motivo = "?"
                    if m.get("tipo") == "colar" and m.get("texto") and m.get("alvo"):
                        motivo = prompt.colar(str(m["texto"]), "".join(str(m["alvo"]).split()))
                    cli.sendall((json.dumps({"ok": motivo == "", "motivo": motivo}) + "\n").encode())
                except (OSError, ValueError):
                    pass

    threading.Thread(target=laco, name="colar", daemon=True).start()
    return caminho


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
    prompt = Prompt(fd)
    sock = servir(prompt, pid)
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
                prompt.viu(dados)
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
                    with prompt.trava:
                        prompt.teclas(dados)
                        escrever(fd, dados)
                else:
                    entradas.remove(0)
            if vigiando and visto is not None:
                calmo = agora - saida_em >= CALMA
                sem_reacao = enviados == 0 or agora - enviado_em >= REACAO
                if calmo and sem_reacao:
                    with prompt.trava:
                        escrever(fd, b"\r")
                    enviados += 1
                    enviado_em = agora
                    cru = b""
    finally:
        termios.tcsetattr(0, termios.TCSAFLUSH, antigo)
        if sock is not None:
            sock.unlink(missing_ok=True)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
