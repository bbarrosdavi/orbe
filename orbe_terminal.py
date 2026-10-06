#!/usr/bin/env python3
"""Um agente de terminal (OpenCode, Gemini CLI ou Hermes) numa janela do PC,
ouvindo o orbe.

Roda o agente num pseudo-terminal, com a tela e o teclado da janela passando
direto, e se anuncia em $XDG_RUNTIME_DIR/orbe/terminais/<pid do
agente>.json (o agente, a pasta, o estado, o título), com um socket ao lado.
O daemon manda a fala por ele e espera a resposta:

- o pedido entra no chat como digitado: no OpenCode pela API da TUI dele
  (/tui/append-prompt e /tui/submit-prompt, com --port); no Gemini e no
  Hermes, colado no prompt com Enter, como o claude-orbe faz com o Claude
  (só com o prompt vazio e sem diálogo aberto);
- a resposta vem do que cada um oferece: os eventos da API do OpenCode
  (/event), os hooks do Gemini (SessionStart, BeforeAgent, BeforeTool e
  AfterAgent, no settings.json do usuário; fora de uma janela do orbe saem
  sem fazer nada) e o espelho de eventos da TUI do Hermes
  (HERMES_TUI_SIDECAR_URL, um WebSocket local).

Interromper só solta a espera: o agente segue o que estiver fazendo na janela.

    orbe_terminal.py opencode|gemini|hermes [--perfil P] [--retomar ID]
    orbe_terminal.py --hook             (o hook do Gemini: o evento no stdin)
    orbe_terminal.py --remover-gemini   (tira os hooks do settings do Gemini)
"""

from __future__ import annotations

import errno
import json
import os
import pty
import select
import shutil
import signal
import socket
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orbe_config as vcfg  # noqa: E402  (só stdlib)
from orbe_aceite import ANSI, Prompt, copiar_tamanho, escrever  # noqa: E402

TERMINAIS = vcfg.RUNTIME / "orbe" / "terminais"
AGENTES = ("opencode", "gemini", "hermes")
NOMES = {"opencode": "OpenCode", "gemini": "Gemini CLI", "hermes": "Hermes"}
HERMES_LAUNCHER = os.path.expanduser("~/.local/bin/hermes")
# o hook do Gemini acha o socket da janela por aqui (herdado do gemini)
VAR_SOCK = "ORBE_TERMINAL"

# Os hooks do Gemini ficam no settings.json do usuário: o settings de sistema
# por janela (GEMINI_CLI_SYSTEM_DEFAULTS_PATH) a 0.62 só aceita em pasta do
# root. O comando é fixo e só age numa janela do orbe, que põe as variáveis.
GEMINI_SETTINGS = Path.home() / ".gemini" / "settings.json"
EVENTOS_GEMINI = ("SessionStart", "BeforeAgent", "BeforeTool", "AfterAgent")
VAR_PY, VAR_SCRIPT = "ORBE_PY_TERMINAL", "ORBE_SCRIPT_TERMINAL"
GEMINI_HOOK = (f'[ -z "${VAR_SOCK}" ] || exec "${VAR_PY}" "${VAR_SCRIPT}" --hook')
PRONTO_MAX = 45.0       # quanto o pedido espera o agente subir
ALVO = 40               # as últimas letras do pedido colado, procuradas na tela


def _norm(t) -> str:
    return " ".join(str(t or "").split())


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _gemini_bin() -> str | None:
    """O gemini vem do npm sob o fnm, cujo PATH muda a cada shell."""
    import glob
    achados = sorted(glob.glob(os.path.expanduser("~/.local/share/fnm/node-versions/*/installation/bin/gemini")))
    return achados[-1] if achados else shutil.which("gemini")


def tela_crua(cru: bytes) -> bytes:
    """O texto da tela sem as sequências de controle (os espaços ficam)."""
    return ANSI.sub(b"", cru)


def _porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


# ── a janela: roda dentro do terminal ──────────────────────────────────────

