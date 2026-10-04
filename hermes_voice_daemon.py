#!/opt/hermes-agent/venv/bin/python
"""
Hermes Voice Daemon v4 — Wake word "ei hermes" + comandos de voz.
Usa Groq Whisper API (não faster-whisper local) para transcrição.

Fluxo: VAD detecta fala sustentada → grava áudio → Groq transcreve →
       detecta "ei hermes" no texto → Hermes processa comando → TTS responde.

Uso:  hermes_voice_daemon.py [--model whisper-large-v3] [--device N]
       hermes_voice_daemon.py --install
       hermes_voice_daemon.py --test
"""

import argparse
import collections
import json
import logging
import os
import queue
import random
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

import numpy as np
import sounddevice as sd
import webrtcvad

sys.path.append("/opt/hermes-agent/venv/lib/python3.11/site-packages")
sys.path.insert(0, str(Path.home() / ".hermes/hermes-agent/venv/lib/python3.11/site-packages"))

HERMES_PROFILE_DIR = Path.home() / ".hermes" / "profiles" / "jarvis"

# Configuração do app (hermes_voice_app.py). Os padrões de lá são os valores
# que viviam aqui como constantes; o que o app grava sobrepõe. Antes o wake
# word vinha do wake_word: do perfil jarvis; agora é do app, que também
# escolhe o provedor.
import hermes_voice_acp as acp  # noqa: E402
import hermes_voice_config as vcfg  # noqa: E402
import hermes_voice_canal as canal  # noqa: E402

VCFG = vcfg.carregar()
_AT = VCFG["ativacao"]
AGENTE_CFG = VCFG["agente"]
# 0 = agente ACP sempre carregado; N = descarrega N min depois da sessão.
MANTER_MIN = float(AGENTE_CFG.get("manter_carregado_min") or 0)

# nenhum | openwakeword | sherpa | microwakeword
WAKE_PROVEDOR = str(_AT["provedor"])
OWW_MODEL = str(_AT["oww_modelo"])
OWW_THRESHOLD = min(max(float(_AT["limiar_oww"]), 0.0), 1.0)
OWW_CONFIRM = min(max(int(_AT["confirmacao"]), 1), 10)
OWW_FRAME = 1280  # 80ms @ 16kHz — igual à GUI
MWW_PY = str(Path.home() / ".hermes/mww-tf/.venv/bin/python")
MWW_BIN = str(Path(__file__).resolve().parent / "hermes_voice_mww.py")
MWW_MODEL = str(_AT["mww_modelo"])
LOGGER_WARN = []

# ── Constantes ──
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480
VAD_AGGRESSIVENESS = 3
# Abrir gravação exige SUSTAINED_SPEECH_FRAMES acima deste piso. Ambiente
# medido sustenta ~10-11 quadros em 1800, abaixo dos 15 exigidos; a fala do
# Davi sustenta 31 já em 2200. 1800 dá folga pra réplica falada mais baixa
# sem deixar o ruído da sala abrir gravação sozinho.
MIN_SPEECH_RMS = 1500
SUSTAINED_SPEECH_FRAMES = 12        # ~360ms pra abrir gravação (evita ruídos rápidos)
# Medido na fonte com AEC (hermes_aec_source), quadros de 30ms:
#   ambiente ocioso   RMS medio 109, p95 289, maximo 595
#   eco do proprio TTS RMS 176  (era 7958 no mic cru: 33 dB de atenuacao)
#   fala real          milhares
# Com o eco fora do sinal nao ha mais o que "gritar por cima", entao o piso
# cai de 5500 pra 2500 (~4x o pico do ambiente) e a sustentacao cai de 600ms
# pra 360ms, o mesmo criterio que o daemon ja usa pra "isto e uma fala".
INTERRUPT_SPEECH_FRAMES = 12        # ~360ms contínuos; teclado não acumula
# Piso de interrupção medido, não estimado. Maior sequência CONTÍNUA acima do
# piso, em quadros de 30ms (o barge-in exige 12):
#   piso 2500 -> eco 0, ambiente 4    fala do Davi tem mediana 2740
#   piso 2000 -> eco 1, ambiente 10
#   piso 1400 -> eco 2, ambiente 18   <- ambiente sozinho já dispararia
# Quem limita o piso é o AMBIENTE, não o eco: com AEC o eco não passa de 2
# quadros em nenhum piso testado. Em 2500 metade da fala dele ficava de fora
# (a interrupção que funcionou disparou raspando, em 2631).
INTERRUPT_MIN_RMS = 2000
MIN_UTTER_SPEECH_FRAMES = 12        # ~360ms de VAD pra mandar ao Groq
MIN_UTTER_RMS = 1000                # evita enviar áudio de silêncio/ruído para Groq

# Silero VAD decide "isto é voz" no lugar do webrtcvad. Medido em 2026-10-03:
# o ruído da sala no Mic1 cru tinha RMS mediano 1730, acima do piso de 1500,
# então o piso não barrava nada e o webrtcvad sozinho decidia; ele marca
# música e ruído como fala, e as gravações iam até o teto de 12 s. O Silero é
# uma rede treinada para separar voz de ruído e música. v4: blocos de 512
# amostras a 16 kHz (32 ms), estado LSTM h/c carregado entre blocos.
SILERO_MODEL = str(Path.home() / ".hermes/cache/vad/silero_vad.onnx")
SILERO_CHUNK = 512
SILERO_THRESHOLD = 0.5              # padrão do Silero

# Fonte virtual criada pelo module-echo-cancel do PipeWire. O nome do nó é
# hermes_aec_source; o sounddevice enxerga pela node.description.
AEC_SOURCE_NODE = "hermes_aec_source"
AEC_SOURCE_DESC = "HermesMicAEC"

SILENCE_TIMEOUT = 0.90              # pausa intrafrase em PT > 0.55 cortava o início
RECORD_MAX_SEC = 12
SESSION_IDLE_SEC = 10.0             # orb some e a sessão de voz fecha
# Teto de segurança da sessão travada. Com AEC o risco de auto-disparo é baixo
# (medido: o eco não sustenta 2 quadros contínuos), mas um hold esquecido
# deixaria o microfone armado para sempre.
HOLD_MAX_SEC = 30 * 60.0
# Janela em que a fala nova ainda conta como continuação do pedido anterior,
# em vez de turno novo. Ver _emendar_pedido.
AMEND_WINDOW_SEC = 12.0
# Narração de ferramenta que não vale falar em voz alta. Encolhido: os verbos
# soltos ("vou ", "busco ", "lendo ") engoliam resposta legítima, porque o
# Jarvis anuncia o que vai fazer em português normal ("Vou puxar o tempo
# agora"). Sobrou o que é jargão de terminal, que nunca é fala natural.
_NARRATE_RE = re.compile(
    r"^(dry-run|pedido explícito|tem comando|aqui estão todos|"
    r"executando comando|rodando comando)\b",
    re.I,
)
# Travar e soltar a sessão por voz. A dispensa já é decidida aqui no daemon,
# sem passar pelo agente; a trava ("fica", "segura") passava pela skill
# voice-orb-hold, que depende de o agente ter terminal e lembrar da skill, e
# na prática não disparava. Agora é o espelho da dispensa.
_HOLD_RE = re.compile(
    r"\b(fica( a[ií])?|fica comigo|fica aberto|fica ligado|n[aã]o some|n[aã]o desliga|"
    r"segura( a sess[aã]o| a[ií])?|me espera|espera a[ií]|continua ouvindo|trava( a[ií])?)\b",
    re.I,
)
_RELEASE_RE = re.compile(
    r"\b(pode soltar|solta( a sess[aã]o| a[ií])?|destrava|volta ao normal|n[aã]o precisa (mais )?segurar)\b",
    re.I,
)
_DISMISS_RE = re.compile(
    r"\b(cala a boca|cala boca|cala-te|tchau|até logo|ate logo|"
    r"dispensa(?:do)?|pode ir|vai embora|para de falar|sil[eê]ncio|"
    r"quieto|pode desligar|xiu|shiu|chega)\b",
    re.I,
)

# ElevenLabs TTS (fallback: Piper)
ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
ELEVENLABS_API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# Piper TTS (fallback)
PIPER_BIN = "/opt/hermes-agent/venv/bin/piper"
PIPER_MODEL = str(Path.home() / ".hermes/piper_models/pt_BR-dii-high.onnx")

# ── Carrega variáveis de ambiente do .env do Hermes ──
_HERMES_ENV = Path.home() / ".hermes" / ".env"
if _HERMES_ENV.exists():
    with open(_HERMES_ENV) as f:
        for line in f:
            line = line.strip()
            if line.startswith("GROQ_API_KEY="):
                os.environ.setdefault("GROQ_API_KEY", line.split("=", 1)[1].strip("\"'"))
            elif line.startswith("ELEVENLABS_API_KEY=") and not os.environ.get("ELEVENLABS_API_KEY"):
                os.environ["ELEVENLABS_API_KEY"] = line.split("=", 1)[1].strip("\"'")
            elif line.startswith("GEMINI_API_KEY=") and not os.environ.get("GEMINI_API_KEY"):
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip("\"'")
            elif line.startswith("GOOGLE_API_KEY=") and not os.environ.get("GOOGLE_API_KEY"):
                os.environ["GOOGLE_API_KEY"] = line.split("=", 1)[1].strip("\"'")

MAC = vcfg.MAC

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"

# HERMES_VOICE_DEBUG=1 liga o rastro de nível no estado listening.
DEBUG_LEVELS = os.environ.get("HERMES_VOICE_DEBUG") == "1"

LOG = logging.getLogger("hermes-voice")


class _SemMixer(Exception):
    """Plataforma sem wpctl/pactl."""


def _resample_frame(frame, output_length: int):
    """Converte um bloco na taxa nativa do dispositivo para um quadro de 16 kHz.

    Clonado de tools/wake_word.py::_resample_audio_frame do Hermes — o mesmo
    caminho que a orelhinha da GUI usa. A diferença que importa é MÉDIA POR
    JANELA (np.add.reduceat), não decimação: decimar joga fora energia e
    produz aliasing, e o front-end de melspectrogram do openWakeWord passa a
    ver características diferentes das do treino. Mesmo modelo e mesmo
    limiar, mas o áudio não é o mesmo áudio.

    O daemon abria o stream direto em 16 kHz e deixava o PortAudio/ALSA
    converter, o que não dá controle sobre esse detalhe.
    """
    source = np.asarray(frame, dtype=np.float64).reshape(-1)
    if source.size == output_length:
        return np.asarray(frame, dtype=np.int16).reshape(-1)
    if source.size == 0:
        return np.zeros(output_length, dtype=np.int16)
    if source.size > output_length:
        edges = np.linspace(0, source.size, output_length + 1, dtype=np.int64)
        values = np.add.reduceat(source, edges[:-1]) / np.diff(edges)
    else:
        # Dispositivos de taxa mais baixa precisam de interpolação pra chegar
        # ao tamanho de quadro que todo motor de wake word espera.
        pos = np.arange(source.size, dtype=np.float64)
        alvo = np.linspace(0, source.size - 1, output_length)
        values = np.interp(alvo, pos, source)
    return np.clip(values, -32768, 32767).astype(np.int16)


class SileroVad:
    """Probabilidade de voz por quadro de 30 ms, com o estado da rede contínuo.

    O quadro do daemon (480 amostras) não casa com o bloco do Silero (512):
    as amostras acumulam e cada bloco completo atualiza a probabilidade. O
    quadro herda a última, atrasada no máximo 32 ms.
    """

    def __init__(self, path: str = SILERO_MODEL):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(
            path, sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self):
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._buf = np.zeros(0, dtype=np.float32)
        self.prob = 0.0

    def feed(self, frame: bytes) -> float:
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self._buf = np.concatenate([self._buf, x])
        while len(self._buf) >= SILERO_CHUNK:
            bloco, self._buf = self._buf[:SILERO_CHUNK], self._buf[SILERO_CHUNK:]
            out, self._h, self._c = self.sess.run(None, {
                "input": bloco[None, :], "sr": self._sr,
                "h": self._h, "c": self._c,
            })
            self.prob = float(np.asarray(out).reshape(-1)[0])
        return self.prob


class OpenWakeWordEar:
    """Mesmo motor da GUI: openWakeWord + ei_hermes_pt.onnx, frames de 80ms."""

    def __init__(self):
        from openwakeword.model import Model
        self.model = Model(wakeword_models=[OWW_MODEL], inference_framework="onnx")
        self.buf = np.zeros(0, dtype=np.int16)
        self.streak = 0
        self.cool_until = 0.0

    def feed(self, frame: bytes) -> bool:
        if time.monotonic() < self.cool_until:
            return False
        self.buf = np.concatenate([self.buf, np.frombuffer(frame, dtype=np.int16)])
        if len(self.buf) > OWW_FRAME * 8:
            self.buf = self.buf[-OWW_FRAME:]
        fired = False
        while len(self.buf) >= OWW_FRAME:
            chunk, self.buf = self.buf[:OWW_FRAME], self.buf[OWW_FRAME:]
            scores = self.model.predict(chunk)
            mx = max(float(v) for v in scores.values()) if scores else 0.0
            if mx >= OWW_THRESHOLD:
                self.streak += 1
                if self.streak >= OWW_CONFIRM:
                    LOG.info("⚡ openWakeWord: ei hermes (score=%.3f frames=%d)",
                             mx, OWW_CONFIRM)
                    self.streak = 0
                    self.cool_until = time.monotonic() + 3.0
                    self.buf = np.zeros(0, dtype=np.int16)
                    try:
                        self.model.reset()
                    except Exception:
                        pass
                    fired = True
                    break
            else:
                self.streak = 0
        return fired


