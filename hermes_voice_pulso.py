#!/usr/bin/env python3
"""Orbe de pulso: a ponte de fala entre o relógio e o agente, sem o desktop.

O daemon (hermes_voice_daemon.py) é do Linux: PipeWire, o orbe em Quickshell,
palavra de ativação. Aqui fica só o caminho do relógio (orbe-wear), e ele roda
em qualquer sistema: o microfone e o alto-falante são os do relógio, e quem
responde é o agente da config, por ACP ou pelo canal do Claude Code.

    segurar o orbe  → a fala do relógio → Groq Whisper → o agente
    o agente pensa  → as linhas do raciocínio, no relógio
    o agente fala   → síntese frase a frase → a voz toca no relógio

O orbe continua sendo só a ponte: não decide nada e não guarda conversa. O
agente, a transcrição e a voz saem do mesmo config.json do daemon (agente, voz,
toque, relogio); as chaves, as do próprio orbe (~/.config/hermes-voice/chaves.env,
editadas no app), senão as do ambiente ou de ~/.hermes/.env (GROQ_API_KEY,
ELEVENLABS_API_KEY, GEMINI_API_KEY).

  hermes_voice_pulso.py                   sobe com o agente da config
  hermes_voice_pulso.py --agente claude   a sessão aberta com o claude-orbe
  hermes_voice_pulso.py --comando "npx -y @zed-industries/claude-agent-acp" --pasta ~/projeto
                                          um agente ACP qualquer, numa pasta

Com o terminal aberto, uma linha digitada vale por uma fala: serve para
conferir o agente e a voz sem o relógio na mão.
"""
import argparse
import array
import contextlib
import io
import logging
import math
import os
import queue
import re
import shutil
import sys
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hermes_voice_acp as acp  # noqa: E402
import hermes_voice_canal as canal  # noqa: E402
import hermes_voice_sessao as sessao  # noqa: E402
import hermes_voice_config as vcfg  # noqa: E402
import hermes_voice_relogio as relogio  # noqa: E402
import hermes_voice_tts as tts  # noqa: E402

LOG = logging.getLogger("pulso")

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# Só vocabulário, sem frase em volta (prosa aqui vira semente de alucinação);
# o mesmo do transcribe_groq do daemon.
GROQ_VOCABULARIO = ("Hermes, Jarvis, daemon, Docker, Python, Niri, "
                    "Wayland, API, front-end, back-end, output.")
# O que o Whisper inventa quando o dedo segura o orbe e ninguém fala.
FANTASMAS = {"obrigado", "obrigada", "muito obrigado", "obrigado por assistir", "e ai",
             "legendas pela comunidade amara.org", "inscreva-se", "inscreva-se no canal", "tchau"}
FALA_MIN_S = 0.4              # menos que isto segurando é toque, não fala
FALA_MIN_RMS = 150            # abaixo disto o relógio só mandou silêncio
TOQUE_DUPLO_S = 0.45          # dois toques curtos dentro disto travam a sessão