class Janela:
    """O agente na janela e o pedido do orbe que ele está atendendo."""

    def __init__(self, agente: str, pasta: str):
        self.agente = agente
        self.pid = 0
        self.prompt: Prompt | None = None
        self.pronto = threading.Event()
        self.inicio = time.monotonic()
        self.saida_em = time.monotonic()
        self._trava = threading.Lock()
        self.pend: dict | None = None      # {"cli", "texto", "comecou", "sessao", "t"}
        self.subida = b""                   # a tela até o agente ficar pronto
        self.reg = {"agente": agente, "pid": 0, "wrapper": os.getpid(), "pasta": pasta,
                    "inicio": time.time(), "estado": "parada", "titulo": "", "sessao": ""}

    # o anúncio para o daemon e a ponte do relógio
    def gravar(self, **mudou):
        if mudou and all(self.reg.get(k) == v for k, v in mudou.items()):
            return
        self.reg.update(mudou)
        if not self.pid:
            return
        tmp = TERMINAIS / f".{self.pid}.json"
        try:
            tmp.write_text(json.dumps(self.reg, ensure_ascii=False))
            os.replace(tmp, TERMINAIS / f"{self.pid}.json")
        except OSError:
            pass

    def estado(self, trabalhando: bool):
        self.gravar(estado="trabalhando" if trabalhando else "parada")

    # o cliente do daemon: um pedido por vez
    @staticmethod
    def _mandar(cli, msg: dict):
        try:
            cli.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        except OSError:
            pass

    def avisar(self, msg: dict, so_comecado: bool = True):
        with self._trava:
            p = self.pend
            if p is None or (so_comecado and not p["comecou"]):
                return
            self._mandar(p["cli"], msg)

    def responder(self, texto: str):
        with self._trava:
            p, self.pend = self.pend, None
        if p is not None:
            self._mandar(p["cli"], {"tipo": "resposta", "texto": texto})

    def falhar(self, motivo: str):
        with self._trava:
            p, self.pend = self.pend, None
        if p is not None:
            self._mandar(p["cli"], {"tipo": "erro", "motivo": motivo})

    def soltar(self, cli):
        with self._trava:
            if self.pend is not None and self.pend["cli"] is cli:
                self.pend = None

    def pedir(self, cli, texto: str):
        """Põe a fala no chat do agente; "" se entrou."""
        if not self.pronto.wait(PRONTO_MAX):
            return f"o {NOMES[self.agente]} não ficou pronto na janela"
        with self._trava:
            antigo = self.pend
            self.pend = {"cli": cli, "texto": _norm(texto), "comecou": False, "sessao": "", "t": time.monotonic()}
        if antigo is not None and antigo["cli"] is not cli:
            self._mandar(antigo["cli"], {"tipo": "erro", "motivo": "outro pedido tomou o lugar"})
        motivo = self.entrar(_norm(texto))
        if motivo:
            self.soltar(cli)
        return motivo

    def entrar(self, texto: str) -> str:
        """Colado no prompt e com Enter (Gemini, Hermes)."""
        alvo = "".join(texto.split())[-ALVO:]
        motivo = self.prompt.colar(texto, alvo) if self.prompt is not None else "sem_terminal"
        return {"": "", "rascunho": "tem texto digitado no prompt da janela",
                "nao_apareceu": "a janela não mostrou o pedido no prompt (um diálogo aberto?)"}.get(motivo, motivo)

    # o que o agente roda, com o ambiente dele; antes do fork
    def comando(self, args) -> tuple[list[str], dict]:
        raise NotImplementedError

    def comecar(self):
        """Depois do fork: o que escuta o agente (eventos, WebSocket)."""

    def viu_saida(self, dados: bytes):
        self.saida_em = time.monotonic()
        if not self.pronto.is_set():
            self.subida = (self.subida + dados)[-65536:]

    def checar_pronto(self):
        """Sem sinal do agente (hook, evento), a tela calma depois da subida serve."""
        agora = time.monotonic()
        if agora - self.inicio > 20 and agora - self.saida_em > 1.0:
            self.pronto.set()

    def limpar(self):
        pass