class SherpaEar:
    """sherpa-onnx: frase digitada, sem treino (o motor "sherpa" do Hermes).

    A frase é tokenizada na hora contra o BPE do modelo. Usa os .int8.onnx,
    metade da RAM dos float32, quando existem.
    """

    def __init__(self, pasta: str, frase: str, limiar: float):
        import sherpa_onnx
        from sherpa_onnx import text2token
        d = Path(pasta)
        toks = text2token([frase.strip().upper()], tokens=str(d / "tokens.txt"),
                          tokens_type="bpe", bpe_model=str(d / "bpe.model"))[0]
        kw = vcfg.RUNTIME / "hermes-voice-kws.txt"
        kw.write_text(" ".join(toks) + " @WAKE\n", encoding="utf-8")

        def arq(parte: str) -> str:
            achados = sorted(d.glob(f"{parte}-*.int8.onnx")) or sorted(d.glob(f"{parte}-*.onnx"))
            if not achados:
                raise RuntimeError(f"modelo sherpa sem {parte} em {d}")
            return str(achados[0])

        # Mesmo mapeamento do Hermes: 0.5 cai no 0.25 recomendado pelo sherpa.
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(d / "tokens.txt"), encoder=arq("encoder"), decoder=arq("decoder"),
            joiner=arq("joiner"), keywords_file=str(kw),
            keywords_threshold=0.05 + 0.4 * min(max(limiar, 0.0), 1.0), num_threads=1)
        self.stream = self.spotter.create_stream()
        self.cool_until = 0.0

    def feed(self, frame: bytes) -> bool:
        if time.monotonic() < self.cool_until:
            return False
        pcm = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self.stream.accept_waveform(SAMPLE_RATE, pcm)
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            if self.spotter.get_result(self.stream):
                self.spotter.reset_stream(self.stream)
                self.cool_until = time.monotonic() + 3.0
                return True
        return False


class MicroWakeWordEar:
    """microWakeWord em processo próprio (TensorFlow, venv mww-tf).

    hermes_voice_mww.py lê PCM s16le 16 kHz no stdin e escreve WAKE no stdout.
    É o provedor mais pesado em RAM, por causa do TensorFlow.
    """

    def __init__(self, modelo: str, limiar: float, confirma: int):
        env = dict(os.environ, MWW_MODEL=modelo, MWW_CUTOFF=str(limiar), MWW_STREAK=str(confirma))
        self.proc = subprocess.Popen([MWW_PY, MWW_BIN], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=env, close_fds=True)
        self._acordou = threading.Event()
        self.cool_until = 0.0
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        assert self.proc.stdout is not None
        for linha in self.proc.stdout:
            if linha.strip() == b"WAKE":
                self._acordou.set()

    def feed(self, frame: bytes) -> bool:
        if self.proc.poll() is not None or self.proc.stdin is None:
            return False
        try:
            self.proc.stdin.write(frame)
            self.proc.stdin.flush()
        except OSError:
            return False
        if not self._acordou.is_set():
            return False
        self._acordou.clear()
        if time.monotonic() < self.cool_until:
            return False
        self.cool_until = time.monotonic() + 3.0
        return True


# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
# Groq Whisper STT
# ═══════════════════════════════════════════
# O Whisper nunca devolve vazio: em ruído ele inventa uma frase curta. Qual
# frase depende do prompt — com a prosa antiga ("Transcrição estrita ... termos
# técnicos e empréstimos:") ele regurgitava o próprio prompt e saía
# "Tremendo a direção e empréstimos", que virava comando e ia buscar no cofre.
# Com lista pura de termos o fantasma volta a ser genérico, e genérico é um
# conjunto pequeno e fechado, que dá pra barrar por igualdade exata.
#
# Só entra aqui o que foi medido contra ruído real ou é fantasma documentado
# do Whisper. A comparação é por igualdade exata, nunca substring, e "tchau"
# fica de fora de propósito: sozinho é a dispensa canônica do orbe.
_WHISPER_PHANTOMS = {
    "obrigado", "obrigada", "muito obrigado", "obrigado por assistir",
    "e ai", "tremendo", "aprenda",
    "legendas pela comunidade", "amara.org",
    "legendas pela comunidade amara.org",
    "inscreva-se", "inscreva-se no canal",
    # Ruído de sala / eco residual sem AEC (medido no Mic1 cru).
    "t", "musica", "amanda", "hmm", "hum", "ah", "eh", "uh",
}


def _normalize_utterance(text: str) -> str:
    """Minúsculas, sem acento e sem pontuação de borda, pra comparar fantasma."""
    t = unicodedata.normalize("NFD", (text or "").strip().lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s.@-]", "", t)
    t = " ".join(t.split())
    # Pontuação só nas bordas: o ponto interno de "amara.org" sobrevive.
    return t.strip(".-")


def _is_whisper_phantom(text: str) -> bool:
    norm = _normalize_utterance(text)
    if not norm or norm in _WHISPER_PHANTOMS:
        return True
    # Uma letra / token minúsculo: ruído, não comando.
    if len(norm) <= 2 and " " not in norm:
        return True
    # Só pontuação: o modelo transcreveu silêncio.
    return not re.search(r"\w", norm)


# Atendimento ao wake. Curto e direto conforme especificação do perfil (Sem beep; Sim?).
# Vazio: a ativação não fala nada. O "Sim?" saía "SAM?" na voz do Gemini.
ACK_PHRASES: tuple[str, ...] = ()
# O atendimento não arma barge-in: não faz sentido interromper uma frase de
# 300 ms. O _tts_push compara por aqui, então basta a frase estar na tupla.
_ACK_NORMS = frozenset(_normalize_utterance(p) for p in ACK_PHRASES)


def _stt_provedor() -> str:
    """groq | gemini: o do app, ou o que tiver chave (Groq primeiro)."""
    p = STT_PROVEDOR
    if p in ("groq", "gemini"):
        return p
    if GROQ_API_KEY:
        return "groq"
    return "gemini" if _gemini_key() else "groq"


def _gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


_STT_GEMINI_PROMPT = (
    "Transcreva literalmente a fala deste áudio, no idioma falado. Responda só com "
    "a transcrição, sem aspas nem comentários. Se não houver fala, responda vazio."
)


def transcribe_gemini(wav_path: str) -> str:
    """Mesmo contrato do transcribe_groq, pelo Gemini (áudio inline).

    Para quem não tem chave do Groq: o Gemini já é a voz padrão do orbe, então
    a mesma chave cobre a ida e a volta. O filtro de fantasmas vale aqui
    também; o Gemini inventa menos em silêncio, mas não nunca.
    """
    key = _gemini_key()
    if not key:
        LOG.error("sem GROQ_API_KEY nem GEMINI_API_KEY para a transcrição")
        return ""
    try:
        import base64
        import requests
        audio = base64.b64encode(Path(wav_path).read_bytes()).decode()
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{STT_GEMINI_MODELO}:generateContent",
            headers={"x-goog-api-key": key},
            json={
                "contents": [{"parts": [
                    {"text": _STT_GEMINI_PROMPT + f" Idioma esperado: {STT_IDIOMA}."},
                    {"inline_data": {"mime_type": "audio/wav", "data": audio}},
                ]}],
                # sem thinkingConfig: os modelos novos recusam o thinkingBudget
                "generationConfig": {"temperature": 0.0},
            },
            timeout=30,
        )
        resp.raise_for_status()
        partes = (resp.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in partes if not p.get("thought")).strip().strip('"')
        if _is_whisper_phantom(text):
            LOG.info("STT descartado (fantasma): %r", text)
            return ""
        return text
    except Exception as e:
        LOG.error("Gemini STT: %s", e)
        return ""


def transcribe_groq(wav_path: str) -> str:
    """Envia WAV para Groq Whisper API, retorna texto transcrito."""
    if _stt_provedor() == "gemini":
        return transcribe_gemini(wav_path)
    if not GROQ_API_KEY:
        LOG.error("GROQ_API_KEY não definida")
        return ""

    try:
        import requests
        with open(wav_path, "rb") as f:
            files = {"file": f}
            data = {
                "model": GROQ_MODEL,
                "language": STT_IDIOMA,
                "response_format": "json",
                "temperature": 0.0,
                # Lista pura de vocabulário, sem frase em volta: prosa aqui
                # vira semente de alucinação (ver _WHISPER_PHANTOMS).
                "prompt": "Hermes, Jarvis, daemon, Docker, Python, "
                          + ("macOS, " if MAC else "Niri, Wayland, ")
                          + "API, front-end, back-end, output.",
            }
            resp = requests.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files=files,
                data=data,
                timeout=30,
            )
        resp.raise_for_status()
        result = resp.json()
        text = result.get("text", "").strip()
        if _is_whisper_phantom(text):
            LOG.info("STT descartado (fantasma do Whisper): %r", text)
            return ""
        return text
    except ImportError:
        LOG.error("requests não instalado. pip install requests")
        return ""
    except Exception as e:
        LOG.error("Groq API: %s", e)
        return ""


# ═══════════════════════════════════════════
# Gravador de Áudio (acionado por VAD)
# ═══════════════════════════════════════════
class Recorder:
    def __init__(self):
        self.chunks: list[bytes] = []
        self.flags: list[bool] = []         # is_speech de cada quadro
        self.silence_frames = 0
        self.speech_frames_recorded = 0
        self.has_spoken = False
        self.silence_limit = int(SILENCE_TIMEOUT / (FRAME_MS / 1000))
        self.startup_silence_limit = int(1.2 / (FRAME_MS / 1000))
        self.echo_skip_until = 0
        self.segurando = False   # dedo no orbe: silêncio não fecha a gravação
        self.por_toque = False   # aberta ou segurada pelo toque (teto maior)
        self.fim = False         # dedo solto: fecha no próximo quadro

    def feed(self, frame: bytes, is_speech: bool):
        self.chunks.append(frame)
        self.flags.append(is_speech)
        # Ignora eco do bipe (janela dinâmica ajustada após pre-roll)
        if len(self.chunks) < self.echo_skip_until:
            self.silence_frames += 1
            return
        if is_speech:
            self.speech_frames_recorded += 1
            if self.speech_frames_recorded >= MIN_UTTER_SPEECH_FRAMES:
                self.has_spoken = True
            self.silence_frames = 0
        else:
            self.silence_frames += 1

    def is_done(self) -> bool:
        if self.fim:
            return True
        if self.segurando:
            return False
        if not self.has_spoken:
            return self.silence_frames >= self.startup_silence_limit
        return self.silence_frames >= self.silence_limit

    @property
    def seconds(self) -> float:
        return len(self.chunks) * FRAME_MS / 1000.0

    def average_rms(self) -> float:
        if not self.chunks:
            return 0.0
        raw = b"".join(self.chunks)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(audio ** 2)))

    def voice_pcm(self) -> np.ndarray:
        """Só os quadros com voz: a impressão vocal não deve pesar o silêncio."""
        voz = [c for c, f in zip(self.chunks, self.flags) if f]
        return np.frombuffer(b"".join(voz or self.chunks), dtype=np.int16)

    def speech_ratio(self) -> float:
        n = len(self.chunks)
        if n == 0:
            return 0.0
        return self.speech_frames_recorded / n

    def save_wav(self) -> str | None:
        if not self.chunks:
            return None
        raw = b"".join(self.chunks)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            from scipy.io.wavfile import write as wav_write
            # Whisper-turbo descarta ~200–300ms iniciais. Pad de silêncio
            # recupera a primeira sílaba sem atrasar o VAD.
            pad = np.zeros(int(SAMPLE_RATE * 0.30), dtype=np.int16)
            audio = np.concatenate([pad, np.frombuffer(raw, dtype=np.int16)])
            wav_write(path, SAMPLE_RATE, audio)
            return path
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            return None


# ═══════════════════════════════════════════
# Áudio (bipes + TTS via Piper)
# ═══════════════════════════════════════════
def _gen_beep(path: str, freq: float, duration: float):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    data = (np.sin(2 * np.pi * freq * t) * 0.5 * 32767).astype(np.int16)
    from scipy.io.wavfile import write as wav_write
    wav_write(path, SAMPLE_RATE, data)

_gen_beep(str(vcfg.RUNTIME / "hv_beep_ack.wav"), 1100, 0.13)
_gen_beep(str(vcfg.RUNTIME / "hv_beep_done.wav"), 440, 0.12)


def _tocar_cmd(path: str) -> list[str]:
    """Toca um arquivo de áudio: pw-play no PipeWire, afplay no macOS."""
    return ["afplay", path] if MAC else ["pw-play", path]

HERMES_BIN = str(Path.home() / ".hermes/hermes-agent/venv/bin/hermes")
HERMES_PROFILE = "jarvis"
HERMES_SESSION = "Bot Chat"
HERMES_PATH = f"{Path.home()}/.hermes/hermes-agent/venv/bin:{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"
if MAC:
    # launchd entrega um PATH mínimo; os agentes (node, opencode, gemini)
    # costumam viver no Homebrew e nas pastas de usuário.
    HERMES_PATH = ":".join(dict.fromkeys(
        HERMES_PATH.split(":") + ["/opt/homebrew/bin", "/opt/homebrew/sbin",
                                  f"{Path.home()}/.opencode/bin", f"{Path.home()}/.bun/bin"]
        + os.environ.get("PATH", "").split(":")))
