#!/usr/bin/python3
"""Canal do orbe para uma sessão aberta do Claude Code.

Dois papéis no mesmo arquivo, só com a stdlib:

- Rodado pelo Claude (MCP stdio, via `claude-orbe`): declara o canal
  `claude/channel`, abre um socket local por sessão e empurra cada pergunta do
  orbe como `notifications/claude/channel`. O Claude responde pela ferramenta
  `reply`, que devolve o texto a quem perguntou.
- Importado pelo daemon: `AgenteClaude` tem a mesma cara do `AgenteACP` e fala
  com o socket da sessão aberta mais recente.

O canal só existe nas sessões abertas com a flag de desenvolvimento de canais
(prévia de pesquisa); sem ela o Claude descarta as notificações em silêncio.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import signal
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path


def _pasta() -> Path:
    """Onde as sessões se anunciam: o runtime do usuário (no Windows, o perfil local)."""
    rt = os.environ.get("XDG_RUNTIME_DIR")
    if not rt and hasattr(os, "getuid"):
        rt = f"/run/user/{os.getuid()}"
        if not os.path.isdir(rt):                 # sem systemd (macOS, BSD)
            rt = os.path.join(tempfile.gettempdir(), f"hermes-voice-{os.getuid()}")
    return Path(rt or os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "hermes-voice" / "claude"


PASTA = _pasta()
# Sem AF_UNIX (o Python do Windows), o canal escuta no laço local e o .sock da
# sessão é um arquivo com a porta e a chave de quem pode falar com ela.
UNIX = hasattr(socket, "AF_UNIX")
NOME = "orbe"

INSTRUCOES = (
    'Mensagens do orbe de voz chegam como <channel source="orbe" pedido="...">. '
    "O conteúdo é a fala do usuário transcrita por reconhecimento de voz e pode trazer "
    "erros de transcrição. Faça o que ele pedir nesta sessão, como faria com um pedido "
    "digitado, e no fim chame a ferramenta reply uma vez, com o mesmo pedido, trazendo "
    "a resposta que será falada em voz alta. A resposta falada não leva markdown, código, "
    "listas nem caminhos longos; o detalhe fica no terminal."
)


# Vai em cada mensagem, como atributo da tag <channel>: há versões do Claude
# Code que não levam as instruções do servidor ao modelo (medido na 2.1.289: ele
# respondia no terminal e não chamava o reply, e o orbe ficava sem resposta).
LEMBRETE = ("Fala do usuario pelo orbe de voz. No fim, chame a ferramenta reply com este "
            "pedido e a resposta que sera dita em voz alta, sem markdown.")


def _vivo(pid: int) -> bool:
    if os.name == "nt":
        # no Windows o os.kill(pid, 0) não sonda: ele encerra o processo
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            codigo = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(codigo))) and codigo.value == 259   # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def sessoes() -> list[dict]:
    """Sessões do Claude com o canal ativo, da mais recente para a mais antiga."""
    achadas = []
    for s in PASTA.glob("*.sock"):
        try:
            pid = int(s.stem)
        except ValueError:
            continue
        if not _vivo(pid):
            continue
        info = {"pid": pid, "sock": str(s), "desde": s.stat().st_mtime, "cwd": ""}
        try:
            info.update(json.loads(s.with_suffix(".json").read_text()))
        except (OSError, ValueError):
            pass
        achadas.append(info)
    return sorted(achadas, key=lambda i: i["desde"], reverse=True)


# ── servidor: roda dentro da sessão do Claude ──────────────────────────────

class Canal:
    def __init__(self):
        self.pid = os.getppid()
        self.sock_path = PASTA / f"{self.pid}.sock"
        self.info_path = PASTA / f"{self.pid}.json"
        self._saida = threading.Lock()
        self._pendentes: dict[str, socket.socket] = {}
        self._trava = threading.Lock()
        self._chave = ""              # só no laço local: o que o cliente apresenta antes de perguntar

    # MCP: ndjson no stdin/stdout
    def _escrever(self, msg: dict):
        linha = json.dumps(msg, ensure_ascii=False) + "\n"
        with self._saida:
            sys.stdout.write(linha)
            sys.stdout.flush()

    def _responder(self, mid, resultado=None, erro=None):
        m = {"jsonrpc": "2.0", "id": mid}
        if erro is not None:
            m["error"] = erro
        else:
            m["result"] = resultado if resultado is not None else {}
        self._escrever(m)

    def _instrucoes(self) -> str:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import hermes_voice_config as vcfg
            voz = (vcfg.carregar()["agente"].get("instrucao_voz") or "").strip()
        except Exception:
            voz = ""
        return INSTRUCOES + ("\n\n" + voz if voz else "")

    def _ferramentas(self) -> list[dict]:
        return [{
            "name": "reply",
            "description": "Fala a resposta ao usuário pelo orbe de voz.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pedido": {"type": "string", "description": "O atributo pedido da tag <channel>."},
                    "text": {"type": "string", "description": "O que será dito em voz alta."},
                },
                "required": ["pedido", "text"],
            },
        }]

    def _chamar(self, nome: str, args: dict) -> dict:
        if nome != "reply":
            return {"content": [{"type": "text", "text": f"ferramenta desconhecida: {nome}"}],
                    "isError": True}
        pedido = str(args.get("pedido") or "")
        texto = str(args.get("text") or "")
        with self._trava:
            cli = self._pendentes.pop(pedido, None)
        if cli is None:
            return {"content": [{"type": "text", "text":
                    "O orbe não espera mais esta resposta (a conversa de voz foi interrompida)."}]}
        try:
            cli.sendall((json.dumps({"tipo": "resposta", "pedido": pedido, "texto": texto},
                                    ensure_ascii=False) + "\n").encode())
        except OSError:
            return {"content": [{"type": "text", "text": "O orbe desconectou antes da resposta."}]}
        return {"content": [{"type": "text", "text": "falado"}]}

    def _tratar(self, msg: dict):
        metodo, mid = msg.get("method"), msg.get("id")
        if metodo is None:
            return
        if metodo == "initialize":
            p = msg.get("params") or {}
            self._responder(mid, {
                "protocolVersion": p.get("protocolVersion") or "2025-06-18",
                "capabilities": {"experimental": {"claude/channel": {}}, "tools": {}},
                "serverInfo": {"name": NOME, "version": "0.1"},
                "instructions": self._instrucoes(),
            })
        elif metodo == "tools/list":
            self._responder(mid, {"tools": self._ferramentas()})
        elif metodo == "tools/call":
            p = msg.get("params") or {}
            self._responder(mid, self._chamar(p.get("name", ""), p.get("arguments") or {}))
        elif metodo == "ping":
            self._responder(mid, {})
        elif mid is not None:
            self._responder(mid, erro={"code": -32601, "message": f"método desconhecido: {metodo}"})

    # socket local: o daemon do orbe pergunta aqui
    def _cliente(self, cli: socket.socket):
        buf = b""
        # o socket Unix já é só do usuário (0600); o laço local pede a chave
        autorizado = UNIX
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
                    if not autorizado:
                        if m.get("tipo") != "chave" or not hmac.compare_digest(str(m.get("chave")), self._chave):
                            return
                        autorizado = True
                        continue
                    if m.get("tipo") == "pergunta":
                        pedido = uuid.uuid4().hex[:8]
                        with self._trava:
                            self._pendentes[pedido] = cli
                        self._escrever({"jsonrpc": "2.0", "method": "notifications/claude/channel",
                                        "params": {"content": str(m.get("texto") or ""),
                                                   "meta": {"pedido": pedido, "responder": LEMBRETE}}})
                        cli.sendall((json.dumps({"tipo": "aceito", "pedido": pedido}) + "\n").encode())
                    elif m.get("tipo") == "cancelar":
                        with self._trava:
                            for k in [k for k, c in self._pendentes.items() if c is cli]:
                                del self._pendentes[k]
        except OSError:
            pass
        finally:
            with self._trava:
                for k in [k for k, c in self._pendentes.items() if c is cli]:
                    del self._pendentes[k]
            cli.close()

    def _escutar(self, srv: socket.socket):
        while True:
            try:
                cli, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._cliente, args=(cli,), daemon=True).start()

    def _limpar(self, *_):
        for p in (self.sock_path, self.info_path):
            try:
                p.unlink()
            except OSError:
                pass

    def rodar(self):
        for fluxo in (sys.stdin, sys.stdout):     # o MCP é UTF-8; o console do Windows, não
            try:
                fluxo.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
        PASTA.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._limpar()
        if UNIX:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(self.sock_path))
            os.chmod(self.sock_path, 0o600)
        else:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            self._chave = secrets.token_hex(16)
            self.sock_path.write_text(f"{srv.getsockname()[1]} {self._chave}")
        srv.listen(4)
        self.info_path.write_text(json.dumps({"cwd": os.getcwd()}))
        signal.signal(signal.SIGTERM, lambda *_: (self._limpar(), os._exit(0)))
        threading.Thread(target=self._escutar, args=(srv,), daemon=True).start()
        try:
            for linha in sys.stdin:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    self._tratar(json.loads(linha))
                except ValueError:
                    continue
        finally:
            self._limpar()


# ── cliente: usado pelo daemon do orbe ─────────────────────────────────────

def _ligar(caminho: Path) -> socket.socket:
    """Conecta ao canal de uma sessão: socket Unix, ou o laço local com a chave."""
    if UNIX:
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            cli.connect(str(caminho))
        except OSError:
            cli.close()
            raise
        return cli
    porta, chave = caminho.read_text().split()
    cli = socket.create_connection(("127.0.0.1", int(porta)), timeout=3)
    cli.sendall((json.dumps({"tipo": "chave", "chave": chave}) + "\n").encode())
    return cli


class AgenteClaude:
    """Fala com a sessão aberta mais recente; não sobe processo nenhum."""

    def __init__(self):
        import hermes_voice_acp as acp
        self._erro = acp.ErroACP
        self.iniciado_em = time.time()
        self.sessao = ""
        self.info: dict = {"agentInfo": {"name": "Claude Code", "title": "Claude Code"}}
        self.modelos: list = []
        self.modelo_atual = ""
        self.cwd = ""

    def iniciar(self, teto: float = 0):
        pass

    def abrir_sessao(self, retomar=None, teto: float = 0):
        s = sessoes()
        if not s:
            raise self._erro("nenhuma sessão do Claude aberta com o canal do orbe (use claude-orbe)")
        self.sessao, self.cwd = str(s[0]["pid"]), s[0].get("cwd", "")
        return self.sessao

    def vivo(self) -> bool:
        if not self.sessao or not _vivo(int(self.sessao)):
            return False
        s = sessoes()
        # Uma sessão aberta depois passa a ser a escolhida.
        return bool(s) and str(s[0]["pid"]) == self.sessao

    def definir_modelo(self, modelo: str):
        raise self._erro("o modelo é o da sessão aberta do Claude")

    def fechar(self):
        pass

    def cancelar(self):
        pass

    def erro_recente(self) -> str:
        return ""

    def perguntar(self, texto, ao_texto, ao_pensamento=None, a_ferramenta=None,
                  parar=None, teto: float = 600.0) -> str:
        """Manda a fala e espera o reply. Interromper só para a espera: o
        Claude segue o que estiver fazendo no terminal."""
        try:
            cli = _ligar(PASTA / f"{self.sessao}.sock")
        except (OSError, ValueError) as e:
            raise self._erro(f"sessão {self.sessao} não atende: {e}")
        cli.settimeout(0.2)
        fim = time.monotonic() + teto
        buf = b""
        try:
            cli.sendall((json.dumps({"tipo": "pergunta", "texto": texto}, ensure_ascii=False)
                         + "\n").encode())
            if a_ferramenta:
                a_ferramenta("claude", "pending")
            while True:
                if parar is not None and parar.is_set():
                    cli.sendall(b'{"tipo": "cancelar"}\n')
                    return "cancelled"
                if time.monotonic() > fim:
                    cli.sendall(b'{"tipo": "cancelar"}\n')
                    raise self._erro(f"sem resposta do Claude em {teto:.0f} s")
                try:
                    bloco = cli.recv(65536)
                except socket.timeout:
                    continue
                if not bloco:
                    raise self._erro("a sessão do Claude fechou o canal")
                buf += bloco
                while b"\n" in buf:
                    linha, buf = buf.split(b"\n", 1)
                    try:
                        m = json.loads(linha)
                    except ValueError:
                        continue
                    if m.get("tipo") == "resposta":
                        ao_texto(m.get("texto") or "")
                        return "end_turn"
        finally:
            cli.close()


if __name__ == "__main__":
    if "--mcp-config" in sys.argv:
        # o que o claude-orbe passa ao Claude, com o Python e o caminho desta máquina
        print(json.dumps({"mcpServers": {NOME: {"type": "stdio", "command": sys.executable,
                                                 "args": [str(Path(__file__).resolve())]}}}))
    else:
        Canal().rodar()