class JanelaOpenCode(Janela):
    """A TUI do OpenCode com o servidor dela numa porta conhecida."""

    def comando(self, args):
        self.porta = _porta_livre()
        self.base = f"http://127.0.0.1:{self.porta}"
        self.tipos: dict[str, str] = {}      # partID → tipo da parte
        self.etapas: set[str] = set()        # as ferramentas já ditas
        argv = [shutil.which("opencode") or "opencode", "--port", str(self.porta)]
        if args.retomar:
            argv += ["--session", args.retomar]
        return argv, {}

    def checar_pronto(self):
        """O servidor sobe antes da TUI, e o que a API põe no prompt antes de ela
        desenhar se perde (medido: 1,25 s o servidor, e 5 s depois pegou): vale
        o prompt na tela, ou a tela calma."""
        if not getattr(self, "servidor", False):
            return
        agora = time.monotonic()
        if b"Askanything" in b"".join(tela_crua(self.subida).split()) or (agora - self.inicio > 6 and agora - self.saida_em > 1.0):
            threading.Timer(0.5, self.pronto.set).start()
            self.servidor = False

    def _http(self, metodo: str, caminho: str, corpo=None, espera: float = 5.0):
        dados = None if corpo is None else json.dumps(corpo).encode()
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo,
                                     headers={"Content-Type": "application/json"} if dados else {})
        with urllib.request.urlopen(req, timeout=espera) as r:
            bruto = r.read()
        return json.loads(bruto) if bruto else None

    def comecar(self):
        threading.Thread(target=self._eventos, name="eventos", daemon=True).start()

    def _eventos(self):
        """O /event em SSE, de novo a cada queda, enquanto o OpenCode vive. O
        pedido feito logo que a porta abre fica sem resposta para sempre
        (medido: na subida, sim; 6 s depois, responde na hora): por isso o
        prazo para os cabeçalhos."""
        import http.client
        while _vivo(self.pid):
            try:
                c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=4)
                c.request("GET", "/event", headers={"Accept": "text/event-stream"})
                r = c.getresponse()
                if r.status != 200:
                    raise OSError(r.status)
                if c.sock is not None:
                    c.sock.settimeout(None)
                self.servidor = True
                for bruto in r:
                    linha = bruto.decode("utf-8", "replace").strip()
                    if linha.startswith("data:"):
                        try:
                            self._evento(json.loads(linha[5:]))
                        except (ValueError, KeyError, TypeError):
                            pass
            except OSError:
                pass
            time.sleep(0.5)

    def _evento(self, e: dict):
        tipo, p = e.get("type", ""), e.get("properties") or {}
        sid = p.get("sessionID") or ""
        if tipo == "session.status":
            ocupada = (p.get("status") or {}).get("type") != "idle"
            self._status(sid, ocupada)
        elif tipo == "session.idle":
            self._status(sid, False)
        elif tipo == "session.updated":
            info = p.get("info") or {}
            if info.get("id") and info.get("id") == self.reg.get("sessao"):
                self.gravar(titulo=str(info.get("title") or ""))
        elif tipo == "message.part.updated":
            parte = p.get("part") or {}
            self.tipos[parte.get("id", "")] = parte.get("type", "")
            if parte.get("type") == "tool" and self._nossa(parte.get("sessionID", "")):
                st = parte.get("state") or {}
                self.avisar({"tipo": "ferramenta", "nome": parte.get("tool", ""), "estado": st.get("status", "")})
                titulo, pid = _norm(st.get("title")), str(parte.get("id") or "")
                if titulo and pid not in self.etapas:
                    self.etapas.add(pid)
                    self.avisar({"tipo": "etapa", "texto": titulo})
        elif tipo == "message.part.delta":
            if self.tipos.get(p.get("partID", "")) == "reasoning" and self._nossa(sid):
                self.avisar({"tipo": "pensamento", "texto": p.get("delta", "")})

    def _nossa(self, sid: str) -> bool:
        p = self.pend
        return p is not None and p["comecou"] and p["sessao"] == sid

    def _status(self, sid: str, ocupada: bool):
        if ocupada:
            self.gravar(sessao=sid)
        self.estado(ocupada)
        p = self.pend
        if p is None:
            return
        if ocupada and not p["comecou"]:
            # a primeira sessão que pega trabalho depois do envio é a do pedido
            p["comecou"], p["sessao"] = True, sid
            self.avisar({"tipo": "pensando"})
        elif not ocupada and p["comecou"] and p["sessao"] == sid:
            texto = self._resposta(sid, p["texto"])
            if texto is not None:
                self.responder(texto)

    def _resposta(self, sid: str, pedido: str) -> str | None:
        """A última fala do OpenCode depois do pedido; None se o pedido ainda
        não entrou (estava na fila de um turno digitado)."""
        try:
            msgs = self._http("GET", f"/session/{sid}/message") or []
        except (OSError, ValueError):
            return None
        def texto(m):
            return _norm(" ".join(pt.get("text", "") for pt in m.get("parts") or []
                                  if pt.get("type") == "text" and not pt.get("synthetic")))
        meu = next((i for i in range(len(msgs) - 1, -1, -1)
                    if (msgs[i].get("info") or {}).get("role") == "user" and texto(msgs[i]) == pedido), None)
        if meu is None:
            return None
        falas = [m for m in msgs[meu + 1:] if (m.get("info") or {}).get("role") == "assistant"]
        if not falas:
            return None
        fim = falas[-1]
        erro = (fim.get("info") or {}).get("error") or {}
        return texto(fim) or _norm((erro.get("data") or {}).get("message") or erro.get("name") or "")

    def entrar(self, texto: str) -> str:
        try:
            self._http("POST", "/tui/append-prompt", {"text": texto})
            self._http("POST", "/tui/submit-prompt", {})
        except (OSError, ValueError) as e:
            return f"a API do OpenCode não respondeu ({e})"
        return ""