# sockets e barramento da sessão gráfica do usuário
RUNTIME = str(vcfg.RUNTIME)
# Orbe: Quickshell no Wayland; no macOS, uma janela PySide6 com o mesmo
# OrbeConteudo (orbe-qt/orbe_mac.py). Os dois desenham na GPU.
ORB_QML = str(Path(__file__).resolve().parent / "orbe-qt" / ("orbe_mac.py" if MAC else "orbe.qml"))
ORB_SOCK = f"{RUNTIME}/hermes-voice-orb.sock"
# Entrada de controle do daemon, uma linha por mensagem:
#   touch down | touch up      dedo no orbe (orbe-qt/orbe.qml)
#   relato {json}              trabalho despachado terminou (hermes_voice_despacho.py)
CTL_SOCK = f"{RUNTIME}/hermes-voice-ctl.sock"
# Toque mais curto que isto é só "interromper"; mais longo, o dedo segura a
# gravação aberta até ser solto, e pausa entre palavras não fecha nada.
TOQUE_SEGURAR_SEC = 0.35
TOQUE_DUPLO_SEC = 0.45    # dois toques curtos dentro disso travam a sessão
RECORD_MAX_TOQUE_SEC = 90.0

# Runtime oficial do Hermes: o venv/bin/hermes sobe no Python 3.11 e o
# hermes_bootstrap reexecuta no 3.14 (~1,1 s só nesse salto); o launcher
# publicado entrega o comando final direto, e o agente ACP sobe por ele.
HERMES_LAUNCHER = str(Path.home() / ".local/bin/hermes")
# O agente ACP leu .env e config ao subir. Se algum destes mudou depois, ele
# está velho: reinicia antes do próximo pedido, retomando a mesma conversa.
WARM_STALE_PATHS = (
    HERMES_PROFILE_DIR / "config.yaml",
    HERMES_PROFILE_DIR / ".env",
    Path.home() / ".hermes" / ".env",
    Path.home() / ".hermes" / "hermes-agent" / "install-stamp.json",
)


def _hermes_runtime() -> list[str] | None:
    """[python, -I, -c, bootstrap] do runtime oficial; None cai no HERMES_BIN."""
    try:
        out = subprocess.check_output(
            [HERMES_LAUNCHER, "--print-runtime-command", "--"],
            text=True, timeout=30, stderr=subprocess.DEVNULL,
        )
        cmd = json.loads(out)
        if (isinstance(cmd, list) and len(cmd) == 4
                and all(isinstance(c, str) for c in cmd)):
            return cmd
        LOG.warning("runtime do hermes em formato inesperado; usando %s", HERMES_BIN)
    except Exception as e:
        LOG.warning("runtime do hermes não resolvido (%s); usando %s", e, HERMES_BIN)
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def get_desktop_env():
    """Garante PATH + PipeWire/D-Bus para o unit systemd (PATH mínimo)."""
    env = os.environ.copy()
    env["HOME"] = str(Path.home())
    env["PATH"] = HERMES_PATH
    if MAC:
        # o player do TTS (hermes_voice_play.py) precisa do sounddevice daqui
        env["ORBE_PY"] = sys.executable
        return env
    env["XDG_RUNTIME_DIR"] = RUNTIME
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={RUNTIME}/bus"
    env["WAYLAND_DISPLAY"] = "wayland-1"
    env["XDG_SESSION_TYPE"] = "wayland"
    env["GDK_BACKEND"] = "wayland"
    return env


def _tts_child_env() -> dict:
    """Env do worker TTS: sem PIPEWIRE_NODE/PULSE_SOURCE (isso é só da captura)."""
    env = get_desktop_env()
    env.pop("PIPEWIRE_NODE", None)
    env.pop("PULSE_SOURCE", None)
    env["HERMES_HOME"] = str(Path.home() / ".hermes")
    env["HERMES_PROFILE"] = "jarvis"
    return env


def _tts_envelope(path: str, hop: float = 0.05) -> list:
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "16000", wav],
            capture_output=True, timeout=8,
        )
        if r.returncode != 0:
            return []
        from scipy.io import wavfile
        sr, data = wavfile.read(wav)
        data = data.astype(np.float32)
        if data.ndim > 1:
            data = data.mean(axis=1)
        n = max(1, int(sr * hop))
        lo = float(np.log(110.0))
        span = float(np.log(3500.0 / 110.0))
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        band = (freqs >= 90) & (freqs <= 5000)
        fb = freqs[band]
        win = np.hanning(n)
        out = []
        for i in range(0, len(data), n):
            seg = data[i:i + n]
            lvl = float(np.sqrt(np.mean(seg ** 2))) / 32768.0
            tone = 0.5
            if len(seg) == n and lvl > 1e-4:
                mag = np.abs(np.fft.rfft(seg * win))[band]
                s = float(mag.sum())
                if s > 1e-6:
                    cen = float((mag * fb).sum()) / s
                    tone = min(1.0, max(0.0, (float(np.log(max(cen, 110.0))) - lo) / span))
            out.append((lvl, tone))
        peak = max((l for l, _ in out), default=0.0) or 1.0
        return [(min(1.0, l / peak), t) for l, t in out]
    except Exception:
        return []
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass


_ORB_LOCK = threading.Lock()


def _compositor_ready() -> bool:
    if MAC:
        return True
    env = get_desktop_env()
    return os.path.exists(os.path.join(env["XDG_RUNTIME_DIR"], env["WAYLAND_DISPLAY"]))


def _sock_do_orbe(pid: int):
    """HERMES_ORB_SOCK do ambiente do processo; None quando usa o padrão."""
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return None
    for kv in env:
        if kv.startswith(b"HERMES_ORB_SOCK="):
            return kv.split(b"=", 1)[1].decode(errors="replace") or None
    return None


def _reap_orbs() -> None:
    """Mata orbes órfãos (socket ausente, daemon anterior morto sem limpar)."""
    me = os.getpid()
    try:
        # ps em vez de pgrep -a: o pgrep do macOS não tem -a
        out = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        if pid == me or "pgrep" in cmd or "pkill" in cmd:
            continue
        if ORB_QML not in cmd:
            continue
        if MAC and "--sock" in cmd:
            continue    # pré-visualização do app (socket próprio)
        if not MAC and _sock_do_orbe(pid) not in (None, ORB_SOCK):
            continue    # instância de outro socket (pré-visualização do app, teste)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


_ORB_CONN = None
_ORB_CONN_LOCK = threading.Lock()


def orb_cmd(line: str) -> None:
    """Fala com o orbe. Sobe o processo só na primeira chamada (zero idle).

    Uma conexão só, mantida aberta: o SocketServer do Quickshell guarda o
    objeto de cada conexão até o servidor desligar, e o level da fala chega a
    dezenas por segundo. Com o orbe morto, o AF_UNIX devolve EPIPE na hora,
    então a mensagem é reenviada por uma conexão nova em vez de se perder.
    """
    payload = (line.strip() + "\n").encode()

    def _send() -> bool:
        global _ORB_CONN
        with _ORB_CONN_LOCK:
            for _ in range(2):
                if _ORB_CONN is None:
                    try:
                        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        s.settimeout(0.12)
                        s.connect(ORB_SOCK)
                    except OSError:
                        return False
                    _ORB_CONN = s
                try:
                    _ORB_CONN.sendall(payload)
                    return True
                except OSError:
                    try:
                        _ORB_CONN.close()
                    except OSError:
                        pass
                    _ORB_CONN = None
            return False

    if _send():
        return
    op = line.split()[0] if line else ""
    if op not in ("show", "state", "warm"):
        return
    if not _ORB_LOCK.acquire(blocking=False):
        for _ in range(80):
            time.sleep(0.05)
            if _send():
                return
        return
    try:
        if _send():
            return
        if not _compositor_ready():
            LOG.warning("orbe: compositor ausente, não spawnar")
            return
        _reap_orbs()
        time.sleep(0.15)
        try:
            logf = open("/tmp/hermes-voice-orb.log", "ab", buffering=0)
            # no Mac o orbe morre junto com o daemon (--pai), como o hotkey
            # que ele registra
            argv = ([sys.executable, ORB_QML, "--pai", str(os.getpid())] if MAC
                    else ["/usr/bin/qs", "-p", ORB_QML])
            subprocess.Popen(
                argv,
                env=get_desktop_env(),
                stdout=logf,
                stderr=logf,
            )
        except Exception as e:
            LOG.warning("orbe spawn: %s", e)
            return
        for _ in range(80):
            time.sleep(0.05)
            if _send():
                return
        LOG.warning("orbe: socket não subiu após spawn")
    finally:
        _ORB_LOCK.release()


def _orb_boot() -> None:
    for _ in range(80):
        if _compositor_ready():
            orb_cmd("warm")
            return
        time.sleep(0.25)
    LOG.warning("orbe: compositor não apareceu no boot")


def frame_rms(frame: bytes) -> float:
    audio = np.frombuffer(frame, dtype=np.int16)
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


def play_beep(name: str):
    path = str(vcfg.RUNTIME / f"hv_beep_{name}.wav")
    if os.path.exists(path):
        try:
            # fire-and-forget: o beep não pode atrasar o resto do fluxo
            subprocess.Popen(
                _tocar_cmd(path),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=get_desktop_env(),
            )
        except Exception:
            pass

