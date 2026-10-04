"""Cliente ACP (Agent Client Protocol) do orbe de voz.

Mesmo fio que a Hina usa com o Hermes (src/llm/hermes_acp_provider.py):
JSON-RPC 2.0, uma mensagem JSON por linha, no stdin/stdout do agente.
Sequência: initialize → session/new (ou session/load) → session/prompt. O
texto da resposta chega em notificações session/update (agent_message_chunk)
enquanto o session/prompt não volta; session/cancel interrompe o turno sem
derrubar o processo, então o agente fica carregado entre um pedido e outro.

Qualquer agente que fale ACP serve: Hermes (`hermes -p <perfil> acp`),
OpenCode (`opencode acp`), Gemini CLI (`gemini --acp`) ou um comando dado.

Só biblioteca padrão e threads: roda dentro do daemon (Python do venv do
Hermes) e do app de configuração (Python do sistema).
"""
from __future__ import annotations

import collections
import glob
import json
import logging
import os
import shlex
import shutil
import subprocess
import threading
import time

LOG = logging.getLogger("hermes-voice.acp")

HERMES_LAUNCHER = os.path.expanduser("~/.local/bin/hermes")
PROFILES_DIR = os.path.expanduser("~/.hermes/profiles")

NOMES = {
    "hermes": "Hermes",
    "opencode": "OpenCode",
    "gemini": "Gemini CLI",
    "comando": "Comando ACP",
    "claude": "Claude Code",
}


class ErroACP(RuntimeError):
    pass


def perfis_hermes() -> list[str]:
    try:
        nomes = sorted(n for n in os.listdir(PROFILES_DIR)
                       if os.path.isdir(os.path.join(PROFILES_DIR, n))
                       and not n.startswith(("_", ".")))
    except OSError:
        nomes = []
    return ["default"] + nomes


def _gemini_bin() -> str | None:
    """O gemini vem do npm sob o fnm, cujo PATH muda a cada shell."""
    achados = sorted(glob.glob(os.path.expanduser(
        "~/.local/share/fnm/node-versions/*/installation/bin/gemini")))
    return achados[-1] if achados else shutil.which("gemini")


def disponivel(tipo: str) -> bool:
    if tipo == "hermes":
        return os.path.exists(HERMES_LAUNCHER)
    if tipo == "opencode":
        return shutil.which("opencode") is not None
    if tipo == "gemini":
        return _gemini_bin() is not None
    if tipo == "claude":
        return shutil.which("claude") is not None
    return tipo == "comando"


def comando(agente: dict, hermes_rt: list[str] | None = None) -> tuple[list[str], dict]:
    """(argv, variáveis extras de ambiente) do agente escolhido na config."""
    tipo = agente.get("tipo") or "hermes"
    if tipo == "hermes":
        perfil = (agente.get("perfil") or "jarvis").strip()
        if perfil not in perfis_hermes():
            # perfil do config que não existe nesta máquina (o padrão "jarvis"
            # numa instalação nova): o hermes recusaria e o orbe ficaria mudo
            perfil = "default"
        base = list(hermes_rt) if hermes_rt else [HERMES_LAUNCHER]
        return base + ([] if perfil == "default" else ["-p", perfil]) + ["acp", "--accept-hooks"], {}
    if tipo == "opencode":
        return [shutil.which("opencode") or "opencode", "acp"], {}
    if tipo == "gemini":
        exe = _gemini_bin()
        if not exe:
            raise ErroACP("gemini não encontrado")
        # O script do gemini começa com "#!/usr/bin/env node".
        caminho = os.path.dirname(exe) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
        return [exe, "--acp"], {"PATH": caminho}
    argv = shlex.split(agente.get("comando") or "")
    if not argv:
        raise ErroACP("comando ACP vazio")
    return argv, {}