class JanelaGemini(Janela):
    """O Gemini CLI, com os hooks do orbe no settings.json do usuário
    (instalados na primeira janela). Os hooks só rodam em pasta que o Gemini
    confia (a home e o que está abaixo dela, no trustedFolders.json do Davi)."""

    def comando(self, args):
        exe = _gemini_bin()
        if not exe:
            raise SystemExit("gemini não encontrado")
        instalar_gemini()
        env = {"PATH": os.path.dirname(exe) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
               VAR_PY: sys.executable, VAR_SCRIPT: str(Path(__file__).resolve())}
        argv = [exe] + (["--resume", args.retomar] if args.retomar else [])
        return argv, env

    hooks = False

    def pedir(self, cli, texto: str):
        # O Gemini (desde a 0.62) só roda hooks em pasta confiada: sem eles a
        # resposta nunca chegaria, e a janela pronta sem o SessionStart diz isso
        if self.pronto.wait(PRONTO_MAX) and not self.hooks:
            return "o Gemini não confia nesta pasta e não roda os hooks do orbe (confie nela no Gemini)"
        return super().pedir(cli, texto)

    def hook(self, ev: dict):
        nome = ev.get("hook_event_name", "")
        p = self.pend
        if nome == "SessionStart":
            self.hooks = True
            self.gravar(sessao=str(ev.get("session_id") or ""))
            threading.Timer(0.8, self.pronto.set).start()
        elif nome == "BeforeAgent":
            self.estado(True)
            if p is not None and not p["comecou"] and _norm(ev.get("prompt")) == p["texto"]:
                p["comecou"] = True
                self.avisar({"tipo": "pensando"})
        elif nome == "BeforeTool":
            entrada = ev.get("tool_input") or {}
            self.avisar({"tipo": "ferramenta", "nome": ev.get("tool_name", ""), "estado": "pending"})
            desc = _norm(entrada.get("description")) if isinstance(entrada, dict) else ""
            if desc:
                self.avisar({"tipo": "etapa", "texto": desc})
        elif nome == "AfterAgent":
            self.estado(False)
            if p is not None and (p["comecou"] or _norm(ev.get("prompt")) == p["texto"]):
                self.responder(str(ev.get("prompt_response") or ""))