def speak(text: str):
    """
    Fala usando ElevenLabs TTS API (standalone, não-interruptível).
    Usada apenas em contextos fora do Daemon (ex: test_once).
    Fallback: Piper local se ElevenLabs falhar.
    """
    if not text:
        return
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    env = get_desktop_env()
    if api_key:
        try:
            import requests
            fd, mp3_out = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            resp = requests.post(
                ELEVENLABS_API_URL,
                headers={
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": api_key,
                },
                json={
                    "text": text.strip(),
                    "model_id": ELEVENLABS_MODEL_ID,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                timeout=30,
            )
            resp.raise_for_status()
            with open(mp3_out, "wb") as f:
                f.write(resp.content)
            if os.path.exists(mp3_out) and os.path.getsize(mp3_out) > 0:
                play_timeout = max(45, (len(text) // 10) + 30)
                subprocess.run(
                    _tocar_cmd(mp3_out),
                    capture_output=True, timeout=play_timeout, env=env
                )
            try:
                os.unlink(mp3_out)
            except OSError:
                pass
            return
        except ImportError:
            LOG.warning("ElevenLabs TTS: requests não instalado, fallback Piper")
        except Exception as e:
            LOG.warning("ElevenLabs TTS: %s, fallback Piper", e)
    else:
        LOG.warning("ELEVENLABS_API_KEY não encontrada, fallback Piper")

    # ── Fallback: Piper local ──
    wav_out = None
    try:
        fd, wav_out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        proc = subprocess.Popen(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", wav_out],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
        )
        proc.communicate(input=text.strip().encode("utf-8"), timeout=25)
        if os.path.exists(wav_out) and os.path.getsize(wav_out) > 0:
            play_timeout = max(45, (len(text) // 10) + 30)
            subprocess.run(_tocar_cmd(wav_out), capture_output=True, timeout=play_timeout, env=env)
    except Exception as e:
        LOG.warning("Piper TTS: %s", e)
    finally:
        if wav_out:
            try:
                os.unlink(wav_out)
            except OSError:
                pass


# ═══════════════════════════════════════════
# Detecção de Wake Word no texto
# ═══════════════════════════════════════════
def _fold_pt(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", (text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def detect_wake_word(text: str) -> str | None:
    """Aceita 'ei hermes' e as transcrições típicas do Groq: 'e aí, Hermes', 'E, E, Hermes'."""
    if not text:
        return None
    import difflib

    words = _fold_pt(text).split()
    if not words:
        return None
    collapsed = [words[0]]
    for w in words[1:]:
        if w != collapsed[-1]:
            collapsed.append(w)
    words = collapsed

    prefixes = {"ei", "e", "hey", "oi", "ok", "ai", "hi"}
    hermes_ok = {"hermes", "ermes", "herme"}
    window = min(6, len(words))
    hit = None
    for i in range(window):
        w = words[i]
        is_h = w in hermes_ok or (
            len(w) >= 5 and difflib.SequenceMatcher(None, w, "hermes").ratio() >= 0.82
        )
        if not is_h:
            continue
        prev = words[i - 1] if i >= 1 else ""
        if prev not in prefixes:
            continue
        hit = i
        break
    if hit is None:
        return None

    rest = words[hit + 1 :]
    while rest:
        w0 = rest[0]
        is_h = w0 in hermes_ok or (
            len(w0) >= 5 and difflib.SequenceMatcher(None, w0, "hermes").ratio() >= 0.82
        )
        if rest[0] in prefixes or is_h:
            rest = rest[1:]
            continue
        break
    cmd = " ".join(rest)
    LOG.info("Wake word detectada (tokens=%s). Comando: '%s'", words[: hit + 1], cmd)
    return cmd


def _strip_cli_footer(text: str) -> str:
    out = []
    for line in (text or "").splitlines():
        ll = line.strip().lower()
        if not ll:
            continue
        if (ll.startswith(("resume this session", "session:", "title:", "duration:",
                           "messages:", "hermes --resume", "hermes -c"))
                or "resume this session" in ll
                or "resumed session" in ll
                or "user message" in ll
                or "total messages" in ll
                or "comando processado" in ll):
            break
        out.append(line.strip())
    return "\n".join(out).strip()


def _take_sentences(buf: str) -> tuple[list[str], str]:
    """Extrai frases completas; o resto fica no buffer."""
    out = []
    while True:
        m = re.search(r"^(.{2,}?[.!?…]+)(?:\s+|$)", buf, re.S)
        if not m:
            break
        s = m.group(1).strip()
        if s:
            out.append(s)
        buf = buf[m.end():]
    return out, buf


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?=]*[A-Za-z]"
    r"|\x1b\][^\x07]*\x07"
    r"|\x1b[()][0-9A-Za-z]"
    r"|\x1b[NO]"
)
_CSI_LEFTOVER = re.compile(r"\[\?[0-9;]*[A-Za-z]")


def _scrub_cli(text: str) -> str:
    t = _ANSI_RE.sub("", text or "")
    t = _CSI_LEFTOVER.sub("", t)
    t = re.sub(r"[\u2500-\u257F╭╮╰╯│─┌┐└┘┊╌╎]+", " ", t)
    t = "".join(ch for ch in t if ch >= " " or ch in "\n")
    return " ".join(t.split())


def _clean_tts(text: str) -> str:
    t = _scrub_cli(text)
    t = re.sub(r"[💻⚙🔧📁🔍📦🚀⏳].*?(?:…|\.\.\.|$)", "", t)
    return " ".join(t.split())


# ═══════════════════════════════════════════
# Consulta Hermes (standalone, não-interruptível)
# ═══════════════════════════════════════════
def ask_hermes(text: str) -> str:
    """Envia comando de texto pro Hermes, retorna resposta limpa."""
    if not text:
        return "Comando vazio."
    try:
        env = get_desktop_env()
        env.pop("HERMES_HOME", None)

        result = subprocess.run(
            [HERMES_BIN, "-p", HERMES_PROFILE, "chat",
             "-q", text, "--quiet", "--yolo"],
            capture_output=True, text=True, timeout=120,
            env=env,
        )
        raw = result.stdout
        clean_lines = []
        for line in raw.splitlines():
            ls = line.strip()
            ll = ls.lower()
            if (not ls
                or ll.startswith("session_id:")
                or ll.startswith("warning:")
                or "unknown toolsets" in ll
                or "áudio gerado" in ll
                or "audio gerado" in ll
            ):
                continue
            clean_lines.append(ls)
        response = "\n".join(clean_lines).strip()
        return response if response else "Comando processado."
    except subprocess.TimeoutExpired:
        return "O Hermes demorou muito para responder. Tente novamente."
    except Exception as e:
        return f"Erro ao contactar Hermes: {e}"


# ═══════════════════════════════════════════
# Valores do app por cima das constantes
# ═══════════════════════════════════════════
def _aplicar_config():
    """hermes_voice_config sobrepõe as constantes definidas acima."""
    global SILENCE_TIMEOUT, MIN_SPEECH_RMS, SUSTAINED_SPEECH_FRAMES, BARGE_IN
    global INTERRUPT_SPEECH_FRAMES, INTERRUPT_MIN_RMS, RECORD_MAX_SEC
    global SESSION_IDLE_SEC, TOQUE_SEGURAR_SEC, RECORD_MAX_TOQUE_SEC
    global GROQ_MODEL, STT_IDIOMA, DEBUG_LEVELS, STT_PROVEDOR, STT_GEMINI_MODELO
    c, t, v = VCFG["conversa"], VCFG["toque"], VCFG["voz"]
    SILENCE_TIMEOUT = float(c["silencio_fim_s"])
    MIN_SPEECH_RMS = int(c["fala_rms"])
    SUSTAINED_SPEECH_FRAMES = int(c["fala_quadros"])
    BARGE_IN = bool(c["barge_in"])
    INTERRUPT_SPEECH_FRAMES = int(c["barge_quadros"])
    INTERRUPT_MIN_RMS = int(c["barge_rms"])
    RECORD_MAX_SEC = float(c["gravacao_max_s"])
    SESSION_IDLE_SEC = float(c["sessao_ociosa_s"])
    TOQUE_SEGURAR_SEC = float(t["segurar_s"])
    RECORD_MAX_TOQUE_SEC = float(t["gravacao_max_s"])
    GROQ_MODEL = str(v["stt_modelo"]) or GROQ_MODEL
    STT_IDIOMA = str(v["stt_idioma"]) or "pt"
    STT_PROVEDOR = str(v.get("stt_provedor") or "")
    STT_GEMINI_MODELO = str(v.get("stt_gemini_modelo") or "gemini-flash-lite-latest")
    DEBUG_LEVELS = DEBUG_LEVELS or bool(VCFG["diagnostico"]["rastro_niveis"])


BARGE_IN = True
STT_IDIOMA = "pt"
STT_PROVEDOR = ""
STT_GEMINI_MODELO = "gemini-flash-lite-latest"
_aplicar_config()


# ═══════════════════════════════════════════
# Daemon Principal
# ═══════════════════════════════════════════
class Daemon:
    def __init__(self, device: int | None = None):
        self.device = device
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        try:
            self.silero: SileroVad | None = SileroVad()
            LOG.info("VAD: Silero (%s, limiar %.2f)", SILERO_MODEL, SILERO_THRESHOLD)
        except Exception as e:
            self.silero = None
            LOG.warning("Silero indisponível (%s); VAD volta ao webrtcvad", e)
        self._vad_max = 0.0
        # Porteiro de voz: só o dono do PC comanda o orbe. Sem cadastro
        # (hermes_voice_speaker.py enroll) ele fica desligado.
        self.speaker = None
        try:
            from hermes_voice_speaker import SpeakerGate
            gate = SpeakerGate()
            if gate.ativo:
                self.speaker = gate
                LOG.info("Porteiro de voz: ativo (limiar %.3f)", gate.limiar)
            else:
                LOG.info("Porteiro de voz: sem cadastro, aceita qualquer voz")
        except Exception as e:
            LOG.warning("Porteiro de voz indisponível (%s); aceita qualquer voz", e)
        self.running = threading.Event()
        self.running.set()
        self.audio_queue: queue.Queue = queue.Queue(maxsize=120)  # ~3.6s; xrun não vira OOM
        # Sem wake word, o microfone só abre com o orbe ativo (ver _mic_necessario).
        self._mic_evento = threading.Event()
        self._last_audio_t = time.monotonic()
        self._xrun_log_t = 0.0
        self.speech_frames = 0
        self.state = "listening"
        self.expecting_command = False
        self.preroll_buffer = collections.deque(maxlen=32)  # ~960ms de pre-roll
        self.rec = None

        # ── Infraestrutura de interrupção ──
        self._active_proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._interrupted = threading.Event()
        self._processing_thread: threading.Thread | None = None
        self.allow_interrupt = False
        self._tts_playing = False
        self._int_frames = 0
        self._session_until = 0.0
        self._deaf_until = 0.0
        self._from_wake = False
        self._chat_id = None
        self._voice_session = None
        self._tts_gen = 0
        self._tts_sent_q = queue.Queue()
        self._tts_play_q = queue.Queue()
        self._tts_done = threading.Event()
        self._tts_done.set()
        self._tts_proc = None
        self._tts_turn_n = 0
        self._tts_barge = False
        self._tts_barge_after = 0.0
        self._echo_rms = 0.0
        self._tts_ring = collections.deque(maxlen=30)
        self._last_spoken = collections.deque(maxlen=8)
        self.oww = self._criar_ouvido()

        if _stt_provedor() == "gemini":
            LOG.info("STT: Gemini (%s)", STT_GEMINI_MODELO)
        elif not GROQ_API_KEY:
            LOG.warning("GROQ_API_KEY não definida! STT via Groq não funcionará.")

        self._last_ack = ""
        self._aec_ok = False
        self._hold_until = 0.0   # >0 = sessão travada; ver HOLD_MAX_SEC
        self._pedido_aberto = ""  # pedido cuja geração foi abortada no meio
        self._pedido_ts = 0.0
        self._continuando = False
        # Turno abortado por continuação: o turno novo espera ele guardar o
        # pedido antes de emendar (ver _emendar_pedido).
        self._thread_velho: threading.Thread | None = None
        self._ctl_q: queue.Queue = queue.Queue()
        self._toque_t = 0.0
        self._toque_rec_novo = False
        self._toque_curto_t = 0.0   # último toque curto: dois seguidos travam a sessão
        self._relatos: collections.deque = collections.deque()
        self._dbg_max, self._dbg_sf, self._dbg_next = 0.0, 0, 0.0
        self._mic_orb_t = 0.0
        self._hermes_rt = _hermes_runtime()
        # Agente ACP: um processo, carregado entre os pedidos.
        self.agente: acp.AgenteACP | None = None
        self._agente_lock = threading.Lock()
        self._agente_uso = time.monotonic()
        self._instruido = False
        self.capture_rate, self.capture_block = self._resolve_capture()
        self._check_aec()

        signal.signal(signal.SIGINT, lambda *a: self.running.clear())
        signal.signal(signal.SIGTERM, lambda *a: self.running.clear())

    def _resolve_capture(self) -> tuple[int, int]:
        """Taxa nativa do dispositivo e tamanho de bloco correspondente.

        A orelhinha da GUI nunca pede 16 kHz ao PortAudio: abre na taxa que o
        dispositivo declara como nativa e reamostra em numpy. Aqui é o mesmo.
        """
        rate = SAMPLE_RATE
        nome = ""
        try:
            info = sd.query_devices(self.device, "input")
            nome = (info.get("name") or "").lower().strip()
            nativa = info.get("default_samplerate")
            if (isinstance(nativa, (int, float))
                    and not isinstance(nativa, bool) and nativa > 0):
                rate = int(round(nativa))
        except Exception as e:
            LOG.warning("Sem taxa nativa do dispositivo (%s); abrindo em %d Hz",
                        e, SAMPLE_RATE)
        # O plugin ALSA "pipewire"/"pulse"/"default" anuncia 44100. O grafo
        # SOF+AEC neste host é 48 kHz; abrir em 44100 cria um cliente extra
        # no mesmo relógio do speaker (AEC acopla captura e playback) e o
        # SOF entra em resync — áudio engasga.
        if rate == 44100 and nome in ("pipewire", "pulse", "default"):
            rate = 48000
            LOG.info("Captura: plugin anunciou 44100; abrindo a 48000 (taxa do grafo)")
        bloco = max(1, int(round(FRAME_SIZE * rate / SAMPLE_RATE)))
        LOG.info("Captura: %d Hz nativos, bloco de %d → quadro de %d @ %d Hz "
                 "(reamostragem por média de janela, igual à GUI)",
                 rate, bloco, FRAME_SIZE, SAMPLE_RATE)
        return rate, bloco

    def _check_aec(self):
        """Módulo no grafo → captura pelo nome. Default source intocada.

        hermes_aec_source é a saída filtrada. Não vira o microfone do
        desktop: o daemon amarra PIPEWIRE_NODE só no pw-record.
        """
        self._aec_ok = False
        if MAC:
            # Sem PipeWire: o cancelamento de eco do PipeWire não existe aqui.
            LOG.info("AEC: indisponível no macOS; barge-in usa o microfone cru")
            return
        for _ in range(3):
            try:
                r = subprocess.run(
                    ["pactl", "list", "short", "sources"],
                    capture_output=True, text=True, timeout=2,
                )
                txt = r.stdout or ""
            except Exception as e:
                LOG.warning("AEC: pactl falhou (%s)", e)
                return
            if re.search(rf"(^|\s){re.escape(AEC_SOURCE_NODE)}(\s|$)", txt):
                self._aec_ok = True
                LOG.info("AEC: %s no grafo; fonte padrão do sistema não será alterada",
                         AEC_SOURCE_NODE)
                try:
                    subprocess.run(["pactl", "set-source-volume", AEC_SOURCE_NODE, "100%"], capture_output=True)
                    subprocess.run(["pactl", "set-source-mute", AEC_SOURCE_NODE, "0"], capture_output=True)
                except Exception:
                    pass
                return
            time.sleep(0.1)
        LOG.warning("AEC: %s ausente; Mic1 cru, sem cancelamento de eco", AEC_SOURCE_NODE)

    def _callback(self, indata, frames, time_info, status):
        if status:
            agora = time.monotonic()
            if agora - self._xrun_log_t >= 5.0:
                self._xrun_log_t = agora
                LOG.warning("Audio: %s", status)
        bloco = indata[:, 0] if getattr(indata, "ndim", 1) == 2 else indata
        if self.capture_rate != SAMPLE_RATE:
            bloco = _resample_frame(bloco, FRAME_SIZE)
        payload = np.ascontiguousarray(bloco, dtype=np.int16).tobytes()
        self._last_audio_t = time.monotonic()
        try:
            self.audio_queue.put_nowait(payload)
        except queue.Full:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_queue.put_nowait(payload)
            except queue.Full:
                pass

    def _touch_session(self):
        self._session_until = time.monotonic() + SESSION_IDLE_SEC

    def _mic_necessario(self) -> bool:
        """Wake word precisa ouvir sempre; sem ela, só com o orbe ativo."""
        return (self.oww is not None or self.expecting_command or self.allow_interrupt
                or self._tts_playing)

    def _abrir_mic(self):
        self._mic_evento.set()

    def _end_session(self, reason: str = "idle"):
        if not (self.expecting_command or self.allow_interrupt):
            orb_cmd("hide")
            return
        LOG.info("Sessão de voz encerrada (%s)", reason)
        self.expecting_command = False
        self.allow_interrupt = False
        # NÃO zera _chat_id/_voice_session: a orbe reusa o Bot Chat forever
        # do modo bot. Só a escuta de voz fecha; o thread Hermes continua.
        self._hold_until = 0.0
        self._pedido_aberto = ""
        self._agente_uso = time.monotonic()
        self._bump_tts()
        if self.oww is not None:
            self.oww.cool_until = time.monotonic() + 4.0
        orb_cmd("hold 0")
        orb_cmd("hide")

    def _trigger_session(self):
        LOG.info("⚡ trigger da sessão de voz (teclado/gesto/wake)")
        orb_cmd("clear")
        orb_cmd("show listening")
        self.expecting_command = True
        self.allow_interrupt = True
        self._from_wake = True
        # Sempre o mesmo forever-chat do Bot Mode.
        if not self._voice_session:
            self._voice_session = HERMES_SESSION
        self._preaquecer_agente()
        self._abrir_mic()
        self._pedido_aberto = ""
        self._continuando = False
        self._tts_barge = False
        self._tts_barge_after = 0.0
        if self.silero is not None:
            self.silero.reset()
        self._touch_session()
        self._ensure_tts_worker()
        self._tts_worker_warm()
        ack = self._pick_ack()
        if ack:
            self._tts_push(ack)

    def _poll_cmdfile(self):
        p = vcfg.RUNTIME / "hermes-voice.cmd"
        try:
            txt = p.read_text()
            p.unlink(missing_ok=True)
        except OSError:
            return
        low = txt.lower().strip()
        if any(w in low for w in ("dismiss", "stop", "hide", "tchau", "cancel")):
            LOG.info("dismiss via cmdfile")
            self._kill_active(hide=True)
            self._end_session("dismiss")
        elif "toggle" in low:
            in_session = self.expecting_command or self.allow_interrupt or self.state != "listening"
            if self._gerando():
                # Atalho no meio do raciocínio: o pedido não tinha acabado.
                # Corta a geração e emenda a próxima fala, como a voz faz.
                self._do_continuacao(0.0, origem="atalho")
            elif in_session:
                LOG.info("toggle: encerrando sessão ativa via cmdfile")
                self._kill_active(hide=True)
                self._end_session("toggle")
            else:
                LOG.info("toggle: iniciando sessão via cmdfile")
                self._trigger_session()
        elif any(w in low for w in ("trigger", "wake", "start", "show")):
            LOG.info("trigger manual via cmdfile")
            self._trigger_session()
        elif "hold" in low:
            self._travar("cmdfile", falar=False)
        elif "release" in low:
            self._destravar("cmdfile", falar=False)

    def _gerando(self) -> bool:
        """Turno em voo (STT ou Hermes) sem a resposta tocando."""
        return (self.state == "processing" and not self._tts_playing
                and self._processing_thread is not None
                and self._processing_thread.is_alive())

    # ── Controle externo: toque no orbe e relato de despacho ──

    def _ctl_loop(self):
        try:
            os.unlink(CTL_SOCK)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(CTL_SOCK)
            srv.listen(8)
        except OSError as e:
            LOG.warning("socket de controle indisponível (%s)", e)
            return
        while self.running.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            partes = []
            try:
                conn.settimeout(2.0)
                while True:
                    bloco = conn.recv(65536)
                    if not bloco:
                        break
                    partes.append(bloco)
            except OSError:
                pass
            finally:
                conn.close()
            for linha in b"".join(partes).decode("utf-8", "replace").splitlines():
                if linha.strip():
                    self._ctl_q.put(linha.strip())

    def _poll_ctl(self):
        """Roda no laço de áudio: o estado só muda numa thread."""
        while True:
            try:
                linha = self._ctl_q.get_nowait()
            except queue.Empty:
                break
            op, _, arg = linha.partition(" ")
            if op == "touch" and arg == "down":
                self._toque_down()
            elif op == "touch" and arg == "up":
                self._toque_up()
            elif op == "relato":
                try:
                    rel = json.loads(arg)
                except ValueError:
                    LOG.warning("relato ilegível: %r", arg[:120])
                    continue
                self._relatos.append(rel)
                LOG.info("Relato na fila (%s)", rel.get("perfil", "?"))
        if (self._relatos and self.state == "listening" and self.rec is None
                and not self._busy()):
            self._iniciar_relato(self._relatos.popleft())
        self._talvez_descarregar_agente()

    def _toque_down(self):
        self._toque_t = time.monotonic()
        if self.state == "recording" and self.rec is not None and not self._tts_playing:
            # Já gravando por voz: o dedo só passa a segurar a gravação.
            self.rec.segurando = True
            self.rec.por_toque = True
            self._toque_rec_novo = False
            LOG.info("toque: segurando a gravação em curso")
            return
        if self._tts_playing:
            LOG.info("toque: fala interrompida")
            self._continuando = False
            self._pedido_aberto = ""
            self._kill_active(hide=False)
        elif self._gerando():
            LOG.info("toque: geração cortada, o pedido continua")
            self._continuando = True
            self._kill_active(hide=False)
        else:
            LOG.info("toque: escutando")
        self._thread_velho = self._processing_thread
        self._processing_thread = None
        if not self._voice_session:
            self._voice_session = HERMES_SESSION
        self._preaquecer_agente()
        self._abrir_mic()
        self.expecting_command = True
        self.allow_interrupt = True
        self.state = "recording"
        self.rec = Recorder()
        self.rec.segurando = True
        self.rec.por_toque = True
        self._toque_rec_novo = True
        self.speech_frames = 0
        self._int_frames = 0
        self._deaf_until = 0.0
        self.preroll_buffer.clear()
        if self.silero is not None:
            self.silero.reset()
        self._touch_session()
        orb_cmd("show listening")

    def _toque_up(self):
        rec = self.rec
        if self.state != "recording" or rec is None or not rec.segurando:
            return
        rec.segurando = False
        dur = time.monotonic() - self._toque_t
        if dur >= TOQUE_SEGURAR_SEC:
            LOG.info("toque solto após %.1fs: fim da fala", dur)
            rec.fim = True
        elif self._toque_rec_novo:
            # Toque curto = só interromper. A gravação do dedo sai; a escuta
            # por voz continua, e a fala seguinte emenda se o pedido ficou aberto.
            self.rec = None
            self.state = "listening"
            self.speech_frames = 0
            orb_cmd("state listening")
            agora = time.monotonic()
            if agora - self._toque_curto_t < TOQUE_DUPLO_SEC:
                # dois toques curtos seguidos: trava a sessão (de novo, solta)
                self._toque_curto_t = 0.0
                if self._hold_until:
                    self._destravar("duplo toque", falar=False)
                else:
                    self._travar("duplo toque", falar=False)
            else:
                self._toque_curto_t = agora
                LOG.info("toque curto: interrompido, escutando")
        else:
            rec.por_toque = False

    def _iniciar_relato(self, rel: dict):
        perfil = str(rel.get("perfil") or "?")
        texto = (f"Resultado do trabalho despachado ao perfil {perfil}.\n"
                 f"Pedido: {rel.get('tarefa', '')}\n")
        if rel.get("arquivo"):
            texto += f"Saída completa em: {rel['arquivo']}\n"
        texto += "\n" + str(rel.get("resultado") or "(sem saída)")
        LOG.info("Relato do despacho (%s): %d caracteres", perfil, len(texto))
        if not self._voice_session:
            self._voice_session = HERMES_SESSION
        self._preaquecer_agente()
        self._abrir_mic()
        self.allow_interrupt = True
        self.expecting_command = False
        self._continuando = False
        self._interrupted.clear()
        self.state = "processing"
        orb_cmd("clear")
        orb_cmd("show thinking")
        self._touch_session()
        gen = self._tts_gen
        self._processing_thread = threading.Thread(
            target=self._responder, args=(texto, gen), kwargs={"relato": True},
            daemon=True)
        self._processing_thread.start()

    def _guardar_pedido(self, cmd: str, falou: bool = False):
        """Geração abortada por continuação antes de qualquer palavra falada:
        o pedido fica para a próxima fala emendar (_emendar_pedido)."""
        if self._continuando and not falou and cmd:
            self._pedido_aberto = cmd
            self._pedido_ts = time.monotonic()
            LOG.info("Pedido guardado para emenda: %r", cmd[:120])
        self._continuando = False

    def _is_dismiss(self, text: str) -> bool:
        return bool(_DISMISS_RE.search(text or ""))

    @staticmethod
    def _so_isso(text: str, rx) -> bool:
        """A frase é só o comando (com no máximo o nome do assistente ou uma
        interjeição em volta); "fica atento ao e-mail" não trava."""
        t = re.sub(r"[^\w\s]", " ", (text or "").lower())
        t = re.sub(r"\b(ei|ok|okay|t[áa]|ent[ãa]o|por favor|hermes|jarvis|a[ií])\b", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return bool(t) and rx.fullmatch(t) is not None

    def _travar(self, origem: str, falar: bool = True):
        self._hold_until = time.monotonic() + HOLD_MAX_SEC
        self._touch_session()
        orb_cmd("hold 1")
        LOG.info("Sessão travada (%s), teto de %d min", origem, int(HOLD_MAX_SEC // 60))
        if falar:
            self._speak("Fico.")

    def _destravar(self, origem: str, falar: bool = True):
        if not self._hold_until:
            return
        self._hold_until = 0.0
        self._touch_session()
        orb_cmd("hold 0")
        LOG.info("Trava solta (%s); timeout de %.0fs volta a valer", origem, SESSION_IDLE_SEC)
        if falar:
            self._speak("Solto.")

    def _is_speech(self, frame: bytes, rms: float) -> bool:
        """Voz neste quadro: piso de RMS e Silero (webrtcvad se ele faltar).

        O Silero só roda com sessão aberta ou turno em andamento. Ocioso, o
        daemon descarta os quadros (só o wake word, quando ligado, os lê), e
        a sessão nova começa com o estado da rede zerado (_trigger_session).
        """
        if self.silero is None:
            return rms >= MIN_SPEECH_RMS and self.vad.is_speech(frame, SAMPLE_RATE)
        if not (self.expecting_command or self.allow_interrupt
                or self.state != "listening"):
            return False
        p = self.silero.feed(frame)
        self._vad_max = max(self._vad_max, p)
        return rms >= MIN_SPEECH_RMS and p >= SILERO_THRESHOLD

    def _voz_do_dono(self, pcm: np.ndarray, onde: str) -> bool:
        """True = o dono falou (ou não dá para saber). Loga a similaridade."""
        if self.speaker is None:
            return True
        t0 = time.monotonic()
        ok, sim = self.speaker.e_o_dono(pcm)
        LOG.info("porteiro %s: %s (sim=%s limiar=%.3f, %.0f ms)", onde,
                 "dono" if ok else "OUTRA PESSOA, ignorada",
                 "n/d" if sim is None else f"{sim:.3f}", self.speaker.limiar,
                 (time.monotonic() - t0) * 1000)
        return ok

    def _is_deaf(self) -> bool:
        return self._tts_playing or time.monotonic() < self._deaf_until

    def _busy(self) -> bool:
        if self._tts_playing:
            return True
        if self.state == "processing" or (
            self._processing_thread is not None and self._processing_thread.is_alive()
        ):
            return True
        if self.state == "recording" and self.rec is not None and self.rec.has_spoken:
            return True
        return False

    def _should_idle_end(self) -> bool:
        if not (self.expecting_command or self.allow_interrupt):
            return False
        if self._busy():
            return False
        if self._hold_until:
            # Sessão travada a pedido do Jarvis ("segura a sessão"). O timeout
            # de inatividade sai de cena, mas não para sempre: sem um teto, um
            # hold esquecido deixa o microfone armado indefinidamente. Só a
            # dispensa explícita, o release, ou este teto encerram.
            if time.monotonic() < self._hold_until:
                return False
            LOG.info("Trava de sessão expirou (teto de %d min sem fala)",
                     int(HOLD_MAX_SEC // 60))
            self._hold_until = 0.0
        return self._session_expired()

    def _bump_tts(self):
        self._tts_gen += 1
        self._tts_playing = False
        self._tts_barge_after = 0.0
        self._tts_worker_cancel()
        try:
            while True:
                self._tts_sent_q.get_nowait()
        except queue.Empty:
            pass
        proc = self._tts_proc
        if proc and proc.pid:
            try:
                subprocess.run(
                    ["pkill", "-9", "-P", str(proc.pid)],
                    capture_output=True, timeout=1,
                )
            except Exception:
                pass

    def _ensure_tts_worker(self):
        if self._tts_proc is not None and self._tts_proc.poll() is None:
            return
        logf = open("/tmp/hermes-voice-tts.log", "ab", buffering=0)
        # o venv do Hermes, se houver (credenciais OAuth do xAI); senão, o do daemon
        py_hermes = Path.home() / ".hermes/hermes-agent/venv/bin/python"
        self._tts_proc = subprocess.Popen(
            [str(py_hermes) if py_hermes.exists() else sys.executable,
             str(Path(__file__).resolve().parent / "hermes_voice_tts.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=logf,
            env=_tts_child_env(),
            text=True,
            bufsize=1,
        )
        LOG.info("TTS worker: Jarvis tts.provider (xAI OAuth / Gemini / Piper)")

    def _tts_worker_cancel(self):
        proc = self._tts_proc
        if proc and proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write("CANCEL\n")
                proc.stdin.flush()
            except OSError:
                pass

    def _tts_worker_warm(self):
        """Manda o worker abrir o WebSocket antes de haver texto.

        O handshake com a xAI custa 0.56s contra 0.53s de síntese: mais da
        metade do tempo até o primeiro áudio é só conexão. Disparado quando o
        turno começa, ele acontece enquanto o modelo ainda gera, e sai do
        caminho crítico. Silencioso de propósito: é otimização, não função.
        """
        proc = self._tts_proc
        if proc and proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write("WARM\n")
                proc.stdin.flush()
            except OSError:
                pass

    def _tts_worker_say(self, text: str, gen: int):
        self._ensure_tts_worker()
        proc = self._tts_proc
        if not proc or proc.poll() is not None or not proc.stdin:
            LOG.warning("TTS worker morto")
            return
        try:
            proc.stdin.write("SAY " + text.replace("\n", " ") + "\n")
            proc.stdin.flush()
        except OSError as e:
            LOG.warning("TTS worker write: %s", e)
            self._tts_proc = None
            return
        while gen == self._tts_gen:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                break
            line = line.strip()
            if line.startswith("LEVEL "):
                orb_cmd("level " + line[6:])
            elif line.startswith("DONE") or line.startswith("ERR"):
                if line.startswith("ERR"):
                    LOG.warning("TTS %s", line)
                break

    def _tts_push(self, sentence: str, gen: int | None = None):
        s = _clean_tts(sentence)
        if len(s) < 2:
            return
        if _NARRATE_RE.search(s):
            return
        if gen is None:
            gen = self._tts_gen
        if gen != self._tts_gen:
            return
        self._tts_sent_q.put((s, gen))
        self._tts_turn_n += 1
        self._tts_playing = True
        self._last_spoken.append(s)
        if _normalize_utterance(s) not in _ACK_NORMS:
            self._tts_barge = BARGE_IN
            if self._tts_barge_after == 0.0:
                self._tts_barge_after = time.monotonic() + 0.55
                self._echo_rms = 0.0
        LOG.info("TTS queue [%d]: %s", self._tts_turn_n, s[:100])

    def _tts_drain(self):
        gen = self._tts_gen
        t0 = time.monotonic()
        while gen == self._tts_gen and time.monotonic() - t0 < 45:
            if self._tts_sent_q.empty() and not self._tts_playing:
                return
            time.sleep(0.05)

    def _tts_consumer(self):
        while self.running.is_set():
            try:
                item = self._tts_sent_q.get(timeout=0.4)
            except queue.Empty:
                continue
            if item is None:
                continue
            text, gen = item
            if gen != self._tts_gen:
                continue
            orb_cmd("state speaking")
            self._tts_playing = True
            try:
                self._tts_worker_say(text, gen)
            except Exception as e:
                LOG.warning("TTS consumer: %s", e)
            finally:
                if self._tts_sent_q.empty():
                    self._tts_playing = False
                    self._deaf_until = time.monotonic() + 0.20
                    orb_cmd("level 0")
                    self._int_frames = 0
                self._touch_session()

    def _session_expired(self) -> bool:
        return time.monotonic() >= self._session_until

    # ── Subprocess interruptível ──

    def _run_proc(self, cmd, input_data=None, timeout=120, env=None, text_mode=False):
        """Executa subprocess que pode ser morto por _kill_active().
        Retorna CompletedProcess ou None se interrompido/timeout."""
        if self._interrupted.is_set():
            return None
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if input_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=text_mode,
            )
        except Exception as e:
            LOG.warning("Falha ao iniciar %s: %s", cmd[0], e)
            return None
        with self._proc_lock:
            self._active_proc = proc
        try:
            stdout, stderr = proc.communicate(input=input_data, timeout=timeout)
            if self._interrupted.is_set():
                return None
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return None
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            return None
        finally:
            with self._proc_lock:
                self._active_proc = None

    def _kill_active(self, hide=False):
        """Mata o processo ativo (hermes/pw-play) e sinaliza interrupção."""
        self._interrupted.set()
        self._bump_tts()
        if hide:
            orb_cmd("hide")
        else:
            orb_cmd("state listening")
        with self._proc_lock:
            if self._active_proc:
                try:
                    self._active_proc.kill()
                    LOG.info("Processo ativo (PID %d) morto", self._active_proc.pid)
                except Exception:
                    pass

    def _pick_ack(self) -> str:
        """Sorteia o atendimento, nunca repetindo o imediatamente anterior."""
        if not ACK_PHRASES:
            return ""
        opcoes = [p for p in ACK_PHRASES if p != self._last_ack] or list(ACK_PHRASES)
        self._last_ack = random.choice(opcoes) if opcoes else ""
        return self._last_ack

    def _do_barge(self, rms: float):
        LOG.info("⚡ barge-in (rms=%.0f, piso=%d, %dms sustentados)",
                 rms, INTERRUPT_MIN_RMS,
                 INTERRUPT_SPEECH_FRAMES * FRAME_MS)
        self._int_frames = 0
        self._tts_barge = False
        self._deaf_until = 0.0
        # Barge-in de verdade: ele está reagindo à RESPOSTA, então o pedido
        # anterior está velho e não deve voltar emendado.
        self._continuando = False
        self._pedido_aberto = ""
        self._kill_active(hide=False)
        self._thread_velho = self._processing_thread
        self._processing_thread = None
        self.expecting_command = True
        self.allow_interrupt = True
        self.state = "recording"
        self.rec = Recorder()
        self.rec.echo_skip_until = 0
        self.speech_frames = 0
        tail = list(self._tts_ring)
        self._tts_ring.clear()
        self.preroll_buffer.clear()
        for pf, ps in tail:
            self.rec.feed(pf, ps)

    def _do_continuacao(self, rms: float, origem: str = "voz"):
        """Fala durante a GERAÇÃO: o pedido não tinha terminado de ser dito.

        Falando devagar, a pausa entre palavras passa de SILENCE_TIMEOUT e a
        gravação fecha no meio da frase. O pedido incompleto já disparou a
        geração, e antes o resto da fala só era ouvido depois que a resposta
        inteira saísse, virando turno novo. Agora a geração em voo é abortada e
        a fala nova é gravada para emendar o pedido (ver _emendar_pedido).

        Difere do barge-in por onde semeia o gravador: no barge-in o áudio útil
        está no anel capturado durante o TTS; aqui está no preroll, porque
        durante a geração o microfone não estava sendo desviado para o anel.
        """
        if origem == "voz":
            LOG.info("Fala durante a geração (rms=%.0f, %dms): continuação do pedido",
                     rms, INTERRUPT_SPEECH_FRAMES * FRAME_MS)
        else:
            LOG.info("Continuação do pedido pelo %s", origem)
        self._int_frames = 0
        self._deaf_until = 0.0
        self._continuando = True
        self._kill_active(hide=False)
        self._thread_velho = self._processing_thread
        self._processing_thread = None
        self.expecting_command = True
        self.allow_interrupt = True
        self.state = "recording"
        self.rec = Recorder()
        self.rec.echo_skip_until = 0
        self.speech_frames = 0
        tail = list(self.preroll_buffer)
        self.preroll_buffer.clear()
        for pf, ps in tail:
            self.rec.feed(pf, ps)

    def _emendar_pedido(self, cmd: str) -> str:
        """Junta a fala nova ao pedido anterior quando ela é continuação.

        O discriminador é ONDE a geração parou. Se nenhuma palavra da resposta
        chegou a ser falada, o Davi ainda estava formulando e o que ele diz
        agora é o resto da mesma frase. Se o orbe já estava respondendo, aí é
        interrupção de verdade: o pedido velho não volta, senão a correção
        ("na verdade, faz outra coisa") viria grudada no que ela corrige.
        """
        pend, self._pedido_aberto = self._pedido_aberto, ""
        if not pend:
            return cmd
        idade = time.monotonic() - self._pedido_ts
        if idade > AMEND_WINDOW_SEC:
            LOG.info("Pedido em aberto descartado (%.1fs > %.0fs)",
                     idade, AMEND_WINDOW_SEC)
            return cmd
        emendado = f"{pend.rstrip(' .,;')} {cmd}".strip()
        LOG.info("Pedido emendado (%.1fs): %r + %r", idade, pend, cmd)
        return emendado

    def _is_tts_echo(self, text: str) -> bool:
        if self._aec_ok:
            return False
        raw_clean = re.sub(r"[^a-z0-9]", "", (text or "").lower())
        if not raw_clean:
            return False
        for ack in ("sim", "poisnao", "fala", "manda", "oi", "podefalar", "escuto", "estououvindo"):
            if raw_clean in (ack, ack + "podefalar", ack + "estououvindo") or (
                raw_clean.startswith(ack) and len(raw_clean) <= len(ack) + 8
            ):
                return True
        t = re.sub(r"[^a-z0-9áéíóúâêôãõç ]", "", (text or "").lower())
        t = " ".join(t.split())
        if len(t) < 6:
            return False
        import difflib
        for s in self._last_spoken:
            u = re.sub(r"[^a-z0-9áéíóúâêôãõç ]", "", s.lower())
            u = " ".join(u.split())
            if not u:
                continue
            # "u in t" só com frase falada longa: uma curta ("Sim?", "Quatro.")
            # cabe dentro de qualquer comando, e o comando inteiro ia fora
            # como eco ("Sim? Que horas são agora?", 03/10).
            if t in u or (len(u) >= 10 and u in t):
                return True
            if len(t) >= 10 and len(u) >= 10:
                if difflib.SequenceMatcher(None, t, u).ratio() > 0.65:
                    return True
        return False

    # ── TTS interruptível ──

    def _speak(self, text: str):
        self._tts_push(text)

    # ── Agente ACP ──

    @staticmethod
    def _hermes_env() -> dict:
        env = get_desktop_env()
        env.pop("HERMES_HOME", None)
        env["TERM"] = "dumb"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _criar_ouvido(self):
        """Ouvido de wake word do provedor escolhido no app; None = desligado."""
        try:
            if WAKE_PROVEDOR == "openwakeword":
                ouvido = OpenWakeWordEar()
                desc = f"openWakeWord {OWW_MODEL} (limiar {OWW_THRESHOLD:.2f}, {OWW_CONFIRM} quadros)"
            elif WAKE_PROVEDOR == "sherpa":
                ouvido = SherpaEar(_AT["sherpa_dir"], _AT["frase"], float(_AT["limiar_sherpa"]))
                desc = f"sherpa-onnx, frase \"{_AT['frase']}\""
            elif WAKE_PROVEDOR == "microwakeword":
                ouvido = MicroWakeWordEar(MWW_MODEL, float(_AT["limiar_mww"]), OWW_CONFIRM)
                desc = f"microWakeWord {MWW_MODEL}"
            else:
                LOG.info("Wake word desligado: ativação pelo atalho e pelo toque")
                return None
        except Exception as e:
            LOG.error("Wake word (%s) falhou: %s", WAKE_PROVEDOR, e)
            return None
        LOG.info("Wake word: %s", desc)
        return ouvido

    def _agente_chave(self) -> str:
        a = AGENTE_CFG
        return "|".join((a["tipo"], a["perfil"] if a["tipo"] == "hermes" else "",
                         a["comando"] if a["tipo"] == "comando" else ""))

    def _agente_velho(self, ag: acp.AgenteACP) -> bool:
        if AGENTE_CFG["tipo"] != "hermes":
            return False
        return any(_mtime(p) > ag.iniciado_em for p in WARM_STALE_PATHS)

    def _agente_pronto(self) -> acp.AgenteACP:
        """Agente vivo e com sessão; sobe, ou reinicia retomando a conversa."""
        with self._agente_lock:
            ag = self.agente
            if ag is not None and ag.vivo() and ag.sessao and not self._agente_velho(ag):
                return ag
            if ag is not None:
                LOG.info("agente ACP: reiniciando (%s)",
                         "config mudou" if ag.vivo() else "processo saiu")
                ag.fechar()
                self.agente = None
            t0 = time.monotonic()
            if AGENTE_CFG["tipo"] == "claude":
                # Sessão do Claude já aberta no terminal: nada a subir.
                argv = ["claude"]
                ag = canal.AgenteClaude()
            else:
                hermes = AGENTE_CFG["tipo"] == "hermes"
                argv, extra = acp.comando(AGENTE_CFG, self._hermes_rt if hermes else None)
                env = self._hermes_env()
                env.update(extra)
                ag = acp.AgenteACP(argv, env)
            try:
                ag.iniciar()
                estado = vcfg.ler_estado()
                retomar = estado.get("sessao") if estado.get("chave") == self._agente_chave() else None
                ag.abrir_sessao(retomar)
                if AGENTE_CFG["modelo"]:
                    try:
                        ag.definir_modelo(AGENTE_CFG["modelo"])
                    except acp.ErroACP as e:
                        LOG.warning("agente ACP: modelo %s recusado (%s)", AGENTE_CFG["modelo"], e)
            except Exception:
                ag.fechar()
                raise
            self.agente = ag
            # A conversa retomada já recebeu a instrução de voz no 1º pedido.
            self._instruido = bool(retomar) and ag.sessao == retomar
            info = ag.info.get("agentInfo") or {}
            if AGENTE_CFG["tipo"] == "claude":
                LOG.info("Claude: sessão %s em %s", ag.sessao, ag.cwd or "?")
            LOG.info("agente ACP pronto em %.1fs: %s %s, sessão %s (%s), modelo %s",
                     time.monotonic() - t0, info.get("name", argv[0]), info.get("version", ""),
                     ag.sessao, "retomada" if self._instruido or (retomar and ag.sessao == retomar) else "nova",
                     ag.modelo_atual or "padrão")
            try:
                vcfg.gravar_estado({
                    "chave": self._agente_chave(), "sessao": ag.sessao,
                    "agente": info.get("title") or info.get("name") or "",
                    "modelos": ag.modelos, "modelo_atual": ag.modelo_atual,
                })
            except OSError as e:
                LOG.warning("estado do agente não gravado: %s", e)
            return ag

    def _preaquecer_agente(self):
        """Sobe o agente em segundo plano enquanto o Davi ainda fala."""
        ag = self.agente
        if (ag is not None and ag.vivo()) or self._agente_lock.locked():
            return

        def _subir():
            try:
                self._agente_pronto()
            except Exception as e:
                LOG.warning("agente ACP não subiu: %s", e)
        threading.Thread(target=_subir, daemon=True).start()

    def _talvez_descarregar_agente(self):
        if MANTER_MIN <= 0 or self.agente is None:
            return
        if (self.expecting_command or self.allow_interrupt or self._gerando()
                or self._agente_lock.locked()):
            return
        if time.monotonic() - self._agente_uso < MANTER_MIN * 60:
            return
        with self._agente_lock:
            ag, self.agente = self.agente, None
        if ag is not None:
            LOG.info("agente ACP descarregado (%.0f min sem sessão de voz)", MANTER_MIN)
            threading.Thread(target=ag.fechar, daemon=True).start()

    def _ask_hermes(self, text: str) -> str:
        """Pergunta ao agente por ACP. O texto chega em pedaços e vai ao TTS
        frase a frase; pensamento vai para o orbe, nunca para a voz.

        Interromper (barge-in, toque, atalho) manda session/cancel: o turno
        fecha e o processo do agente continua carregado.
        """
        if not text or self._interrupted.is_set():
            return ""
        gen = self._tts_gen
        # O agente vai levar um tempo; abre o socket do TTS em paralelo.
        self._tts_worker_warm()
        try:
            ag = self._agente_pronto()
        except Exception as e:
            LOG.warning("agente ACP indisponível: %s", e)
            return ""
        pedido = text
        instrucao = (AGENTE_CFG.get("instrucao_voz") or "").strip()
        # Hermes usa o SOUL do perfil; o canal do Claude manda a instrução ao conectar.
        if AGENTE_CFG["tipo"] not in ("hermes", "claude") and instrucao and not self._instruido:
            pedido = f"{instrucao}\n\n{text}"
            self._instruido = True

        partes: list[str] = []
        frase = [""]
        pensado = [""]

        def ao_texto(t: str):
            if self._tts_gen != gen:
                return
            partes.append(t)
            frase[0] += t
            sents, frase[0] = _take_sentences(frase[0])
            for sent in sents:
                self._tts_push(sent, gen)

        def ao_pensamento(t: str):
            if self._tts_gen != gen:
                return
            if not pensado[0]:
                orb_cmd("state thinking")
            pensado[0] += t
            while "\n" in pensado[0] or len(pensado[0]) > 160:
                corte = pensado[0].find("\n")
                corte = corte if 0 <= corte <= 160 else 160
                linha, pensado[0] = pensado[0][:corte].strip(), pensado[0][corte:].lstrip("\n")
                if linha:
                    orb_cmd("line " + linha[:200])
            if not pensado[0]:
                pensado[0] = " "

        def a_ferramenta(_titulo: str, _status: str):
            if self._tts_gen == gen:
                orb_cmd("state tools")

        daemon = self

        class _Parar:
            @staticmethod
            def is_set() -> bool:
                return daemon._interrupted.is_set() or daemon._tts_gen != gen

        try:
            fim = ag.perguntar(pedido, ao_texto, ao_pensamento, a_ferramenta,
                               parar=_Parar(),
                               teto=600.0 if AGENTE_CFG["tipo"] == "claude" else 120.0)
            if fim not in ("end_turn", "cancelled"):
                LOG.info("agente ACP: turno terminou com %s", fim or "?")
        except acp.ErroACP as e:
            LOG.warning("agente ACP: %s", e)
        finally:
            self._agente_uso = time.monotonic()
            if frase[0].strip() and self._tts_gen == gen and not self._interrupted.is_set():
                self._tts_push(frase[0].strip(), gen)
            if self._tts_gen == gen:
                self._tts_drain()
        if self._interrupted.is_set() or self._tts_gen != gen:
            return ""
        return "".join(partes).strip()

    # ── Main Loop ──

    def run(self):
        LOG.info("═══ Hermes Voice Daemon v4 (Groq Whisper) ═══")
        LOG.info("VAD: %d | Groq: %s", VAD_AGGRESSIVENESS, GROQ_MODEL)
        LOG.info("Agente: %s | wake word: %s | barge-in: %s",
                 acp.NOMES.get(AGENTE_CFG["tipo"], AGENTE_CFG["tipo"])
                 + (f" ({AGENTE_CFG['perfil']})" if AGENTE_CFG["tipo"] == "hermes" else ""),
                 WAKE_PROVEDOR, "ligado" if BARGE_IN else "desligado")
        self._ensure_tts_worker()
        threading.Thread(target=self._tts_consumer, daemon=True).start()
        threading.Thread(target=_orb_boot, daemon=True).start()
        threading.Thread(target=self._ctl_loop, daemon=True).start()
        if MANTER_MIN <= 0:
            self._preaquecer_agente()

        # Inicializa volume de áudio do sistema (sink e source) no máximo (100%)
        env = get_desktop_env()
        try:
            if MAC:
                raise _SemMixer
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "1.0"], capture_output=True, env=env)
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", "1.0"], capture_output=True, env=env)
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], capture_output=True, env=env)
            subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "100%"], capture_output=True, env=env)
            if self._aec_ok:
                subprocess.run(["pactl", "set-source-volume", AEC_SOURCE_NODE, "100%"], capture_output=True, env=env)
                subprocess.run(["pactl", "set-source-mute", AEC_SOURCE_NODE, "0"], capture_output=True, env=env)
            LOG.info("Volume de áudio inicializado no máximo (100%).")
        except _SemMixer:
            pass    # no Mac o volume é do usuário; o daemon não mexe
        except Exception as e:
            LOG.warning("Erro ao inicializar volume de áudio: %s", e)

        # Captura nativa PipeWire via pw-record (48000 Hz, 1 ch, s16le raw).
        # Bypassa a camada ALSA do PortAudio (pa_linux_alsa.c) que sofre com
        # xrun spinloops infinitos de AlsaRestart e deadlocks no PipeWire.
        capture_bytes = self.capture_block * 2

        def _capture_worker():
            backoff = 0.5
            while self.running.is_set():
                # Orbe inativo e sem wake word: nenhum stream aberto no mic.
                if not self._mic_necessario() and not self._mic_evento.is_set():
                    self._mic_evento.wait(0.5)
                    continue
                self._mic_evento.clear()
                target = AEC_SOURCE_NODE if self._aec_ok else "@DEFAULT_AUDIO_SOURCE@"
                if self._aec_ok:
                    try:
                        subprocess.run(["pactl", "set-source-volume", AEC_SOURCE_NODE, "100%"], capture_output=True)
                        subprocess.run(["pactl", "set-source-mute", AEC_SOURCE_NODE, "0"], capture_output=True)
                    except Exception:
                        pass
                latency_str = f"{int(round(self.capture_block * 1000 / self.capture_rate))}ms"
                cmd = [
                    "pw-record",
                    "--target", target,
                    "--rate", str(self.capture_rate),
                    "--channels", "1",
                    "--format", "s16",
                    "--container", "raw",
                    "--latency", latency_str,
                    "-",
                ]
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                except Exception as e:
                    LOG.warning("pw-record falhou ao iniciar: %s", e)
                    time.sleep(backoff)
                    backoff = min(8.0, backoff * 2)
                    continue

                LOG.info("Captura ativa via pw-record (alvo=%s latency=%s)", target, latency_str)
                backoff = 0.5
                self._last_audio_t = time.monotonic()
                aberto_em = time.monotonic()
                fechou = False
                while self.running.is_set():
                    if not proc.stdout:
                        break
                    # 1 s de folga: a sessão marca expecting_command logo
                    # depois de pedir o microfone.
                    if (time.monotonic() - aberto_em > 1.0 and not self._mic_necessario()
                            and not self._mic_evento.is_set()):
                        fechou = True
                        break
                    try:
                        raw = proc.stdout.read(capture_bytes)
                    except Exception:
                        break
                    if not raw or len(raw) < capture_bytes:
                        break
                    bloco = np.frombuffer(raw, dtype=np.int16)
                    if self.capture_rate != SAMPLE_RATE:
                        bloco = _resample_frame(bloco, FRAME_SIZE)
                    payload = np.ascontiguousarray(bloco, dtype=np.int16).tobytes()
                    self._last_audio_t = time.monotonic()
                    try:
                        self.audio_queue.put_nowait(payload)
                    except queue.Full:
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.audio_queue.put_nowait(payload)
                        except queue.Full:
                            pass

                err_msg = ""
                if fechou:
                    # Vivo ainda: ler o stderr até EOF travaria aqui.
                    proc.terminate()
                if proc.stderr and not fechou:
                    try:
                        err_msg = proc.stderr.read().decode("utf-8", "replace").strip()
                    except Exception:
                        pass
                if err_msg:
                    LOG.warning("pw-record stderr: %s", err_msg[:200])

                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                for f in (proc.stdout, proc.stderr):
                    if f:
                        f.close()
                if fechou:
                    LOG.info("Microfone fechado: orbe inativo")
                elif self.running.is_set():
                    LOG.warning("Fluxo de áudio pw-record desconectado; reconectando em %.1fs...", backoff)
                    time.sleep(backoff)

        def _capture_worker_mac():
            """CoreAudio pelo sounddevice: o mesmo ciclo do pw-record.

            O stream só fica aberto enquanto o microfone é necessário (o
            indicador laranja do macOS some com o orbe inativo), e reabre
            sozinho se o dispositivo cair (fone desconectado etc.).
            """
            backoff = 0.5
            while self.running.is_set():
                if not self._mic_necessario() and not self._mic_evento.is_set():
                    self._mic_evento.wait(0.5)
                    continue
                self._mic_evento.clear()
                try:
                    # o dispositivo padrão pode ter mudado desde a última vez
                    self.capture_rate, self.capture_block = self._resolve_capture()
                    stream = sd.InputStream(
                        device=self.device, samplerate=self.capture_rate, channels=1,
                        dtype="int16", blocksize=self.capture_block,
                        latency="low", callback=self._callback)
                    stream.start()
                except Exception as e:
                    LOG.warning("microfone indisponível (%s); nova tentativa em %.1fs", e, backoff)
                    time.sleep(backoff)
                    backoff = min(8.0, backoff * 2)
                    continue
                LOG.info("Captura ativa via CoreAudio (%d Hz, bloco %d)",
                         self.capture_rate, self.capture_block)
                backoff = 0.5
                aberto_em = self._last_audio_t = time.monotonic()
                fechou = False
                while self.running.is_set() and stream.active:
                    time.sleep(0.1)
                    agora = time.monotonic()
                    if (agora - aberto_em > 1.0 and not self._mic_necessario()
                            and not self._mic_evento.is_set()):
                        fechou = True
                        break
                    if agora - self._last_audio_t > 3.0:
                        LOG.warning("CoreAudio parou de entregar áudio; reabrindo")
                        break
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                if fechou:
                    LOG.info("Microfone fechado: orbe inativo")
                elif self.running.is_set():
                    time.sleep(backoff)

        threading.Thread(target=_capture_worker_mac if MAC else _capture_worker,
                         daemon=True).start()

        while self.running.is_set():
            try:
                frame = self.audio_queue.get(timeout=0.5)
            except queue.Empty:
                if self.state == "processing" and self._processing_thread:
                    if not self._processing_thread.is_alive():
                        self._processing_thread = None
                        self.state = "listening"
                        self.speech_frames = 0
                        self.preroll_buffer.clear()
                if self._should_idle_end():
                    self._end_session("timeout 10s")
                self._poll_cmdfile()
                self._poll_ctl()
                continue
            if frame is None:
                break

            if self._should_idle_end():
                self._end_session("timeout 10s")
            self._poll_cmdfile()
            self._poll_ctl()

            rms = frame_rms(frame)
            if self.expecting_command or self.allow_interrupt:
                agora = time.monotonic()
                if agora - self._mic_orb_t >= 0.05:
                    self._mic_orb_t = agora
                    orb_cmd(f"mic {min(1.0, (rms / 32768.0) * 12.0):.3f}")
            is_speech = self._is_speech(frame, rms)

            if self._tts_playing and not self._tts_barge:
                # ACK do robô ("Sim?", "Pois não?"):
                # Ignora retorno do speaker para não abrir gravação sozinho sobre o ACK.
                # Só permite abrir fala se o usuário falar com energia real (> 3000 RMS).
                if rms < 3000:
                    self.speech_frames = 0
                    continue
            elif self.allow_interrupt and self._tts_playing and self._tts_barge:
                self._tts_ring.append((frame, is_speech))
                # Barge-in do commit 3c2b7c1: voz sustentada acima do piso,
                # sem estimar o eco. O rastreador exponencial de eco e a razão
                # rms > eco*1.40 saíram de novo: o rastreador subia junto com a
                # voz do Davi e a razão nunca se sustentava por cima da fala.
                agora = time.monotonic()
                onset = (
                    agora >= self._tts_barge_after
                    and is_speech
                    and rms >= INTERRUPT_MIN_RMS
                )
                if onset:
                    self._int_frames += 1
                else:
                    self._int_frames = 0
                if DEBUG_LEVELS:
                    self._dbg_max = max(self._dbg_max, rms)
                    self._dbg_sf = max(self._dbg_sf, self._int_frames)
                    if agora >= self._dbg_next:
                        self._dbg_next = agora + 1.0
                        LOG.info("[dbg] falando: rms_max=%.0f (piso %d) vad_max=%.2f "
                                 "int_frames_max=%d (precisa %d)",
                                 self._dbg_max, INTERRUPT_MIN_RMS, self._vad_max,
                                 self._dbg_sf, INTERRUPT_SPEECH_FRAMES)
                        self._dbg_max, self._dbg_sf = 0.0, 0
                        self._vad_max = 0.0
                if self._int_frames >= INTERRUPT_SPEECH_FRAMES:
                    anel = b"".join(f for f, _ in self._tts_ring)
                    if not self._voz_do_dono(np.frombuffer(anel, dtype=np.int16), "barge-in"):
                        self._int_frames = 0
                        continue
                    LOG.info("⚡ barge-in (rms=%.0f, piso=%d, %dms sustentados)",
                             rms, INTERRUPT_MIN_RMS,
                             INTERRUPT_SPEECH_FRAMES * FRAME_MS)
                    self._do_barge(rms)
                else:
                    continue

            if time.monotonic() < self._deaf_until and self.state != "recording":
                # Janela surda pós-TTS: não acumula speech_frames nem
                # preroll — eco residual abria gravação sozinho no Mic1.
                self._int_frames = 0
                self.speech_frames = 0
                continue

            if self.state == "listening":
                in_session = self.expecting_command or self.allow_interrupt
                if not in_session:
                    # idle: se oww estiver ativo, escuta wake word; senão, aguarda atalho/gesto
                    if self._tts_playing:
                        continue
                    if self.oww and self.oww.feed(frame):
                        LOG.info("⚡ wake word (%s)", WAKE_PROVEDOR)
                        self._trigger_session()
                    continue

                self.preroll_buffer.append((frame, is_speech))
                if is_speech:
                    self.speech_frames += 1
                    self._touch_session()
                else:
                    # Decaimento -1, não -2. Com -2, fala pausada (razão de
                    # voz ~70%) rende saldo quase nulo e a gravação nunca
                    # abre: medido, o acumulador empacava em 8 de 15 num
                    # comando a 154 wpm. Medido nos dois decaimentos:
                    #   comando pausado 154 wpm: pico 16 (-2) contra 25 (-1)
                    #   ambiente ruidoso:        pico 10 nos DOIS
                    # A margem contra ruído não muda; a tolerância a pausa
                    # entre palavras dobra.
                    self.speech_frames = max(0, self.speech_frames - 2)

                if DEBUG_LEVELS:
                    # Por que a fala não abriu gravação: mostra o nível que
                    # chegou, se o VAD concordou, e até onde o acumulador
                    # subiu. Sem isto o sintoma é mudo e só resta supor.
                    self._dbg_max = max(self._dbg_max, rms)
                    self._dbg_sf = max(self._dbg_sf, self.speech_frames)
                    if time.monotonic() >= self._dbg_next:
                        self._dbg_next = time.monotonic() + 1.0
                        LOG.info("[dbg] escutando: rms_max=%.0f (piso %d) "
                                 "vad_max=%.2f (limiar %.2f) "
                                 "speech_frames_max=%d (precisa %d)",
                                 self._dbg_max, MIN_SPEECH_RMS,
                                 self._vad_max, SILERO_THRESHOLD,
                                 self._dbg_sf, SUSTAINED_SPEECH_FRAMES)
                        self._dbg_max = 0.0
                        self._vad_max = 0.0
                        self._dbg_sf = 0

                if self.speech_frames >= SUSTAINED_SPEECH_FRAMES:
                    LOG.info("▶ Fala detectada, gravando...")
                    orb_cmd("warm")
                    self.state = "recording"
                    self.rec = Recorder()
                    for pf, ps in self.preroll_buffer:
                        self.rec.feed(pf, ps)
                    self.preroll_buffer.clear()
                    self.rec.echo_skip_until = 0

            elif self.state == "recording":
                assert self.rec
                self.rec.feed(frame, is_speech)
                teto = RECORD_MAX_TOQUE_SEC if self.rec.por_toque else RECORD_MAX_SEC
                if self.rec.seconds > teto or self.rec.is_done():
                    LOG.info("□ Gravação: %.1fs", self.rec.seconds)
                    # Inicia processamento em thread background
                    self.state = "processing"
                    self.speech_frames = 0
                    self._int_frames = 0
                    self.preroll_buffer.clear()
                    self._interrupted.clear()
                    rec = self.rec
                    self.rec = None
                    self._processing_thread = threading.Thread(
                        target=self._handle, args=(rec,), daemon=True
                    )
                    self._processing_thread.start()

            elif self.state == "processing":
                # Fala durante o raciocínio vira continuação do pedido
                # (_do_continuacao), com o critério do commit 3c2b7c1: voz
                # forte e sustentada, decaindo 3 quadros por quadro sem voz.
                self.preroll_buffer.append((frame, is_speech))
                if is_speech and rms >= INTERRUPT_MIN_RMS:
                    self._int_frames += 1
                else:
                    self._int_frames = max(0, self._int_frames - 3)
                if (BARGE_IN and self._int_frames >= INTERRUPT_SPEECH_FRAMES
                        and self._processing_thread
                        and self._processing_thread.is_alive()):
                    pre = b"".join(f for f, _ in self.preroll_buffer)
                    if not self._voz_do_dono(np.frombuffer(pre, dtype=np.int16), "continuação"):
                        self._int_frames = 0
                        continue
                    self._do_continuacao(rms)
                    continue
                if self._processing_thread and not self._processing_thread.is_alive():
                    self._processing_thread = None
                    self.state = "listening"
                    self.speech_frames = 0
                    self.preroll_buffer.clear()

        LOG.info("Daemon encerrado")

    def _handle(self, rec: Recorder):
        """Processa gravação: STT → comando. Wake já veio do microWakeWord."""
        handle_gen = self._tts_gen
        self._interrupted.clear()
        if not rec.has_spoken:
            if self._from_wake or self.expecting_command:
                self._from_wake = False
                self.expecting_command = True
                self._touch_session()
                orb_cmd("state listening")
                LOG.info("Wake ok, aguardando comando")
            return

        wav_path = rec.save_wav()
        if not wav_path:
            LOG.warning("Falha ao salvar áudio")
            return

        rms = rec.average_rms()
        ratio = rec.speech_ratio()
        if (
            rec.speech_frames_recorded < MIN_UTTER_SPEECH_FRAMES
            or rms < MIN_UTTER_RMS
            or (not rec.por_toque and rec.seconds >= RECORD_MAX_SEC - 0.4 and ratio < 0.30)
        ):
            LOG.info(
                "STT recusado (ruído) rms=%.0f ratio=%.2f speech=%d dur=%.1fs",
                rms, ratio, rec.speech_frames_recorded, rec.seconds,
            )
            try:
                os.unlink(wav_path)
            except OSError:
                pass
            if self.expecting_command or self._from_wake:
                self.expecting_command = True
                self._touch_session()
                orb_cmd("state listening")
            return

        # Antes do Groq: voz de outra pessoa nem sai da máquina.
        if not self._voz_do_dono(rec.voice_pcm(), "gravação"):
            try:
                os.unlink(wav_path)
            except OSError:
                pass
            if self.expecting_command or self._from_wake:
                self.expecting_command = True
                orb_cmd("state listening")
            return

        LOG.info("Enviando para Groq Whisper API...")
        t0 = time.time()
        text = transcribe_groq(wav_path)
        lat = time.time() - t0
        LOG.info("Groq respondeu em %.1fs: '%s'", lat, text[:200])
        if text:
            orb_cmd("line " + text[:200])

        try:
            os.unlink(wav_path)
        except OSError:
            pass

        if handle_gen != self._tts_gen:
            LOG.info("⚡ Processamento interrompido após STT")
            self._guardar_pedido(text)
            return

        from_wake = self._from_wake
        self._from_wake = False

        if not text:
            if self.expecting_command or from_wake:
                self.expecting_command = True
                self._touch_session()
                orb_cmd("state listening")
            return

        if self._is_tts_echo(text):
            LOG.info("eco TTS ignorado: %s", text[:80])
            self.expecting_command = True
            self._touch_session()
            orb_cmd("state listening")
            return

        if self._is_dismiss(text):
            LOG.info("dismiss: %s", text[:80])
            self._end_session("dismiss")
            return

        # "fica" / "solta" sozinhos são decididos aqui, sem ir ao agente
        if self._so_isso(text, _HOLD_RE) or self._so_isso(text, _RELEASE_RE):
            if self._so_isso(text, _HOLD_RE):
                self._travar("voz: " + text[:40])
            else:
                self._destravar("voz: " + text[:40])
            self.expecting_command = True
            self._touch_session()
            orb_cmd("state listening")
            return

        if self.expecting_command or from_wake:
            self.expecting_command = False
            cmd_clean = text.lower().strip()
            # "nada não" saiu daqui: é a forma mais comum de discordar em
            # português falado, e o Davi usa isso para contestar e SEGUIR a
            # conversa, não para cancelar. Sobrou só o que é inequivocamente
            # um pedido de desistência.
            if any(escape in cmd_clean for escape in ["cancela", "esquece", "cancelar"]):
                LOG.info("Comando cancelado pelo usuário")
                self._speak("Cancelado.")
                self._end_session("cancel")
                return
            stripped = detect_wake_word(text)
            cmd = text if stripped is None else (stripped or "")
            if not cmd:
                self.expecting_command = True
                self._touch_session()
                orb_cmd("state listening")
                return
            self._touch_session()
            orb_cmd("state thinking")
        else:
            cmd = detect_wake_word(text)

            if cmd is None:
                LOG.info("Wake word não detectada em: '%s'", text)
                return

            orb_cmd("show listening")
            self.allow_interrupt = True
            self._touch_session()

            if not cmd:
                self.expecting_command = True
                LOG.info("Wake word detectada de forma isolada. Aguardando comando na próxima fala...")
                orb_cmd("state listening")
                return

        if self._interrupted.is_set():
            # barge-in: o orbe FICA na tela para o novo comando
            LOG.info("⚡ Processamento interrompido antes do Hermes")
            self._guardar_pedido(cmd)
            return

        # O turno abortado pela continuação pode ainda estar no Groq: espera
        # ele guardar o pedido, senão a emenda chega antes do que emendar.
        velho, self._thread_velho = self._thread_velho, None
        if velho is not None and velho is not threading.current_thread():
            velho.join(timeout=4.0)
        cmd = self._emendar_pedido(cmd)
        LOG.info("Comando: \"%s\"", cmd)
        self._responder(cmd, handle_gen)

    def _responder(self, cmd: str, handle_gen: int, relato: bool = False):
        """Hermes + TTS de um turno. ``relato``: resultado de despacho, que
        nunca vira pedido em aberto para emenda."""
        self._touch_session()
        orb_cmd("state thinking")

        self._tts_turn_n = 0
        resposta = self._ask_hermes(cmd)
        LOG.info("Resposta: \"%s\"", resposta[:200] if resposta else "")

        if handle_gen != self._tts_gen or self._interrupted.is_set():
            LOG.info("⚡ Processamento interrompido após Hermes")
            # Nenhuma palavra da resposta falada = o Davi ainda formulava.
            self._guardar_pedido("" if relato else cmd, falou=self._tts_turn_n > 0)
            return
        if resposta and self._tts_turn_n == 0:
            self._tts_push(resposta)
            self._tts_drain()
        if self._interrupted.is_set():
            LOG.info("⚡ TTS interrompido — orbe mantido para o redirecionamento")
            self._touch_session()
            return
        self.expecting_command = True
        self.allow_interrupt = True
        self._touch_session()
        orb_cmd("state listening")


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════
def install_systemd():
    """Instala a unit do usuário a partir do modelo ao lado deste arquivo."""
    if MAC:
        aqui = Path(__file__).resolve().parent
        subprocess.run(["sh", str(aqui / "install-mac.sh")], check=True,
                       env=dict(os.environ, ORBE_PY=sys.executable))
        return
    aqui = Path(__file__).resolve().parent
    unit = (aqui / "hermes-voice.service.unit").read_text()
    unit = unit.replace("@ORBE@", str(aqui)).replace("@PY@", sys.executable)
    path = Path.home() / ".config/systemd/user/hermes-voice.service"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(f"Serviço instalado: {path}")
    print("Ative com: systemctl --user enable --now hermes-voice")


def test_once():
    """Testa: grava 1 utterance, envia pra Groq, mostra resultado."""
    print("Fale 'Ei Hermes <comando>' agora (escuta por 8s)...")
    frames_buf = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                         dtype=DTYPE, blocksize=FRAME_SIZE) as stream:
        for _ in range(int(8.0 / (FRAME_MS / 1000))):
            frame, _ = stream.read(FRAME_SIZE)
            frames_buf.append(frame.tobytes())

    raw = b"".join(frames_buf)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        from scipy.io.wavfile import write as wav_write
        wav_write(path, SAMPLE_RATE, np.frombuffer(raw, dtype=np.int16))
        print("Enviando para Groq...")
        text = transcribe_groq(path)
        print(f"Transcrição: \"{text}\"")
        if text:
            cmd = detect_wake_word(text)
            if cmd is not None:
                print(f"✓ Wake word detectada! Comando: \"{cmd}\"")
            else:
                print("✗ Wake word não detectada")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Voice Daemon (Groq Whisper)")
    parser.add_argument("--device", type=int, default=None, help="Índice do dispositivo de áudio")
    parser.add_argument("--install", action="store_true", help="Instalar como serviço systemd")
    parser.add_argument("--test", action="store_true", help="Testar transcrição 1x e sair")
    parser.add_argument("--debug", action="store_true", help="Log debug")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.install:
        install_systemd()
        sys.exit(0)

    if args.test:
        test_once()
        sys.exit(0)

    # PipeWire default — never raw ALSA hw:*. Native-16kHz ALSA nodes skip
    # resampling and often bind a silent capture while the real mic is the
    # Digital Microphone source.
    # No macOS o dispositivo fica None: segue a entrada padrão do sistema,
    # mesmo se ela mudar com o daemon rodando (AirPods etc.).
    if args.device is None and not MAC:
        try:
            devices = sd.query_devices()
            # Sempre pelo nó genérico do PipeWire, nunca pelo nó da fonte AEC
            # direto: o nó dedicado é exposto em 48 kHz fixo e recusa os
            # 16 kHz do VAD (PaErrorCode -9997). O "default" passa pelo
            # resampler e segue a fonte padrão, que é onde o AEC entra.
            # "pipewire" primeiro, NÃO "default". Medido em 2026-09-01 no mesmo
            # ambiente, 3s de captura por dispositivo:
            #   [11] pipewire  RMS max 11175
            #   [12] pulse     RMS max  8783
            #   [16] default   RMS max    859   <- 13x menos
            # Pelo "default" o sinal nunca cruza MIN_SPEECH_RMS (2200) e o
            # daemon fica surdo: nem wake, nem comando.
            preferred = ("pipewire", "pulse", "default")
            entradas = {
                d["name"].lower().strip(): i
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            }
            for alvo in preferred:
                if alvo in entradas:
                    args.device = entradas[alvo]
                    LOG.info("Dispositivo de entrada: [%d] %s",
                             args.device, devices[args.device]["name"])
                    break
            if args.device is None:
                args.device = sd.default.device[0]
                LOG.info("Dispositivo de entrada: default[%s]", args.device)
        except Exception as e:
            LOG.warning("Falha ao escolher dispositivo de entrada: %s", e)

    daemon = Daemon(device=args.device)
    daemon.run()
