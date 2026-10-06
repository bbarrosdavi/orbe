#!/usr/bin/env python3
"""Sessões do Claude Code que o orbe não abriu: ver, mandar a fala, ouvir a resposta.

O canal (orbe_canal.py) só existe nas sessões abertas com o
claude-orbe. As abertas à mão o orbe alcança por um hook do usuário, posto no
~/.claude/settings.json com --instalar. Só a stdlib:

- `--hook`, em SessionStart e Stop, com asyncRewake: roda em segundo plano e
  espera num socket local da sessão (a escuta). Chegou uma fala do orbe, a
  escuta sai com código 2 e o Claude daquela sessão acorda com o pedido, mesmo
  parado. Com a sessão no meio de um turno, ele entra na fila "next" do Claude
  Code, a mesma do que se digita enquanto ela trabalha, e chega no turno em
  andamento. O pedido leva uma marca: no Stop do turno em que ela já está no
  transcript, a mesma entrada deixa a última resposta para o orbe e arma a
  escuta de novo.
- Importado pelo daemon e pelo pulso: `sessoes()` lista as sessões vivas, pelo
  registro do próprio Claude Code (~/.claude/sessions), e `agente(pid)` dá o
  agente de uma delas, com a cara do AgenteClaude.

O Claude atende porque o hook diz de onde o pedido vem (ORIGEM, abaixo): sem
isso ele recusa uma mensagem que não veio do usuário.

  orbe_sessao.py               lista as sessões abertas
  orbe_sessao.py --instalar    põe o hook no settings.json do usuário
  orbe_sessao.py --remover     tira o hook e solta as escutas
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
REGISTRO = CLAUDE_DIR / "sessions"
SETTINGS = CLAUDE_DIR / "settings.json"
# Sem AF_UNIX (o Python do Windows) a escuta fica no laço local e o .sock é um
# arquivo com a porta e a chave, como no canal.
UNIX = hasattr(socket, "AF_UNIX")
# Quanto a escuta espera com a sessão parada (o timeout do hook, que o Claude
# aplica também em segundo plano). Passou disso, a sessão volta a ouvir no fim
# do próximo turno dela.
VIDA_S = 86400
ORIGEM = ("Pedido de voz do usuário desta sessão, transcrito pelo orbe de voz (hook do orbe "
          "que ele instalou no próprio settings.json; a resposta final é lida em voz alta para ele):")
RESUMO = "Pedido do orbe de voz"
# o nome deste script no comando do hook; o segundo é o de antes da troca de
# nome (2026-10-06), para o --instalar e o --remover limparem o hook antigo
MARCAS = ("orbe_sessao.py", "hermes_voice_sessao.py")


def _pasta() -> Path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import orbe_config as vcfg
    return vcfg.RUNTIME / "orbe" / "sessoes"


def _vivo(pid: int) -> bool:
    if os.name == "nt":
        import orbe_canal as canal      # o teste do Windows (ctypes) mora lá
        return canal._vivo(pid)
    # sem importar o canal: a escuta fica parada a sessão inteira, e ele pesa uns 4 MB
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _alcancavel(d: dict) -> bool:
    """Sessão de terminal ou de segundo plano. O claude -p também se registra
    como interactive, mas com a entrada do SDK: essa não tem a quem acordar."""
    kind = d.get("kind")
    return kind == "bg" or (kind == "interactive" and d.get("entrypoint") == "cli")


def _registros() -> list[dict]:
    achados = []
    for p in REGISTRO.glob("*.json"):
        try:
            d = json.loads(p.read_text())
            d["pid"] = int(d["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        achados.append(d)
    return achados


def sessoes() -> list[dict]:
    """As sessões do Claude Code vivas, da mais antiga para a mais nova.

    canal: aberta com o claude-orbe (o canal do orbe responde por ela);
    ouve: tem a escuta do hook armada; estado: "parada" ou "trabalhando".
    """
    import orbe_canal as canal
    pasta = _pasta()
    vivas = []
    for d in _registros():
        if not _alcancavel(d) or not _vivo(d["pid"]):
            continue
        pid = d["pid"]
        cwd = str(d.get("cwd") or "")
        vivas.append({
            "pid": pid,
            "nome": str(d.get("name") or ""),
            # o nome derivado já é a pasta com o começo do id (orbe-relogio-2c)
            "nome_derivado": d.get("nameSource") == "derived",
            "pasta": Path(cwd).name or cwd,
            "cwd": cwd,
            "sessao": str(d.get("sessionId") or ""),
            "estado": "parada" if d.get("status") == "idle" else "trabalhando",
            "desde": d.get("startedAt") or 0,
            "canal": (canal.PASTA / f"{pid}.sock").exists(),
            "ouve": (pasta / f"{pid}.sock").exists(),
        })
    return sorted(vivas, key=lambda s: (s["desde"], s["pid"]))


_CANAL = re.compile(r'<channel\b[^>]*>(.*?)</channel>', re.S)


def _inicio(p: Path) -> dict:
    """A pasta, a entrada e o primeiro pedido de um transcript (o que o /resume
    mostra de uma conversa sem título)."""
    try:
        with open(p, "rb") as f:
            bloco = f.read(256 * 1024)
    except OSError:
        return {}
    ini = {}
    for linha in bloco.splitlines():
        if b'"cwd"' not in linha:
            continue
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        if d.get("cwd") and "cwd" not in ini:
            ini = {"cwd": str(d["cwd"]), "entrypoint": str(d.get("entrypoint") or ""), "pedido": ""}
        c = (d.get("message") or {}).get("content") if d.get("type") == "user" else None
        if isinstance(c, list):
            c = next((x.get("text") for x in c if isinstance(x, dict) and x.get("type") == "text"), None)
        # a fala que chega pelo canal do orbe vem dentro da tag dele (numa
        # mensagem marcada como meta): o pedido é o miolo
        m = _CANAL.match(c.strip()) if isinstance(c, str) else None
        if m:
            c = m.group(1)
        elif d.get("isMeta"):
            c = None
        # os comandos de barra e os avisos do sistema vêm entre tags: não são o pedido
        if isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
            ini["pedido"] = " ".join(c.split())[:120]
            break
    return ini


def passadas(limite: int = 25) -> list[dict]:
    """As conversas do Claude Code abertas no terminal que não estão vivas, da
    mais recente para a mais velha: id, título, pasta, cwd e quando (s). As do
    claude -p (o SDK, os hooks) ficam de fora: não são conversa do Davi."""
    vivas = {s["sessao"] for s in sessoes()}
    arquivos = []
    for p in (CLAUDE_DIR / "projects").glob("*/*.jsonl"):
        try:
            arquivos.append((p.stat().st_mtime, p))
        except OSError:
            pass
    arquivos.sort(reverse=True)
    achadas = []
    for quando, p in arquivos:
        if p.stem in vivas:
            continue
        ini = _inicio(p)
        if not ini or ini["entrypoint"] not in ("", "cli") or not Path(ini["cwd"]).is_dir():
            continue                    # o --resume roda na pasta da conversa: sem ela, não há onde
        cwd = ini["cwd"]
        nome = titulo({"sessao": p.stem, "cwd": cwd}) or ini.get("pedido", "")
        if not nome:
            continue                    # aberta e fechada sem conversa: nada a retomar
        achadas.append({"id": p.stem, "titulo": nome, "pasta": Path(cwd).name or cwd,
                        "cwd": cwd, "quando": int(quando)})
        if len(achadas) >= limite:
            break
    return achadas


def rotulo(s: dict) -> str:
    """O nome que o relógio mostra: o derivado já diz a pasta; o dado à mão vem com ela."""
    if s.get("nome_derivado") or not s.get("nome"):
        return s.get("nome") or s.get("pasta") or str(s.get("pid"))
    return f"{s['pasta']} · {s['nome']}" if s.get("pasta") else s["nome"]


# transcript -> (bytes já lidos, primeiro pedido): o nome da conversa sem título
_PEDIDOS: dict[str, tuple[int, str]] = {}


def _pedido(p: Path, tam: int) -> str:
    """O primeiro pedido da conversa, o que o /resume e o histórico mostram de
    uma sem título; lido de novo só enquanto não aparece e o arquivo cresce."""
    lido, achado = _PEDIDOS.get(str(p), (-1, ""))
    if achado or tam == lido:
        return achado
    achado = _inicio(p).get("pedido", "")
    _PEDIDOS[str(p)] = (tam, achado)
    return achado


# transcript -> (bytes já lidos, último título achado)
_TITULOS: dict[str, tuple[int, str]] = {}
# só o fim do transcript na primeira leitura: o título é regravado a cada turno
_CAUDA = 512 * 1024


def _transcript(sessao: str, cwd: str) -> Path | None:
    projetos = CLAUDE_DIR / "projects"
    p = projetos / re.sub(r"[^A-Za-z0-9]", "-", cwd) / f"{sessao}.jsonl"
    if p.exists():
        return p
    return next(iter(projetos.glob(f"*/{sessao}.jsonl")), None)


def _ultimo_titulo(bloco: bytes) -> str:
    for linha in reversed(bloco.splitlines()):
        if b'"ai-title"' not in linha and b'"custom-title"' not in linha:
            continue
        try:
            d = json.loads(linha)
        except ValueError:
            continue                    # a linha que ainda está sendo escrita
        t = d.get("customTitle") or d.get("aiTitle")
        if t:
            return str(t)
    return ""


def titulo(s: dict) -> str:
    """O título da conversa: o nome dado com /rename ou, sem ele, o que o Claude
    Code deu (o do /resume, linha ai-title do transcript) ou, sem esse, o
    primeiro pedido. Lê só o que o transcript cresceu desde a última vez."""
    if s.get("nome") and not s.get("nome_derivado"):
        return s["nome"]
    p = _transcript(s.get("sessao") or "", s.get("cwd") or "") if s.get("sessao") else None
    if p is None:
        return ""
    try:
        tam = p.stat().st_size
    except OSError:
        return ""
    lido, achado = _TITULOS.get(str(p), (0, ""))
    if tam == lido:
        return achado or _pedido(p, tam)
    ini = lido if 0 < lido < tam else max(0, tam - _CAUDA)
    try:
        with open(p, "rb") as f:
            f.seek(ini)
            novo = _ultimo_titulo(f.read(tam - ini))
            if not novo and not lido and ini > 0:
                f.seek(0)               # a cauda não tinha título: o arquivo inteiro, uma vez
                novo = _ultimo_titulo(f.read(ini))
    except OSError:
        return achado
    achado = novo or achado
    _TITULOS[str(p)] = (tam, achado)
    # o Claude Code nem sempre dá título a uma conversa viva (às vezes só ao
    # fechar): até lá, o primeiro pedido, como no histórico
    return achado or _pedido(p, tam)


class Etapas:
    """As etapas de um turno do Claude enquanto o orbe espera a resposta: a
    descrição de cada ferramenta chamada (a linha que o terminal mostra com o
    ponto, como "Checking branch and Windows/macOS notes in README"). Lê só o
    que o transcript cresceu desde que o pedido saiu; ferramenta sem descrição
    (ler, editar, buscar) não é etapa."""

    def __init__(self, pid: int | str):
        self._pid = int(pid)
        self._caminho: Path | None = None
        self._lido = 0
        self._resto = b""
        self._achar()

    def _achar(self):
        s = next((x for x in sessoes() if x["pid"] == self._pid), None)
        p = _transcript(s["sessao"], s["cwd"]) if s and s.get("sessao") else None
        if p is None or p == self._caminho:
            return
        # o /clear troca o transcript: o novo vale do começo
        primeiro = self._caminho is None
        self._caminho, self._resto = p, b""
        try:
            self._lido = p.stat().st_size if primeiro else 0
        except OSError:
            self._lido = 0

    def novas(self) -> list[str]:
        if self._caminho is None:
            self._achar()
            if self._caminho is None:
                return []
        try:
            tam = self._caminho.stat().st_size
        except OSError:
            self._caminho = None
            return []
        if tam < self._lido:
            self._lido, self._resto = 0, b""
        if tam == self._lido:
            return []
        try:
            with open(self._caminho, "rb") as f:
                f.seek(self._lido)
                bloco = self._resto + f.read(tam - self._lido)
        except OSError:
            return []
        self._lido = tam
        linhas = bloco.split(b"\n")
        self._resto = linhas.pop()          # a linha que ainda está sendo escrita
        achadas = []
        for linha in linhas:
            if b'"tool_use"' not in linha or b'"description"' not in linha:
                continue
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            for c in (d.get("message") or {}).get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                desc = (c.get("input") or {}).get("description")
                if isinstance(desc, str) and desc.strip():
                    achadas.append(" ".join(desc.split())[:200])
        return achadas


def _gravar(caminho: Path, dados: dict):
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False))
    os.replace(tmp, caminho)


def _ligar(caminho: Path, timeout: float = 3.0) -> socket.socket:
    if UNIX:
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.settimeout(timeout)
        try:
            cli.connect(str(caminho))
        except OSError:
            cli.close()
            raise
        return cli
    porta, chave = caminho.read_text().split()
    cli = socket.create_connection(("127.0.0.1", int(porta)), timeout=timeout)
    cli.sendall((json.dumps({"tipo": "chave", "chave": chave}) + "\n").encode())
    return cli


def _ler_linha(cli: socket.socket, limite: int = 1 << 20) -> dict | None:
    buf = b""
    while b"\n" not in buf and len(buf) < limite:
        bloco = cli.recv(65536)
        if not bloco:
            break
        buf += bloco
    try:
        return json.loads(buf.split(b"\n", 1)[0])
    except ValueError:
        return None


def _falar(caminho: Path, msg: dict, timeout: float = 3.0) -> dict | None:
    """Uma mensagem à escuta de uma sessão e a resposta dela."""
    cli = _ligar(caminho, timeout)
    try:
        cli.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        return _ler_linha(cli)
    finally:
        cli.close()


# ── o hook: roda dentro de cada sessão do Claude Code ──────────────────────

def _registro_de(sessao: str, espera: float) -> dict | None:
    """O registro da sessão do hook. No SessionStart ele pode ainda não existir."""
    fim = time.monotonic() + espera
    while True:
        for d in _registros():
            if d.get("sessionId") == sessao:
                return d
        if time.monotonic() >= fim:
            return None
        time.sleep(0.25)


def marca(pedido: str) -> str:
    """O que vai junto do pedido e o acha no transcript."""
    return f"(pedido do orbe {pedido})"


def _no_transcript(caminho: str, alvo: str) -> bool:
    """O [alvo] está no fim do transcript (o turno que acabou viu o pedido)."""
    try:
        with open(caminho, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4 * 1024 * 1024))
            return alvo.encode() in f.read()
    except OSError:
        return True                     # sem como conferir: entrega, como antes


def _entregar(pasta: Path, pid: int, texto: str, transcript: str = ""):
    """Stop de um turno com pedido do orbe: a última resposta fica para ele. Se o
    pedido ainda não entrou neste turno (chegou depois da última ferramenta e
    vai abrir o seguinte), fica para o Stop do próximo."""
    pedido = pasta / f"{pid}.pedido"
    try:
        d = json.loads(pedido.read_text())
    except (OSError, ValueError):
        return
    if transcript and d.get("pedido") and not _no_transcript(transcript, marca(str(d["pedido"]))):
        return
    try:
        pedido.unlink()
    except OSError:
        pass
    _gravar(pasta / f"{pid}.resposta", {"pedido": d.get("pedido", ""), "texto": texto})


def _acordar(pasta: Path, pid: int, pedido: str, texto: str) -> int:
    """Sai com 2: o Claude da sessão acorda com o pedido, ou o recebe no turno em andamento."""
    if pedido:
        _gravar(pasta / f"{pid}.pedido", {"pedido": pedido, "t": time.time()})
    sys.stderr.write(texto + (f"\n{marca(pedido)}" if pedido else "") + "\n")
    sys.stderr.flush()
    return 2


def _escutar(pasta: Path, pid: int) -> int:
    """Espera a fala do orbe; com ela, sai com 2 e o Claude acorda com o pedido."""
    sock = pasta / f"{pid}.sock"
    try:
        _falar(sock, {"tipo": "ping"}, 1.0)
        return 0                    # outra escuta já serve esta sessão
    except (OSError, ValueError):
        pass
    try:
        sock.unlink()
    except OSError:
        pass
    chave = ""
    if UNIX:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock))
        os.chmod(sock, 0o600)
    else:
        import secrets
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        chave = secrets.token_hex(16)
        sock.write_text(f"{srv.getsockname()[1]} {chave}")
    srv.listen(4)
    srv.settimeout(2.0)
    try:
        while _vivo(pid):
            try:
                cli, _ = srv.accept()
            except socket.timeout:
                continue
            try:
                cli.settimeout(3.0)
                m = _ler_linha(cli)
                if m is not None and chave:
                    if m.get("tipo") != "chave" or m.get("chave") != chave:
                        continue
                    m = _ler_linha(cli)
                if m is None:
                    continue
                tipo = m.get("tipo")
                if tipo == "ping":
                    cli.sendall(b'{"tipo": "ok"}\n')
                elif tipo == "fim":
                    cli.sendall(b'{"tipo": "ok"}\n')
                    return 0
                elif tipo == "pergunta":
                    # parada, acorda; trabalhando, o Claude Code põe o pedido na
                    # fila "next" e ele chega no turno em andamento, como o que se
                    # digita com ela trabalhando
                    reg = next((d for d in _registros() if d["pid"] == pid), {})
                    trabalhando = reg.get("status") not in (None, "idle")
                    cli.sendall(b'{"tipo": "no_turno"}\n' if trabalhando else b'{"tipo": "aceito"}\n')
                    return _acordar(pasta, pid, str(m.get("pedido") or ""), str(m.get("texto") or "").strip())
            except OSError:
                continue
            finally:
                cli.close()
        return 0
    finally:
        srv.close()
        try:
            sock.unlink()
        except OSError:
            pass


def _hook() -> int:
    """A entrada do settings.json (SessionStart e Stop, com asyncRewake)."""
    # Fora do terminal (claude -p, SDK) o hook roda dentro do turno e o Claude
    # espera por ele no fim: lá não há o que fazer, sai já.
    entrada = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")
    bg = os.environ.get("CLAUDE_CODE_SESSION_KIND") == "bg"
    if entrada and entrada != "cli" and not bg:
        return 0
    try:
        ent = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    reg = _registro_de(str(ent.get("session_id") or ""), 5.0 if entrada == "cli" or bg else 0.0)
    if reg is None or not _alcancavel(reg):
        return 0
    pasta = _pasta()
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ent.get("hook_event_name") == "Stop":
        _entregar(pasta, reg["pid"], str(ent.get("last_assistant_message") or ""),
                  str(ent.get("transcript_path") or ""))
    return _escutar(pasta, reg["pid"])


# ── instalação no settings.json do usuário ─────────────────────────────────

def _comando() -> str:
    """O comando do hook. O código 2 acorda a sessão, e é com ele que o Python
    sai quando não acha o script: sem o arquivo, o test sai com 1 e nada acorda."""
    script = str(Path(__file__).resolve())
    if os.name == "nt":
        import subprocess
        return subprocess.list2cmdline([sys.executable, script, "--hook"])
    import shlex
    return f"test -f {shlex.quote(script)} && exec {shlex.quote(sys.executable)} {shlex.quote(script)} --hook"


def _sem_o_orbe(grupos: list) -> list:
    """Os grupos do evento sem as entradas deste hook (e sem grupo que ficou vazio)."""
    limpos = []
    for g in grupos:
        if not isinstance(g, dict):
            limpos.append(g)
            continue
        hooks = [h for h in g.get("hooks") or []
                 if not any(m in str((h or {}).get("command") or "") for m in MARCAS)]
        if hooks or not g.get("hooks"):
            limpos.append(dict(g, hooks=hooks))
    return limpos


def _ler_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except FileNotFoundError:
        return {}


def _gravar_settings(d: dict):
    if SETTINGS.exists():
        reserva = SETTINGS.with_name(SETTINGS.name + ".orbe-bak")
        reserva.write_bytes(SETTINGS.read_bytes())
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_name(SETTINGS.name + ".orbe-tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, SETTINGS)


def instalar():
    d = _ler_settings()
    hooks = d.setdefault("hooks", {})
    entrada = {"type": "command", "command": _comando(), "asyncRewake": True, "timeout": VIDA_S,
               "rewakeMessage": ORIGEM, "rewakeSummary": RESUMO}
    for ev in ("SessionStart", "Stop"):
        hooks[ev] = _sem_o_orbe(hooks.get(ev) or []) + [{"hooks": [entrada]}]
    _gravar_settings(d)
    print(f"hook do orbe instalado em {SETTINGS} (cópia anterior em {SETTINGS.name}.orbe-bak)")
    print("as sessões abertas passam a ouvir o orbe no fim do próximo turno delas")


def remover():
    d = _ler_settings()
    hooks = d.get("hooks") or {}
    for ev in list(hooks):
        if isinstance(hooks[ev], list):
            hooks[ev] = _sem_o_orbe(hooks[ev])
            if not hooks[ev]:
                del hooks[ev]
    if not hooks:
        d.pop("hooks", None)
    _gravar_settings(d)
    soltas = 0
    for s in _pasta().glob("*.sock"):
        try:
            _falar(s, {"tipo": "fim"}, 1.0)
            soltas += 1
        except (OSError, ValueError):
            pass
    print(f"hook do orbe removido de {SETTINGS}; {soltas} escuta(s) solta(s)")


# ── o agente: usado pelo daemon e pelo pulso ───────────────────────────────

class AgenteSessao:
    """Fala com uma sessão aberta à mão, pela escuta do hook."""

    def __init__(self, pid: int):
        import orbe_acp as acp
        self._erro = acp.ErroACP
        self.alvo = int(pid)
        self.iniciado_em = time.time()
        self.sessao = ""
        self.info: dict = {"agentInfo": {"name": "Claude Code", "title": "Claude Code"}}
        self.modelos: list = []
        self.modelo_atual = ""
        self.cwd = ""
        self._pasta = _pasta()

    def iniciar(self, teto: float = 0):
        pass

    def abrir_sessao(self, retomar=None, teto: float = 0):
        s = next((s for s in sessoes() if s["pid"] == self.alvo), None)
        if s is None:
            raise self._erro(f"a sessão {self.alvo} do Claude fechou")
        self.sessao, self.cwd = str(self.alvo), s["cwd"]
        return self.sessao

    def vivo(self) -> bool:
        return bool(self.sessao) and _vivo(self.alvo)

    def definir_modelo(self, modelo: str):
        raise self._erro("o modelo é o da sessão aberta do Claude")

    def fechar(self):
        pass

    def cancelar(self):
        pass

    def erro_recente(self) -> str:
        return ""

    def perguntar(self, texto, ao_texto, ao_pensamento=None, a_ferramenta=None,
                  parar=None, teto: float = 600.0, a_etapa=None) -> str:
        """Acorda a sessão com a fala e espera o Stop do turno dela. Interromper
        só para a espera: o Claude segue o que estiver fazendo no terminal.
        [a_etapa] recebe a descrição de cada ferramenta que ela chama."""
        import uuid
        pedido = uuid.uuid4().hex[:8]
        etapas = Etapas(self.alvo) if a_etapa else None
        sock = self._pasta / f"{self.alvo}.sock"
        resposta = self._pasta / f"{self.alvo}.resposta"
        fim = time.monotonic() + teto
        avisou = False
        while True:
            if parar is not None and parar.is_set():
                return "cancelled"
            if time.monotonic() > fim:
                raise self._erro(f"a sessão {self.alvo} não parou em {teto:.0f} s")
            try:
                r = _falar(sock, {"tipo": "pergunta", "texto": texto, "pedido": pedido})
            except (OSError, ValueError):
                raise self._erro(f"a sessão {self.alvo} não ouve o orbe (falta o hook: "
                                 "orbe_sessao.py --instalar, ou ela ainda não terminou um turno)")
            tipo = (r or {}).get("tipo")
            if tipo == "aceito":
                break
            if tipo == "no_turno":
                if ao_pensamento is not None:
                    ao_pensamento("a sessão está trabalhando: o pedido entrou no turno dela\n")
                break
            # "ocupada" é a escuta antiga: o orbe espera ela parar
            if tipo != "ocupada":
                raise self._erro(f"a sessão {self.alvo} recusou o pedido ({tipo or 'sem resposta'})")
            if not avisou and ao_pensamento is not None:
                ao_pensamento("a sessão está trabalhando; o pedido entra quando ela parar\n")
                avisou = True
            time.sleep(0.5)
        if a_ferramenta:
            a_ferramenta("claude", "pending")
        while True:
            if (parar is not None and parar.is_set()) or time.monotonic() > fim:
                self._desistir(pedido)
                if parar is not None and parar.is_set():
                    return "cancelled"
                raise self._erro(f"sem resposta da sessão {self.alvo} em {teto:.0f} s")
            try:
                d = json.loads(resposta.read_text())
            except (OSError, ValueError):
                d = None
            if d is not None and d.get("pedido") == pedido:
                try:
                    resposta.unlink()
                except OSError:
                    pass
                ao_texto(str(d.get("texto") or ""))
                return "end_turn"
            if not _vivo(self.alvo):
                raise self._erro(f"a sessão {self.alvo} do Claude fechou")
            if etapas is not None and a_etapa:
                for e in etapas.novas():
                    a_etapa(e)
            time.sleep(0.2)

    def _desistir(self, pedido: str):
        """O orbe não espera mais: o Stop desse turno não deixa resposta."""
        p = self._pasta / f"{self.alvo}.pedido"
        try:
            if json.loads(p.read_text()).get("pedido") == pedido:
                p.unlink()
        except (OSError, ValueError):
            pass


def agente(pid: int = 0):
    """O agente de uma sessão: pelo canal, se ela foi aberta com o claude-orbe
    (ou sem pid: a mais recente com ele); pela escuta do hook, se não."""
    import orbe_canal as canal
    if not pid or (canal.PASTA / f"{pid}.sock").exists():
        return canal.AgenteClaude(pid)
    return AgenteSessao(pid)


def main():
    if "--hook" in sys.argv:
        sys.exit(_hook())
    if "--instalar" in sys.argv:
        instalar()
    elif "--remover" in sys.argv:
        remover()
    else:
        vivas = sessoes()
        if not vivas:
            print("nenhuma sessão do Claude Code aberta")
        for s in vivas:
            via = "canal do orbe" if s["canal"] else "hook" if s["ouve"] else "sem o hook"
            print(f"{s['pid']:>8}  {rotulo(s):<32} {s['estado']:<12} {via:<14} {s['cwd']}")


if __name__ == "__main__":
    main()