class AgenteACP:
    def __init__(self, argv: list[str], env: dict | None = None, cwd: str | None = None):
        self.argv = argv
        self.env = env
        self.cwd = cwd or os.path.expanduser("~")
        self.proc: subprocess.Popen | None = None
        self.iniciado_em = 0.0
        self.info: dict = {}
        self.sessao: str | None = None
        # Modelos que o agente oferece: [{"id", "nome"}], e o atual.
        self.modelos: list[dict] = []
        self.modelo_atual = ""
        self._via_opcao = ""          # configId quando o modelo vem de configOptions
        self._id = 0
        self._pendentes: dict[int, list] = {}
        self._trava_escrita = threading.Lock()
        self._trava = threading.Lock()
        self._trava_turno = threading.Lock()
        self._turno = None            # (ao_texto, ao_pensamento, a_ferramenta)
        self._stderr = collections.deque(maxlen=40)

    # ── processo ──

    def vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def iniciar(self, teto: float = 90.0) -> None:
        env = dict(self.env if self.env is not None else os.environ)
        self.proc = subprocess.Popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=self.cwd, env=env, close_fds=True,
            start_new_session=True,
        )
        self.iniciado_em = time.time()
        threading.Thread(target=self._ler, daemon=True).start()
        threading.Thread(target=self._ler_stderr, daemon=True).start()
        self.info = self._pedir("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "hermes-voice", "version": "1.0"},
        }, teto) or {}

    def fechar(self) -> None:
        proc, self.proc = self.proc, None
        self.sessao = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for lst in list(self._pendentes.values()):
            lst[1] = {"error": {"message": "agente encerrado"}}
            lst[0].set()

    def erro_recente(self) -> str:
        return " | ".join(list(self._stderr)[-4:])[-400:]

    # ── sessão ──

    def abrir_sessao(self, retomar: str | None = None, teto: float = 60.0) -> str:
        """session/load quando o agente aceita e há id salvo; senão session/new."""
        res = None
        pode_carregar = bool((self.info.get("agentCapabilities") or {}).get("loadSession"))
        if retomar and pode_carregar:
            try:
                # Sessão desconhecida volta null (Hermes) ou erro (outros).
                res = self._pedir("session/load", {"sessionId": retomar, "cwd": self.cwd,
                                                   "mcpServers": []}, teto)
            except ErroACP as e:
                LOG.info("session/load recusado (%s); conversa nova", e)
                res = None
        if res is not None:
            self.sessao = retomar
        else:
            res = self._pedir("session/new", {"cwd": self.cwd, "mcpServers": []}, teto) or {}
            self.sessao = res.get("sessionId")
            if not self.sessao:
                raise ErroACP("session/new sem sessionId")
        self._ler_modelos(res)
        return self.sessao or ""

    def _ler_modelos(self, res: dict) -> None:
        m = res.get("models")
        if isinstance(m, dict) and m.get("availableModels"):
            self.modelos = [{"id": x.get("modelId", ""), "nome": x.get("name") or x.get("modelId", "")}
                            for x in m["availableModels"] if x.get("modelId")]
            self.modelo_atual = m.get("currentModelId") or ""
            self._via_opcao = ""
            return
        for op in res.get("configOptions") or []:
            if op.get("category") == "model" or op.get("id") == "model":
                opcoes = []
                for o in op.get("options") or []:
                    for x in (o.get("options") if "options" in o else [o]):
                        if x.get("value"):
                            opcoes.append({"id": x["value"], "nome": x.get("name") or x["value"]})
                self.modelos = opcoes
                self.modelo_atual = op.get("currentValue") or ""
                self._via_opcao = op.get("id") or "model"
                return

    def definir_modelo(self, modelo: str, teto: float = 30.0) -> None:
        if not modelo or modelo == self.modelo_atual or not self.sessao:
            return
        if self._via_opcao:
            self._pedir("session/set_config_option", {"sessionId": self.sessao,
                                                      "configId": self._via_opcao,
                                                      "value": modelo}, teto)
        else:
            self._pedir("session/set_model", {"sessionId": self.sessao, "modelId": modelo}, teto)
        self.modelo_atual = modelo

    # ── turno ──

    def perguntar(self, texto: str, ao_texto, ao_pensamento=None, a_ferramenta=None,
                  parar=None, teto: float = 120.0) -> str:
        """Manda o pedido e bloqueia até o fim do turno. Devolve o stopReason.

        ``parar`` (qualquer objeto com is_set()) verdadeiro no meio do turno
        manda session/cancel e espera o agente fechar o turno (stopReason
        "cancelled"), sem matar o processo. Um turno por vez: o pedido seguinte
        espera o cancelado fechar, senão o agente o enfileira.
        """
        with self._trava_turno:
            return self._perguntar(texto, ao_texto, ao_pensamento, a_ferramenta, parar, teto)

    def _perguntar(self, texto, ao_texto, ao_pensamento, a_ferramenta, parar, teto) -> str:
        if not self.sessao:
            raise ErroACP("sem sessão")
        self._turno = (ao_texto, ao_pensamento, a_ferramenta)
        req, ev, caixa = self._novo_pedido()
        try:
            self._escrever({"jsonrpc": "2.0", "id": req, "method": "session/prompt",
                            "params": {"sessionId": self.sessao,
                                       "prompt": [{"type": "text", "text": texto}]}})
            limite = time.monotonic() + teto
            cancelado = False
            while not ev.wait(0.1):
                if not self.vivo():
                    raise ErroACP("agente saiu no meio do turno: " + self.erro_recente())
                if parar is not None and parar.is_set() and not cancelado:
                    self.cancelar()
                    cancelado = True
                    limite = min(limite, time.monotonic() + 3.0)
                if time.monotonic() > limite:
                    if not cancelado:
                        self.cancelar()
                    raise ErroACP("turno passou do teto")
            if "error" in caixa[1]:
                raise ErroACP(str(caixa[1]["error"].get("message") or caixa[1]["error"]))
            return (caixa[1].get("result") or {}).get("stopReason", "")
        finally:
            self._turno = None
            self._pendentes.pop(req, None)

    def cancelar(self) -> None:
        if self.sessao and self.vivo():
            try:
                self._escrever({"jsonrpc": "2.0", "method": "session/cancel",
                                "params": {"sessionId": self.sessao}})
            except OSError:
                pass

    # ── JSON-RPC ──

    def _novo_pedido(self):
        with self._trava:
            self._id += 1
            req = self._id
        ev = threading.Event()
        caixa = [ev, {}]
        self._pendentes[req] = caixa
        return req, ev, caixa

    def _pedir(self, metodo: str, params: dict, teto: float):
        req, ev, caixa = self._novo_pedido()
        try:
            self._escrever({"jsonrpc": "2.0", "id": req, "method": metodo, "params": params})
            if not ev.wait(teto):
                raise ErroACP(f"{metodo} sem resposta em {teto:.0f}s: {self.erro_recente()}")
        finally:
            self._pendentes.pop(req, None)
        if "error" in caixa[1]:
            raise ErroACP(f"{metodo}: {caixa[1]['error'].get('message') or caixa[1]['error']}")
        return caixa[1].get("result")

    def _escrever(self, msg: dict) -> None:
        if not self.vivo():
            raise ErroACP("agente não está rodando: " + self.erro_recente())
        dado = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        proc = self.proc
        assert proc is not None and proc.stdin is not None
        with self._trava_escrita:
            proc.stdin.write(dado)
            proc.stdin.flush()

    def _ler(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        for linha in proc.stdout:
            try:
                msg = json.loads(linha)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            try:
                self._despachar(msg)
            except Exception:
                LOG.exception("ACP: mensagem não tratada")
        for lst in list(self._pendentes.values()):
            lst[1] = {"error": {"message": "agente encerrado: " + self.erro_recente()}}
            lst[0].set()

    def _ler_stderr(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stderr is not None
        for linha in proc.stderr:
            t = linha.decode("utf-8", "replace").strip()
            if t:
                self._stderr.append(t)
                LOG.debug("agente stderr: %s", t[:200])

    def _despachar(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
            caixa = self._pendentes.get(msg["id"])
            if caixa is not None:
                caixa[1] = msg
                caixa[0].set()
            return
        metodo = msg.get("method")
        if metodo == "session/update":
            self._atualizacao((msg.get("params") or {}).get("update") or {})
        elif metodo == "session/request_permission":
            # O orbe roda sem tela de confirmação, como o --yolo do CLI.
            opcoes = (msg.get("params") or {}).get("options") or []
            escolha = next((o.get("optionId") for o in opcoes
                            if str(o.get("kind", "")).startswith("allow")), None)
            if escolha is None and opcoes:
                escolha = opcoes[0].get("optionId")
            resultado = ({"outcome": "selected", "optionId": escolha} if escolha
                         else {"outcome": "cancelled"})
            self._escrever({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": resultado}})
        elif "id" in msg:
            self._escrever({"jsonrpc": "2.0", "id": msg["id"],
                            "error": {"code": -32601, "message": "método não suportado pelo cliente"}})

    def _atualizacao(self, up: dict) -> None:
        turno = self._turno
        if turno is None:
            return
        ao_texto, ao_pensamento, a_ferramenta = turno
        tipo = up.get("sessionUpdate")
        if tipo in ("agent_message_chunk", "agent_thought_chunk"):
            c = up.get("content") or {}
            t = c.get("text") if c.get("type") == "text" else ""
            if not t:
                return
            if tipo == "agent_message_chunk":
                ao_texto(t)
            elif ao_pensamento:
                ao_pensamento(t)
        elif tipo in ("tool_call", "tool_call_update") and a_ferramenta:
            a_ferramenta(up.get("title") or "", up.get("status") or "")


def sondar(agente: dict, hermes_rt: list[str] | None = None, teto: float = 90.0) -> dict:
    """Sobe o agente, abre uma sessão e devolve modelos; usado pelo app."""
    argv, extra = comando(agente, hermes_rt)
    env = dict(os.environ)
    env.update(extra)
    env.pop("HERMES_HOME", None)
    a = AgenteACP(argv, env)
    try:
        a.iniciar(teto)
        a.abrir_sessao(teto=teto)
        nome = (a.info.get("agentInfo") or {}).get("title") or (a.info.get("agentInfo") or {}).get("name") or ""
        return {"modelos": a.modelos, "atual": a.modelo_atual, "agente": nome}
    finally:
        a.fechar()