class JanelaHermes(Janela):
    """A TUI do Hermes, com o espelho dos eventos dela num WebSocket local."""

    def comando(self, args):
        from websockets.sync.server import serve
        self.srv = serve(self._ws, "127.0.0.1", 0)
        porta = self.srv.socket.getsockname()[1]
        threading.Thread(target=self.srv.serve_forever, name="espelho", daemon=True).start()
        perfil = (args.perfil or "").strip()
        argv = [HERMES_LAUNCHER] + (["-p", perfil] if perfil and perfil != "default" else []) + ["--tui"]
        if args.retomar:
            argv += ["--resume", args.retomar]
        return argv, {"HERMES_TUI_SIDECAR_URL": f"ws://127.0.0.1:{porta}/"}

    def _ws(self, ws):
        for msg in ws:
            for linha in (msg if isinstance(msg, str) else msg.decode("utf-8", "replace")).splitlines():
                try:
                    self._evento(json.loads(linha))
                except (ValueError, TypeError, AttributeError):
                    pass

    def _evento(self, f: dict):
        prm = f.get("params") or {}
        tipo = prm.get("type") or prm.get("event") or ""
        dado = prm.get("payload") or {}
        if not isinstance(dado, dict):
            dado = {}
        p = self.pend
        if tipo == "gateway.ready":
            threading.Timer(0.8, self.pronto.set).start()
        elif tipo == "session.info":
            # o id do gateway (session_id) é curto e não serve ao --resume
            mudou = {"sessao": str(dado.get("stored_session_id") or "")}
            if _norm(dado.get("title")):
                mudou["titulo"] = _norm(dado.get("title"))
            if mudou["sessao"] and mudou["sessao"] != self.reg.get("sessao"):
                self.gravar(**mudou)
        elif tipo == "message.start":
            self.estado(True)
            if p is not None and not p["comecou"] and p.get("colado"):
                p["comecou"] = True
                self.avisar({"tipo": "pensando"})
        elif tipo in ("reasoning.delta", "thinking.delta"):
            self.avisar({"tipo": "pensamento", "texto": str(dado.get("text") or "")})
        elif tipo == "tool.start":
            self.avisar({"tipo": "ferramenta", "nome": str(dado.get("name") or ""), "estado": "pending"})
            ctx = _norm(dado.get("context"))
            if ctx:
                self.avisar({"tipo": "etapa", "texto": ctx})
        elif tipo == "message.complete":
            self.estado(False)
            if p is not None and p["comecou"]:
                t = dado.get("text")
                self.responder(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False))
        elif tipo == "session.title":
            self.gravar(titulo=_norm(dado.get("title")))

    def entrar(self, texto: str) -> str:
        motivo = super().entrar(texto)
        if not motivo and self.pend is not None:
            self.pend["colado"] = True
        return motivo

    def limpar(self):
        try:
            self.srv.shutdown()
        except Exception:
            pass


CLASSES = {"opencode": JanelaOpenCode, "gemini": JanelaGemini, "hermes": JanelaHermes}


def servir(janela: Janela) -> Path:
    """O socket da janela: o daemon pergunta, o hook do Gemini conta."""
    caminho = TERMINAIS / f"{janela.pid}.sock"
    caminho.unlink(missing_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(caminho))
    os.chmod(caminho, 0o600)
    srv.listen(4)

    def cliente(cli):
        buf = b""
        try:
            while True:
                bloco = cli.recv(65536)
                if not bloco:
                    break
                buf += bloco
                while b"\n" in buf:
                    linha, buf = buf.split(b"\n", 1)
                    try:
                        m = json.loads(linha)
                    except ValueError:
                        continue
                    tipo = m.get("tipo")
                    if tipo == "pergunta":
                        motivo = janela.pedir(cli, str(m.get("texto") or ""))
                        Janela._mandar(cli, {"tipo": "erro", "motivo": motivo} if motivo else {"tipo": "aceito"})
                    elif tipo == "cancelar":
                        janela.soltar(cli)
                    elif tipo == "hook" and isinstance(janela, JanelaGemini):
                        janela.hook(m.get("evento") or {})
        except OSError:
            pass
        finally:
            janela.soltar(cli)
            cli.close()

    def laco():
        while True:
            try:
                cli, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=cliente, args=(cli,), daemon=True).start()

    threading.Thread(target=laco, name="socket", daemon=True).start()
    return caminho