def filhos_morrem_junto() -> None:
    """No Windows, o agente vem numa cadeia (npx.cmd → node → cmd → node) e o
    terminate() só leva o primeiro elo; sem isto, cada execução deixava a
    cadeia órfã. Um job com "matar ao fechar" leva todos os descendentes
    quando este processo sai, do jeito que for."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class Basico(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Estendido(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basico), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    info = Estendido()
    info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    # 9 = JobObjectExtendedLimitInformation; o handle do job fica aberto até o processo sair
    if not (job and k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            and k.AssignProcessToJobObject(job, k.GetCurrentProcess())):
        LOG.warning("sem job do Windows (erro %d): o agente pode ficar órfão ao sair", ctypes.get_last_error())


def carregar_env(arquivo: Path) -> None:
    """Chaves de um .env para o ambiente, sem passar por cima do que já está lá."""
    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for linha in linhas:
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def rms(pcm: bytes) -> float:
    """Volume médio de um trecho s16le (o audioop saiu do Python 3.13)."""
    a = array.array("h")
    a.frombytes(pcm[:len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    return math.sqrt(sum(x * x for x in a) / len(a)) if a else 0.0


def transcrever(pcm: bytes, modelo: str, idioma: str) -> str:
    """A fala do relógio (s16le mono 16 kHz) em texto, pelo Groq Whisper."""
    chave = os.environ.get("GROQ_API_KEY", "")
    if not chave:
        LOG.error("GROQ_API_KEY não definida: sem transcrição")
        return ""
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(relogio.TAXA)
        # o Whisper turbo come os primeiros 200 a 300 ms: silêncio na frente salva a primeira sílaba
        w.writeframes(b"\x00" * int(relogio.TAXA * 0.30) * 2 + pcm)
    try:
        import requests
        r = requests.post(
            GROQ_URL, headers={"Authorization": f"Bearer {chave}"},
            files={"file": ("fala.wav", wav.getvalue(), "audio/wav")},
            data={"model": modelo, "language": idioma, "response_format": "json",
                  "temperature": 0.0, "prompt": GROQ_VOCABULARIO},
            timeout=30)
        r.raise_for_status()
        texto = (r.json().get("text") or "").strip()
    except Exception as e:
        LOG.error("Groq: %s", e)
        return ""
    norma = re.sub(r"[^\w\s.@-]", "", texto.lower()).strip(" .-")
    if len(norma) <= 2 or norma in FANTASMAS:
        LOG.info("transcrição descartada (fantasma do Whisper): %r", texto)
        return ""
    return texto


def encerrar(agente) -> None:
    """Fecha o agente e, no Windows, a cadeia inteira de processos dele."""
    proc = getattr(agente, "proc", None)
    if os.name == "nt" and proc is not None and proc.poll() is None:
        import subprocess
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    agente.fechar()


def frases(buf: str) -> tuple:
    """Frases completas e o resto que ainda não fechou (o _take_sentences do daemon)."""
    prontas = []
    while True:
        m = re.search(r"^(.{2,}?[.!?…]+)(?:\s+|$)", buf, re.S)
        if not m:
            return prontas, buf
        if m.group(1).strip():
            prontas.append(m.group(1).strip())
        buf = buf[m.end():]


class _Cano:
    """Faz as vezes do pw-cat para o Worker: o que ele escreve vai para o relógio."""

    def __init__(self, voz, taxa: int):
        self._voz = voz
        self._taxa = taxa
        self.stdin = self

    def write(self, pcm: bytes):
        self._voz.saiu(pcm, self._taxa)

    def flush(self):
        pass

    def close(self):
        pass

    def poll(self):
        return 0                  # não há processo para o _kill_play matar

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class Voz(tts.Worker):
    """A síntese do orbe (hermes_voice_tts.py) com o relógio no lugar do pw-cat."""

    def __init__(self, ponte):
        super().__init__()
        self._ponte = ponte
        self.segundos = 0.0       # quanto áudio já foi para o relógio neste turno
        self._taxa = 0
        self.vale = lambda: True  # a frase em síntese ainda é do turno em andamento?

    def _open_play(self, rate: int):
        self._kill_play()
        cano = _Cano(self, rate)
        with self._play_lock:
            self._play = cano
        return cano

    def _level(self, pcm: bytes):
        pass                      # o relógio mede o nível no que ele mesmo toca

    def _feed(self, play, raw: bytes) -> bool:
        # interrompida, a síntese em curso para de ler o provedor
        return self.vale() and super()._feed(play, raw)

    def _config(self) -> dict:
        if tts.JARVIS_CFG.exists():
            return tts._jarvis_tts()
        # sem o perfil do Hermes nesta máquina o worker reclamaria no stderr a
        # cada frase; valem os padrões dele e as escolhas do config.json
        with contextlib.redirect_stderr(io.StringIO()):
            return tts._jarvis_tts()

    def saiu(self, pcm: bytes, taxa: int):
        if self.cancel.is_set() or not pcm or not self.vale():
            return
        if self.segundos == 0.0 or taxa != self._taxa:
            self._taxa = taxa
            self._ponte.publicar(f"voz {taxa}")
            self._ponte.publicar("state speaking")
        self.segundos += len(pcm) / 2 / taxa
        self._ponte.falar(pcm)

    def piper(self, text: str, modelo: str = tts.PIPER_MODEL) -> bool:
        """A voz local: o wav do Piper vai para o relógio em vez do pw-play."""
        import subprocess
        import tempfile
        if not Path(tts.PIPER_BIN).exists() or not Path(modelo).exists():
            return False
        arq = os.path.join(tempfile.gettempdir(), f"orbe-pulso-{os.getpid()}.wav")
        try:
            r = subprocess.run([tts.PIPER_BIN, "--model", modelo, "--output_file", arq],
                               input=text, text=True, capture_output=True, timeout=12)
            if r.returncode != 0 or not os.path.exists(arq):
                return False
            with wave.open(arq, "rb") as w:
                cano = self._open_play(w.getframerate())
                while not self.cancel.is_set():
                    bloco = w.readframes(4096)
                    if not bloco:
                        break
                    cano.write(bloco)
            return True
        finally:
            try:
                os.unlink(arq)
            except OSError:
                pass

    def falar(self, texto: str) -> bool:
        """Uma frase: o provedor da config e as mesmas quedas do Worker.say()."""
        texto = tts.clean(texto)
        if not texto:
            return True
        cfg = self._config()
        provedor = cfg["provider"]
        ok = False
        try:
            if provedor == "gemini":
                ok = self.gemini(texto, cfg["gemini_model"], cfg["gemini_voice"])
            elif provedor == "piper":
                ok = self.piper(texto, cfg.get("piper_voice") or tts.PIPER_MODEL)
            else:
                ok = self.xai(texto, cfg["xai_voice"], cfg["xai_language"])
        except Exception as e:
            LOG.info("voz: %s falhou (%s)", provedor, e)
        if not ok and not self.cancel.is_set() and provedor not in ("gemini", "piper"):
            try:
                ok = self.gemini(texto, cfg["gemini_model"], cfg["gemini_voice"])
            except Exception as e:
                LOG.info("voz: gemini falhou (%s)", e)
        if not ok and not self.cancel.is_set() and provedor != "piper":
            try:
                ok = self.piper(texto, cfg.get("piper_voice") or tts.PIPER_MODEL)
            except Exception as e:
                LOG.info("voz: piper falhou (%s)", e)
        return ok or self.cancel.is_set()


class Pulso:
    def __init__(self, cfg: dict, pasta: str, token: str, host: str = "0.0.0.0"):
        self.cfg = cfg
        self.pasta = pasta
        self.ponte = relogio.PonteRelogio(
            int(cfg["relogio"]["porta"]), token, ao_controle=self._toque, ao_comando=self._comando,
            ao_quadro=self._quadro, host=host, ao_fala_fim=self._fala_fim, voz=True)
        self.voz = Voz(self.ponte)
        self.agente = None
        self._trava_agente = threading.Lock()
        self._instruido = False
        # cada interrupção muda a geração: o que era de antes se cala sozinho
        self._ger = 0
        self._trava = threading.Lock()
        self._fala = bytearray()          # o que o relógio captou com o dedo no orbe
        self._gravando = False
        # sessão aberta sem dedo (um toque, o live, a sacudida): o relógio manda o
        # microfone enquanto o orbe ouve, e a fala abre pelo volume e fecha no silêncio
        self._escuta = bytearray()
        self._escuta_fala = False
        self._escuta_voz = 0              # quadros seguidos com voz
        self._escuta_calado = 0           # quadros seguidos sem voz, já falando
        self._escuta_antes: list[bytes] = []
        self._quadros = 0
        self._toque_curto_t = 0.0
        self._visivel = False
        self._travado = False
        self._ocupado = False             # turno em andamento: o orbe não some
        self._ocioso = None
        self._fila_voz = queue.Queue()    # (frase | None = fim do turno, geração)
        self._tocou = threading.Event()   # o relógio avisou que a voz acabou

    # ── vida ──

    def rodar(self) -> bool:
        if not self.ponte.iniciar():
            return False
        threading.Thread(target=self._falador, name="voz", daemon=True).start()
        threading.Thread(target=self._aquecer, daemon=True).start()
        return True

    def _aquecer(self):
        """O agente sobe antes da primeira fala (o Claude por ACP leva alguns segundos)."""
        try:
            self._agente_pronto()
        except Exception as e:
            LOG.warning("agente indisponível: %s", e)

    # ── o orbe no relógio ──

    def _mostrar(self, estado: str):
        self._visivel = True
        self.ponte.publicar(f"state {estado}")
        self._agendar_sumico()

    def _sumir(self):
        self._visivel = False
        self._travado = False
        self.ponte.publicar("hold 0")
        self.ponte.publicar("hide")

    def _agendar_sumico(self, espera: float = 0.0):
        """Sem fala nem toque, o orbe volta a esperar (o sessao_ociosa_s do daemon)."""
        if self._ocioso is not None:
            self._ocioso.cancel()
        if self._travado:
            return
        s = espera or float(self.cfg["conversa"]["sessao_ociosa_s"])
        self._ocioso = threading.Timer(s, self._talvez_sumir)
        self._ocioso.daemon = True
        self._ocioso.start()

    def _talvez_sumir(self):
        if self._visivel and not self._travado and not self._ocupado and not self._gravando:
            self._sumir()

    def _interromper(self):
        """Cala a voz e larga o turno em andamento (o agente recebe session/cancel)."""
        with self._trava:
            self._ger += 1
        self._ocupado = False             # o turno largado não segura mais o orbe na tela
        self.voz.cancel.set()
        while True:
            try:
                self._fila_voz.get_nowait()
            except queue.Empty:
                break
        self._tocou.set()
        self.ponte.publicar("voz corta")
        self.ponte.publicar("level 0")

    # ── o que vem do relógio (thread da ponte: nada aqui pode demorar) ──

    def _toque(self, linha: str):
        if linha == "touch down":
            self._interromper()
            self._escuta_parar()          # o dedo assume a fala
            self._fala = bytearray()
            self._quadros = 0
            self._gravando = True
            self.ponte.publicar("show listening" if not self._visivel else "state listening")
            self._visivel = True
            if self._ocioso is not None:
                self._ocioso.cancel()
            return
        if not self._gravando:
            return
        self._gravando = False
        pcm, self._fala = bytes(self._fala), bytearray()
        if len(pcm) / 2 / relogio.TAXA >= FALA_MIN_S:
            self._ocupado = True
            threading.Thread(target=self._turno, args=(pcm, None, self._ger), daemon=True).start()
            return
        # toque curto (ou dedo no orbe sem fala): só interrompe; dois seguidos travam a sessão
        agora = time.monotonic()
        if agora - self._toque_curto_t < TOQUE_DUPLO_S:
            self._toque_curto_t = 0.0
            self._travado = not self._travado
            self.ponte.publicar("hold 1" if self._travado else "hold 0")
        else:
            self._toque_curto_t = agora
        self._mostrar("listening")

    def _quadro(self, pcm: bytes):
        if not self._gravando:
            if self._visivel and not self._ocupado:
                self._ouvir(pcm)
            return
        if len(self._fala) < float(self.cfg["toque"]["gravacao_max_s"]) * relogio.TAXA * 2:
            self._fala += pcm
        self._quadros += 1
        if self._quadros % 2 == 0:        # ~17 por segundo: o orbe mexe com a voz de quem fala
            self.ponte.publicar(f"mic {min(1.0, rms(pcm) / 32768.0 * 12.0):.3f}")

    def _ouvir(self, pcm: bytes):
        """A fala da sessão aberta sem dedo, com o critério do daemon (config
        conversa): fala_quadros seguidos acima de fala_rms abrem, silencio_fim_s
        abaixo fecham, gravacao_max_s corta."""
        c = self.cfg["conversa"]
        voz = rms(pcm) >= float(c["fala_rms"])
        if not self._escuta_fala:
            # os quadros que confirmam a voz e 300 ms antes deles: o começo da fala não se perde
            self._escuta_antes = (self._escuta_antes + [pcm])[-(int(c["fala_quadros"]) + 10):]
            self._escuta_voz = self._escuta_voz + 1 if voz else 0
            if self._escuta_voz >= int(c["fala_quadros"]):
                self._escuta_fala = True
                self._escuta = bytearray(b"".join(self._escuta_antes))
                self._escuta_calado = 0
                if self._ocioso is not None:
                    self._ocioso.cancel()
            return
        self._escuta += pcm
        self._escuta_calado = 0 if voz else self._escuta_calado + 1
        dur = len(self._escuta) / 2 / relogio.TAXA
        if (self._escuta_calado * len(pcm) / 2 / relogio.TAXA < float(c["silencio_fim_s"])
                and dur < float(c["gravacao_max_s"])):
            return
        fala = bytes(self._escuta)
        self._escuta_parar()
        self._ocupado = True
        threading.Thread(target=self._turno, args=(fala, None, self._ger), daemon=True).start()

    def _escuta_parar(self):
        self._escuta = bytearray()
        self._escuta_fala = False
        self._escuta_voz = self._escuta_calado = 0
        self._escuta_antes = []

    def _comando(self, op: str):
        if op == "toggle":
            op = "dismiss" if self._visivel else "trigger"
        if op == "trigger":
            self._escuta_parar()
            self.ponte.publicar("clear")
            self._mostrar("listening")
        elif op == "interromper":
            # o toque curto contado no relógio: cala e volta a ouvir
            self._interromper()
            self._escuta_parar()
            self._mostrar("listening")
        elif op in ("dismiss", "encerrar"):
            self._interromper()
            self._escuta_parar()
            self._ocupado = False
            self._sumir()
            if op == "encerrar" and self.cfg["agente"]["tipo"] == "claude":
                # três toques: com o Claude, a sessão dele fecha também (a do
                # orbe em tela; as abertas à mão, sem o canal, ficam)
                alvo = self._alvo()
                pid = canal.encerrar(max(alvo, 0)) if alvo != 0 else 0
                LOG.info("encerrar: Claude %s", f"fechado (pid {pid})" if pid else "já não tinha sessão")
        elif op in ("hold", "release"):
            self._travado = op == "hold"
            self.ponte.publicar("hold 1" if self._travado else "hold 0")
            if self._visivel:
                self._agendar_sumico()

    def _fala_fim(self):
        self._tocou.set()

    # ── o agente ──

    def _chave(self) -> str:
        a = self.cfg["agente"]
        return "|".join(("pulso", a["tipo"], a["perfil"] if a["tipo"] == "hermes" else "",
                         a["comando"] if a["tipo"] == "comando" else "", self.pasta))

    def _alvo(self) -> int:
        """A sessão do Claude na vaga do orbe em tela no relógio: o pid, 0 com a
        vaga livre, -1 sem vaga (relógio que não diz, ou orbe de outro agente)."""
        vaga = self.ponte.vaga()
        return self.ponte.sessao_da_vaga(vaga) if vaga >= 0 else -1

    def _agente_pronto(self):
        """Agente vivo e com sessão; sobe, ou reinicia retomando a conversa (como no daemon)."""
        with self._trava_agente:
            ag = self.agente
            a = self.cfg["agente"]
            alvo = self._alvo() if a["tipo"] == "claude" else -1
            if ag is not None and ag.vivo() and ag.sessao and getattr(ag, "alvo", 0) == max(alvo, 0):
                return ag
            if ag is not None:
                encerrar(ag)
                self.agente = None
            t0 = time.monotonic()
            if a["tipo"] == "claude":
                # sessão já aberta no terminal: nada a subir (daqui não se abre uma)
                if alvo == 0:
                    raise acp.ErroACP("nenhuma sessão do Claude neste orbe: abra uma no computador")
                ag = sessao.agente(max(alvo, 0))
            else:
                argv, extra = acp.comando(a)
                argv[0] = shutil.which(argv[0]) or argv[0]      # no Windows o npx é npx.cmd
                env = dict(os.environ)
                env.update(extra)
                env.pop("HERMES_HOME", None)
                ag = acp.AgenteACP(argv, env, cwd=self.pasta)
            try:
                ag.iniciar()
                estado = vcfg.ler_estado()
                retomar = estado.get("sessao") if estado.get("chave") == self._chave() else None
                ag.abrir_sessao(retomar)
                if a["modelo"]:
                    try:
                        ag.definir_modelo(a["modelo"])
                    except acp.ErroACP as e:
                        LOG.warning("modelo %s recusado (%s)", a["modelo"], e)
            except Exception:
                encerrar(ag)
                raise
            self.agente = ag
            # a conversa retomada já recebeu a instrução de voz no primeiro pedido
            self._instruido = bool(retomar) and ag.sessao == retomar
            info = ag.info.get("agentInfo") or {}
            LOG.info("agente pronto em %.1fs: %s, sessão %s (%s)%s", time.monotonic() - t0,
                     info.get("title") or info.get("name") or acp.NOMES.get(a["tipo"], a["tipo"]),
                     ag.sessao, "retomada" if self._instruido else "nova",
                     f", em {ag.cwd}" if ag.cwd else "")
            try:
                vcfg.gravar_estado({"chave": self._chave(), "sessao": ag.sessao,
                                    "agente": info.get("title") or info.get("name") or "",
                                    "modelos": ag.modelos, "modelo_atual": ag.modelo_atual})
            except OSError:
                pass
            return ag

    def _turno(self, pcm, texto, ger: int):
        """Uma fala, do áudio à resposta. Roda na sua thread; a geração diz se ainda vale."""
        p = self.ponte
        try:
            p.publicar("state thinking")
            if texto is None:
                v = self.cfg["voz"]
                # dedo no orbe sem fala: o relógio só mandou silêncio, nem vai ao Groq
                texto = "" if rms(pcm) < FALA_MIN_RMS else \
                    transcrever(pcm, str(v["stt_modelo"]), str(v["stt_idioma"]) or "pt")
            if ger != self._ger:
                return
            if not texto:
                self._ocupado = False
                self._mostrar("listening")
                return
            LOG.info("fala: %s", texto)
            p.publicar("line " + texto[:200])
            p.publicar("state thinking")
            resposta = self._perguntar(texto, ger)
            if ger != self._ger:
                return
            LOG.info("resposta: %s", resposta[:300] if resposta else "(nenhuma)")
            self._fila_voz.put((None, ger))       # o falador fecha o turno
        except Exception:
            LOG.exception("turno")
            if ger == self._ger:
                self._ocupado = False
                self._mostrar("listening")

    def _perguntar(self, texto: str, ger: int) -> str:
        """Pergunta ao agente. O texto vai à voz frase a frase; o pensamento e as
        ferramentas vão para o orbe, nunca para a voz (o _ask_hermes do daemon)."""
        p = self.ponte
        a = self.cfg["agente"]
        self.voz.segundos = 0.0
        self._tocou.clear()
        try:
            ag = self._agente_pronto()
        except Exception as e:
            LOG.warning("agente indisponível: %s", e)
            p.publicar("line " + f"Agente indisponível: {e}"[:200])
            return ""
        pedido = texto
        instrucao = (a.get("instrucao_voz") or "").strip()
        # o Hermes usa o SOUL do perfil; o canal do Claude manda a instrução ao conectar
        if a["tipo"] not in ("hermes", "claude") and instrucao and not self._instruido:
            pedido = f"{instrucao}\n\n{texto}"
            self._instruido = True

        partes = []
        frase = [""]
        pensado = [""]
        vistas = set()

        def ao_texto(t: str):
            if ger != self._ger:
                return
            partes.append(t)
            frase[0] += t
            prontas, frase[0] = frases(frase[0])
            for f in prontas:
                self._fila_voz.put((f, ger))

        def ao_pensamento(t: str):
            if ger != self._ger:
                return
            if not pensado[0]:
                p.publicar("state thinking")
            pensado[0] += t
            while "\n" in pensado[0] or len(pensado[0]) > 160:
                corte = pensado[0].find("\n")
                corte = corte if 0 <= corte <= 160 else 160
                linha, pensado[0] = pensado[0][:corte].strip(), pensado[0][corte:].lstrip("\n")
                if linha:
                    p.publicar("line " + linha[:200])
            if not pensado[0]:
                pensado[0] = " "

        def a_ferramenta(titulo: str, _status: str):
            if ger != self._ger:
                return
            p.publicar("state tools")
            # no relógio não há terminal para acompanhar: o nome da ferramenta vira linha
            titulo = " ".join((titulo or "").split())
            if titulo and titulo != "claude" and titulo not in vistas:
                vistas.add(titulo)
                p.publicar("line " + titulo[:200])

        pulso = self

        class _Parar:
            @staticmethod
            def is_set() -> bool:
                return pulso._ger != ger

        try:
            # o daemon dá 120 s aos agentes ACP; um agente de código no relógio leva mais
            teto = 120.0 if a["tipo"] in ("hermes", "opencode", "gemini") else 600.0
            fim = ag.perguntar(pedido, ao_texto, ao_pensamento, a_ferramenta, parar=_Parar(), teto=teto)
            if fim not in ("end_turn", "cancelled"):
                LOG.info("turno terminou com %s", fim or "?")
        except acp.ErroACP as e:
            LOG.warning("agente: %s", e)
            if ger == self._ger:
                p.publicar("line " + str(e)[:200])
        if frase[0].strip() and ger == self._ger:
            self._fila_voz.put((frase[0].strip(), ger))
        return "".join(partes).strip()

    # ── a voz ──

    def _falador(self):
        """Sintetiza as frases em ordem e fecha o turno quando o relógio acaba de tocar."""
        p = self.ponte
        calado = []                       # frases do turno que ficaram sem voz
        while True:
            frase, ger = self._fila_voz.get()
            if ger != self._ger:
                calado.clear()
                continue
            if frase is not None:
                self.voz.cancel.clear()
                self.voz.vale = lambda g=ger: g == self._ger
                if not p.quer_voz() or not self.voz.falar(frase):
                    # sem voz (relógio com ela desligada, ou a síntese falhou): a resposta vira texto
                    calado.append(frase)
                    p.publicar("line " + frase[:200])
                continue
            # fim do turno
            espera = 0.0
            if self.voz.segundos > 0:
                p.publicar("voz fim")
                # o relógio avisa quando acaba de tocar; o teto cobre o aviso perdido
                self._tocou.wait(self.voz.segundos + 3.0)
            elif calado:
                espera = max(float(self.cfg["conversa"]["sessao_ociosa_s"]),
                             sum(len(f) for f in calado) / 14.0)     # tempo de ler no pulso
            calado.clear()
            if ger != self._ger:
                continue
            p.publicar("level 0")
            self._ocupado = False
            self._visivel = True
            p.publicar("state listening")
            self._agendar_sumico(espera)

    # ── sem o relógio na mão ──

    def dizer(self, texto: str):
        """Uma linha digitada vale por uma fala."""
        texto = texto.strip()
        if not texto:
            return
        self._interromper()
        self._ocupado = True
        self.ponte.publicar("show thinking" if not self._visivel else "state thinking")
        self._visivel = True
        threading.Thread(target=self._turno, args=(b"", texto, self._ger), daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description="Orbe de pulso: a ponte de fala do relógio, sem o desktop")
    ap.add_argument("--agente", choices=["hermes", "opencode", "gemini", "claude", "comando"],
                    help="agente desta execução (padrão: o da config)")
    ap.add_argument("--comando", help="linha de comando de um agente ACP (vale por --agente comando)")
    ap.add_argument("--perfil", help="perfil do Hermes")
    ap.add_argument("--pasta", default="", help="pasta em que o agente ACP trabalha (padrão: a do usuário)")
    ap.add_argument("--env", action="append", default=[], help="arquivo .env com as chaves, além de ~/.hermes/.env")
    ap.add_argument("--porta", type=int, default=0, help="porta da ponte (padrão: a da config)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    for fluxo in (sys.stdin, sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    filhos_morrem_junto()
    for arq in args.env:
        carregar_env(Path(arq).expanduser())
    vcfg.aplicar_chaves()                 # as do orbe (app) valem; as que faltam vêm do Hermes
    tts._load_env()                       # ~/.hermes/.env, o mesmo do daemon e do worker de voz

    cfg = vcfg.carregar()
    a = cfg["agente"]
    if args.comando:
        a["tipo"], a["comando"] = "comando", args.comando
    if args.agente:
        a["tipo"] = args.agente
    if args.perfil:
        a["perfil"] = args.perfil
    if args.porta:
        cfg["relogio"]["porta"] = args.porta
    pasta = str(Path(args.pasta).expanduser().resolve()) if args.pasta else os.path.expanduser("~")
    if not os.path.isdir(pasta):
        sys.exit(f"pasta não encontrada: {pasta}")

    token = relogio.token_da_config()
    pulso = Pulso(cfg, pasta, token)
    if not pulso.rodar():
        sys.exit(1)
    nome = acp.NOMES.get(a["tipo"], a["tipo"])
    print(f"Orbe de pulso no ar. Agente: {nome}" + (f" ({a['comando']})" if a["tipo"] == "comando" else ""))
    for ip in relogio.enderecos() or ["<ip desta máquina>"]:
        print(f"  servidor: {ip}:{cfg['relogio']['porta']}")
    print(f"  token:    {token}")
    for chave, para in (("GROQ_API_KEY", "transcrição"), ("GEMINI_API_KEY", "voz pelo Gemini")):
        if not os.environ.get(chave):
            print(f"  aviso: {chave} não definida ({para})")
    print("Segure o orbe no relógio para falar. Aqui, uma linha digitada vale por uma fala (Ctrl+C sai).")
    try:
        for linha in sys.stdin or ():
            pulso.dizer(linha)
        while True:                       # sem terminal (serviço): fica no ar
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        if pulso.agente is not None:
            encerrar(pulso.agente)


if __name__ == "__main__":
    main()