def rodar(agente: str, args) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("orbe_terminal.py roda numa janela de terminal", file=sys.stderr)
        return 2
    TERMINAIS.mkdir(parents=True, exist_ok=True, mode=0o700)
    janela = CLASSES[agente](agente, os.getcwd())
    argv, extra = janela.comando(args)
    pid, fd = pty.fork()
    if pid == 0:
        try:
            env = dict(os.environ, **extra)
            env[VAR_SOCK] = str(TERMINAIS / f"{os.getpid()}.sock")
            os.execvpe(argv[0], argv, env)
        finally:
            os._exit(127)

    janela.pid = pid
    janela.reg["pid"] = pid
    janela.prompt = Prompt(fd)
    sock = servir(janela)
    janela.gravar()
    janela.comecar()
    copiar_tamanho(fd)
    signal.signal(signal.SIGWINCH, lambda *_: copiar_tamanho(fd))
    # fechar a janela (SIGHUP) ou o encerrar do daemon fecham o agente e os
    # filhos dele (o gemini se relança num node filho): o grupo todo
    for sinal in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sinal, lambda *_: _sinalizar(pid, signal.SIGTERM))
    antigo = termios.tcgetattr(0)
    tty.setraw(0)
    try:
        entradas = [fd, 0]
        while True:
            try:
                prontos, _, _ = select.select(entradas, [], [], 1.0 if janela.pronto.is_set() else 0.25)
            except InterruptedError:
                continue
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
                janela.prompt.viu(dados)
                janela.viu_saida(dados)
            if 0 in prontos:
                dados = os.read(0, 65536)
                if dados:
                    with janela.prompt.trava:
                        janela.prompt.teclas(dados)
                        escrever(fd, dados)
                else:
                    entradas.remove(0)
            if not janela.pronto.is_set():
                janela.checar_pronto()
    finally:
        termios.tcsetattr(0, termios.TCSAFLUSH, antigo)
        for p in (sock, TERMINAIS / f"{pid}.json"):
            p.unlink(missing_ok=True)
        janela.limpar()
        janela.falhar(f"a janela do {NOMES[agente]} fechou")
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def hook() -> int:
    """O hook do Gemini: leva o evento à janela e sai logo, sem decidir nada."""
    try:
        ev = json.loads(sys.stdin.read() or "{}")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(os.environ[VAR_SOCK])
        s.sendall((json.dumps({"tipo": "hook", "evento": ev}, ensure_ascii=False) + "\n").encode())
        s.close()
    except (OSError, ValueError, KeyError):
        pass
    return 0


def _hooks_gemini(d: dict, com_o_orbe: bool) -> bool:
    """Tira (e, se [com_o_orbe], repõe) a entrada do orbe em cada evento do
    settings do Gemini; True se mudou algo."""
    antes = json.dumps(d, sort_keys=True)
    hooks = d.setdefault("hooks", {})
    for ev in EVENTOS_GEMINI:
        grupos = []
        for g in hooks.get(ev) or []:
            if isinstance(g, dict):
                # pelo nome, que também pega a entrada de antes da troca de nome
                # (o comando com as variáveis HERMES_ORBE_*)
                hs = [h for h in g.get("hooks") or []
                      if (h or {}).get("command") != GEMINI_HOOK and (h or {}).get("name") != "orbe"]
                if not hs and g.get("hooks"):
                    continue
                g = dict(g, hooks=hs)
            grupos.append(g)
        if com_o_orbe:
            grupos.append({"hooks": [{"type": "command", "name": "orbe", "command": GEMINI_HOOK, "timeout": 5000}]})
        if grupos:
            hooks[ev] = grupos
        else:
            hooks.pop(ev, None)
    if not hooks:
        d.pop("hooks")
    return json.dumps(d, sort_keys=True) != antes


def _settings_gemini(com_o_orbe: bool) -> bool:
    try:
        d = json.loads(GEMINI_SETTINGS.read_text())
    except FileNotFoundError:
        d = {}
    instalado = all(any(h.get("command") == GEMINI_HOOK for g in (d.get("hooks") or {}).get(ev) or []
                        if isinstance(g, dict) for h in g.get("hooks") or [] if isinstance(h, dict))
                    for ev in EVENTOS_GEMINI)
    if instalado == com_o_orbe or not _hooks_gemini(d, com_o_orbe):
        return False
    if GEMINI_SETTINGS.exists():
        GEMINI_SETTINGS.with_name("settings.json.orbe-bak").write_bytes(GEMINI_SETTINGS.read_bytes())
    GEMINI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = GEMINI_SETTINGS.with_name("settings.json.orbe-tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, GEMINI_SETTINGS)
    return True


def instalar_gemini() -> bool:
    """Os hooks do orbe no settings.json do Gemini, se ainda não estão."""
    return _settings_gemini(True)


def remover_gemini() -> bool:
    return _settings_gemini(False)


# ── o daemon: abre janelas e fala com elas ─────────────────────────────────

def sessoes(agente: str = "") -> list[dict]:
    """As janelas vivas (do [agente], ou todas), a mais nova primeiro."""
    vivas = []
    for p in TERMINAIS.glob("[0-9]*.json"):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not _vivo(int(d.get("pid") or 0)):
            if not _vivo(int(d.get("wrapper") or 0)):
                p.unlink(missing_ok=True)
            continue
        if not agente or d.get("agente") == agente:
            vivas.append(d)
    return sorted(vivas, key=lambda d: d.get("inicio", 0), reverse=True)


def abrir(agente: str, pasta: str, terminal: str = "ghostty", perfil: str = "",
          retomar: str = "", espera: float = 30.0) -> int:
    """Abre uma janela do [agente] no PC e devolve o pid dele (0 se não abriu)."""
    antes = {d["pid"] for d in sessoes(agente)}
    cmd = [sys.executable, str(Path(__file__).resolve()), agente]
    if perfil:
        cmd += ["--perfil", perfil]
    if retomar:
        cmd += ["--retomar", retomar]
    argv = [terminal or "ghostty", "-e", *cmd]
    # num escopo próprio: reiniciar o serviço do orbe não fecha a janela
    if shutil.which("systemd-run"):
        argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--", *argv]
    try:
        subprocess.Popen(argv, cwd=pasta, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return 0
    fim = time.monotonic() + espera
    while time.monotonic() < fim:
        novas = [d["pid"] for d in sessoes(agente) if d["pid"] not in antes]
        if novas:
            return int(novas[0])
        time.sleep(0.2)
    return 0


def _sinalizar(pid: int, sinal) -> bool:
    """O agente roda numa sessão própria (pty.fork): o sinal vai ao grupo todo."""
    try:
        os.killpg(pid, sinal)
    except OSError:
        try:
            os.kill(pid, sinal)
        except OSError:
            return False
    return True


def encerrar(pid: int) -> bool:
    """Fecha o agente da janela (e com ele a janela); o que não sair em 3 s, à força."""
    if not any(d["pid"] == pid for d in sessoes()):
        return False
    if not _sinalizar(pid, signal.SIGTERM):
        return False

    def _forcar():
        fim = time.monotonic() + 3
        while time.monotonic() < fim and _vivo(pid):
            time.sleep(0.2)
        if _vivo(pid):
            _sinalizar(pid, signal.SIGKILL)
    threading.Thread(target=_forcar, daemon=True).start()
    return True


class AgenteTerminal:
    """Fala com o agente de uma janela pelo socket dela; a mesma cara do AgenteACP."""

    def __init__(self, pid: int):
        import orbe_acp as acp
        self._erro = acp.ErroACP
        self.alvo = int(pid)
        d = next((d for d in sessoes() if d["pid"] == self.alvo), {})
        self.tipo = d.get("agente", "")
        nome = NOMES.get(self.tipo, self.tipo)
        self.iniciado_em = time.time()
        self.sessao = ""
        self.info: dict = {"agentInfo": {"name": nome, "title": nome}}
        self.modelos: list = []
        self.modelo_atual = ""
        self.cwd = d.get("pasta", "")

    def iniciar(self, teto: float = 0):
        pass

    def abrir_sessao(self, retomar=None, teto: float = 0):
        if not any(d["pid"] == self.alvo for d in sessoes()):
            raise self._erro(f"a janela {self.alvo} fechou")
        self.sessao = str(self.alvo)
        return self.sessao

    def vivo(self) -> bool:
        return bool(self.sessao) and _vivo(self.alvo)

    def definir_modelo(self, modelo: str):
        """O modelo é o que a janela usa; o escolhido no app vale só por ACP."""

    def fechar(self):
        pass

    def cancelar(self):
        pass

    def erro_recente(self) -> str:
        return ""

    def perguntar(self, texto, ao_texto, ao_pensamento=None, a_ferramenta=None,
                  parar=None, teto: float = 600.0, a_etapa=None) -> str:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(str(TERMINAIS / f"{self.alvo}.sock"))
        except OSError as e:
            s.close()
            raise self._erro(f"a janela {self.alvo} não atende: {e}")
        s.settimeout(0.2)
        fim = time.monotonic() + teto
        buf = b""
        try:
            s.sendall((json.dumps({"tipo": "pergunta", "texto": texto}, ensure_ascii=False) + "\n").encode())
            while True:
                if parar is not None and parar.is_set():
                    s.sendall(b'{"tipo": "cancelar"}\n')
                    return "cancelled"
                if time.monotonic() > fim:
                    s.sendall(b'{"tipo": "cancelar"}\n')
                    raise self._erro(f"sem resposta da janela em {teto:.0f} s")
                try:
                    bloco = s.recv(65536)
                except socket.timeout:
                    continue
                if not bloco:
                    raise self._erro("a janela fechou")
                buf += bloco
                while b"\n" in buf:
                    linha, buf = buf.split(b"\n", 1)
                    try:
                        m = json.loads(linha)
                    except ValueError:
                        continue
                    tipo = m.get("tipo")
                    if tipo == "erro":
                        raise self._erro(str(m.get("motivo") or "a janela recusou o pedido"))
                    if tipo == "aceito" and a_ferramenta:
                        a_ferramenta(self.tipo, "pending")
                    elif tipo == "pensamento" and ao_pensamento and m.get("texto"):
                        ao_pensamento(str(m["texto"]))
                    elif tipo == "ferramenta" and a_ferramenta:
                        a_ferramenta(str(m.get("nome") or ""), str(m.get("estado") or ""))
                    elif tipo == "etapa" and a_etapa and m.get("texto"):
                        a_etapa(str(m["texto"]))
                    elif tipo == "resposta":
                        ao_texto(str(m.get("texto") or ""))
                        return "end_turn"
        except OSError as e:
            raise self._erro(f"a janela {self.alvo} caiu: {e}")
        finally:
            s.close()


def main(argv: list[str]) -> int:
    if argv[:1] == ["--hook"]:
        return hook()
    if argv[:1] == ["--remover-gemini"]:
        print(f"hooks do orbe {'removidos de' if remover_gemini() else 'já não estavam em'} {GEMINI_SETTINGS}")
        return 0
    import argparse
    ap = argparse.ArgumentParser(description="Um agente de terminal ouvindo o orbe")
    ap.add_argument("agente", choices=AGENTES)
    ap.add_argument("--perfil", default="")
    ap.add_argument("--retomar", default="")
    args = ap.parse_args(argv)
    return rodar(args.agente, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
