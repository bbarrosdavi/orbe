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
sys.path.insert(0, "/home/davi/.hermes/hermes-agent/venv/lib/python3.11/site-packages")

HERMES_PROFILE_DIR = Path.home() / ".hermes" / "profiles" / "jarvis"

# Defaults do Hermes (tools/wake_word.py::_DEFAULTS), usados só se o perfil
# não disser nada.
OWW_MODEL = "/home/davi/.hermes/cache/wakewords/ei_hermes_pt.onnx"
OWW_THRESHOLD = 0.60
OWW_CONFIRM = 3
OWW_FRAME = 1280  # 80ms @ 16kHz — igual à GUI


def _load_wake_cfg():
    """Lê wake_word do config.yaml do perfil: a MESMA fonte que a GUI usa.

    Antes esses três números eram literais aqui, e o daemon divergia em
    silêncio de qualquer ajuste feito na GUI. Agora é uma configuração só:
    mexer no perfil muda os dois.

    Mapeamento do Hermes: ``sensitivity`` É o limiar de score (não há curva no
    meio, ver _OpenWakeWordEngine), e ``confirmation_frames`` é quantos
    quadros consecutivos acima do limiar são exigidos pra disparar.
    """
    modelo, limiar, confirma = OWW_MODEL, OWW_THRESHOLD, OWW_CONFIRM
    try:
        import yaml
        cfg = yaml.safe_load((HERMES_PROFILE_DIR / "config.yaml").read_text()) or {}
        ww = cfg.get("wake_word") or {}
        if isinstance(ww, dict):
            if ww.get("sensitivity") is not None:
                limiar = min(max(float(ww["sensitivity"]), 0.0), 1.0)
            if ww.get("confirmation_frames") is not None:
                confirma = min(max(int(ww["confirmation_frames"]), 1), 10)
            sub = ww.get("openwakeword")
            if isinstance(sub, dict) and sub.get("model"):
                modelo = str(sub["model"])
    except Exception as e:
        LOGGER_WARN.append(f"wake_word do perfil não lido ({e}); usando defaults")
    return modelo, limiar, confirma


LOGGER_WARN = []
OWW_MODEL, OWW_THRESHOLD, OWW_CONFIRM = _load_wake_cfg()

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
MIN_SPEECH_RMS = 1800
SUSTAINED_SPEECH_FRAMES = 15        # ~450ms pra abrir gravação
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
MIN_UTTER_RMS = 700

# Fonte virtual criada pelo module-echo-cancel do PipeWire. O nome do nó é
# hermes_aec_source; o sounddevice enxerga pela node.description.
AEC_SOURCE_NODE = "hermes_aec_source"
AEC_SOURCE_DESC = "HermesMicAEC"

SILENCE_TIMEOUT = 0.55              # silêncio = fim da fala
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
PIPER_MODEL = "/home/davi/.hermes/piper_models/pt_BR-dii-high.onnx"

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

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"

# HERMES_VOICE_DEBUG=1 liga o rastro de nível no estado listening.
DEBUG_LEVELS = os.environ.get("HERMES_VOICE_DEBUG") == "1"

LOG = logging.getLogger("hermes-voice")


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
        fired = False
        while len(self.buf) >= OWW_FRAME:
            chunk, self.buf = self.buf[:OWW_FRAME], self.buf[OWW_FRAME:]
            scores = self.model.predict(chunk)
            if any(s >= OWW_THRESHOLD for s in scores.values()):
                self.streak += 1
                if self.streak >= OWW_CONFIRM:
                    self.streak = 0
                    self.cool_until = time.monotonic() + 2.0
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
    if norm in _WHISPER_PHANTOMS:
        return True
    # Só pontuação: o modelo transcreveu silêncio.
    return not re.search(r"\w", norm)


# Atendimento ao wake. Curtíssimas de propósito: elas tocam antes de o Davi
# terminar de formular o pedido, então qualquer coisa mais longa atropela.
ACK_PHRASES = (
    "Sim?",
    "Diga.",
    "Fala.",
    "Pois não?",
    "Escuto.",
    "Manda.",
    "Aqui.",
    "Que foi?",
    "Oi?",
    "Pode falar.",
)
# O atendimento não arma barge-in: não faz sentido interromper um "Diga." de
# 300 ms. O _tts_push compara por aqui, então basta a frase estar na tupla.
_ACK_NORMS = frozenset(_normalize_utterance(p) for p in ACK_PHRASES)


def transcribe_groq(wav_path: str) -> str:
    """Envia WAV para Groq Whisper API, retorna texto transcrito."""
    if not GROQ_API_KEY:
        LOG.error("GROQ_API_KEY não definida")
        return ""

    try:
        import requests
        with open(wav_path, "rb") as f:
            files = {"file": f}
            data = {
                "model": GROQ_MODEL,
                "language": "pt",
                "response_format": "json",
                "temperature": 0.0,
                # Lista pura de vocabulário, sem frase em volta: prosa aqui
                # vira semente de alucinação (ver _WHISPER_PHANTOMS).
                "prompt": "Hermes, Jarvis, daemon, Docker, Python, Niri, "
                          "Wayland, API, front-end, back-end, output.",
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
        self.silence_frames = 0
        self.speech_frames_recorded = 0
        self.has_spoken = False
        self.silence_limit = int(SILENCE_TIMEOUT / (FRAME_MS / 1000))
        self.startup_silence_limit = int(1.2 / (FRAME_MS / 1000))
        self.echo_skip_until = 0

    def feed(self, frame: bytes, is_speech: bool):
        self.chunks.append(frame)
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
            wav_write(path, SAMPLE_RATE, np.frombuffer(raw, dtype=np.int16))
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

_gen_beep("/tmp/hv_beep_ack.wav", 1100, 0.13)
_gen_beep("/tmp/hv_beep_done.wav", 440, 0.12)

HERMES_BIN = "/home/davi/.hermes/hermes-agent/venv/bin/hermes"
HERMES_PROFILE = "jarvis"
HERMES_SESSION = "Bot Chat"
HERMES_PATH = "/home/davi/.hermes/hermes-agent/venv/bin:/home/davi/.local/bin:/usr/local/bin:/usr/bin:/bin"
ORB_BIN = "/home/davi/.hermes/scripts/hermes_voice_orb.py"
ORB_SOCK = "/run/user/1000/hermes-voice-orb.sock"


def get_desktop_env():
    """Garante PATH + PipeWire/D-Bus para o unit systemd (PATH mínimo)."""
    env = os.environ.copy()
    env["HOME"] = "/home/davi"
    env["PATH"] = HERMES_PATH
    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
    env["WAYLAND_DISPLAY"] = "wayland-1"
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


def orb_cmd(line: str) -> None:
    """Fala com o orbe. Sobe o processo só na primeira chamada (zero idle)."""
    payload = (line.strip() + "\n").encode()

    def _send() -> bool:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.12)
            s.connect(ORB_SOCK)
            s.sendall(payload)
            s.close()
            return True
        except OSError:
            return False

    if _send():
        return
    op = line.split()[0] if line else ""
    if op not in ("show", "state", "warm"):
        return
    try:
        logf = open("/tmp/hermes-voice-orb.log", "ab", buffering=0)
        subprocess.Popen(
            ["/usr/bin/python3", ORB_BIN],
            env=get_desktop_env(),
            start_new_session=True,
            stdout=logf,
            stderr=logf,
        )
    except Exception:
        return
    for _ in range(80):
        time.sleep(0.05)
        if _send():
            return


def frame_rms(frame: bytes) -> float:
    audio = np.frombuffer(frame, dtype=np.int16)
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


def play_beep(name: str):
    path = f"/tmp/hv_beep_{name}.wav"
    if os.path.exists(path):
        try:
            # fire-and-forget: o beep não pode atrasar o resto do fluxo
            subprocess.Popen(
                ["pw-play", path],
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
                    ["pw-play", mp3_out],
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
            subprocess.run(["pw-play", wav_out], capture_output=True, timeout=play_timeout, env=env)
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


# Bordas dos painéis do Rich. O CLI já entrega raciocínio e resposta em
# caixas distintas, então o roteamento é estrutural: nenhuma linha é
# classificada pelo conteúdo. Separar por idioma é impossível — o modelo
# rascunha a resposta em português dentro do próprio raciocínio.
#
# Raciocínio  → painel de canto quadrado:     ┌─ Reasoning ─┐ … └─┘
# Resposta    → caixa de canto arredondado:   ╭─ ⚔ Ares ─╮  … ╰─╯
# O título da caixa de resposta vem do display.skin do perfil (hoje "Ares"),
# por isso ele nunca é comparado com "Hermes".
REASON_OPEN = "┌"
REASON_CLOSE = "└"
ANSWER_OPEN = "╭"
ANSWER_CLOSE = "╰"
TOOL_MARKS = ("╎", "┊")


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
    return _scrub_cli(text)


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
# Daemon Principal
# ═══════════════════════════════════════════
class Daemon:
    def __init__(self, device: int | None = None):
        self.device = device
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.running = threading.Event()
        self.running.set()
        self.audio_queue: queue.Queue = queue.Queue()
        self.speech_frames = 0
        self.state = "listening"
        self.expecting_command = False
        self.preroll_buffer = collections.deque(maxlen=20)  # ~600ms de pre-roll
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
        self._tts_ring = collections.deque(maxlen=30)
        self._last_spoken = collections.deque(maxlen=8)
        try:
            self.oww = OpenWakeWordEar()
            for aviso in LOGGER_WARN:
                LOG.warning(aviso)
            LOG.info("openWakeWord: %s (sensitivity=%.2f, confirmation_frames=%d "
                     "— do wake_word: do perfil jarvis, mesma fonte da GUI)",
                     OWW_MODEL, OWW_THRESHOLD, OWW_CONFIRM)
        except Exception as e:
            self.oww = None
            LOG.error("openWakeWord falhou: %s", e)

        if not GROQ_API_KEY:
            LOG.warning("GROQ_API_KEY não definida! STT via Groq não funcionará.")

        self._last_ack = ""
        self._aec_ok = False
        self._hold_until = 0.0   # >0 = sessão travada; ver HOLD_MAX_SEC
        self._pedido_aberto = ""  # pedido cuja geração foi abortada no meio
        self._pedido_ts = 0.0
        self._continuando = False
        self._dbg_max, self._dbg_sf, self._dbg_next = 0.0, 0, 0.0
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
        try:
            info = sd.query_devices(self.device, "input")
            nativa = info.get("default_samplerate")
            if (isinstance(nativa, (int, float))
                    and not isinstance(nativa, bool) and nativa > 0):
                rate = int(round(nativa))
        except Exception as e:
            LOG.warning("Sem taxa nativa do dispositivo (%s); abrindo em %d Hz",
                        e, SAMPLE_RATE)
        bloco = max(1, int(round(FRAME_SIZE * rate / SAMPLE_RATE)))
        LOG.info("Captura: %d Hz nativos, bloco de %d → quadro de %d @ %d Hz "
                 "(reamostragem por média de janela, igual à GUI)",
                 rate, bloco, FRAME_SIZE, SAMPLE_RATE)
        return rate, bloco

    def _check_aec(self):
        """Diz no log se o mic está atrás do cancelador de eco.

        O daemon captura pelo nó "default" do PipeWire, então quem decide se
        há AEC é a fonte padrão. Sem ela o barge-in degrada de volta pro
        comportamento antigo: o mic ouve o próprio TTS a ~33 dB acima do
        piso e qualquer resposta longa vira gravação e comando novo.
        """
        if os.environ.get("HERMES_VOICE_NO_AEC") == "1":
            # Saída para teste acústico: com AEC ligado, áudio tocado pelo
            # alto-falante é justamente o que o módulo cancela, então não dá
            # para exercitar wake e comando por voz sintetizada. Também serve
            # para comparar A/B o efeito do cancelamento.
            LOG.warning("HERMES_VOICE_NO_AEC=1: cancelamento de eco IGNORADO "
                        "(o mic vai ouvir o próprio TTS)")
            return
        try:
            atual = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True, text=True, timeout=5, env=get_desktop_env(),
            ).stdout.strip()
        except Exception as e:
            LOG.warning("Não deu pra checar a fonte padrão: %s", e)
            return
        if atual == AEC_SOURCE_NODE:
            self._aec_ok = True
            LOG.info("Cancelamento de eco ativo (fonte padrão: %s)", atual)
            return
        # A fonte padrão volta sozinha pro microfone de hardware: o
        # WirePlumber prefere nó real a nó virtual, e a unit hermes-aec é
        # oneshot com RemainAfterExit, então reiniciar só o daemon não a
        # reafirma. Quem se importa com isso é este daemon, então é ele que
        # corrige, em vez de depender de ordenação de unit.
        try:
            existe = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5, env=get_desktop_env(),
            ).stdout
        except Exception:
            existe = ""
        if AEC_SOURCE_NODE not in existe:
            LOG.warning(
                "SEM cancelamento de eco: a fonte '%s' não existe. O módulo do "
                "PipeWire não subiu (ver ~/.config/pipewire/pipewire.conf.d/). "
                "O mic vai ouvir o próprio TTS.", AEC_SOURCE_NODE,
            )
            return
        try:
            subprocess.run(
                ["pactl", "set-default-source", AEC_SOURCE_NODE],
                capture_output=True, timeout=5, env=get_desktop_env(),
            )
            self._aec_ok = True
            LOG.info("Fonte padrão era '%s'; corrigida para '%s' "
                     "(cancelamento de eco ativo)", atual, AEC_SOURCE_NODE)
        except Exception as e:
            LOG.warning("Não deu pra fixar a fonte padrão: %s", e)

    def _callback(self, indata, frames, time_info, status):
        if status:
            LOG.warning("Audio: %s", status)
        bloco = indata[:, 0] if getattr(indata, "ndim", 1) == 2 else indata
        if self.capture_rate != SAMPLE_RATE:
            bloco = _resample_frame(bloco, FRAME_SIZE)
        self.audio_queue.put(np.ascontiguousarray(bloco, dtype=np.int16).tobytes())

    def _touch_session(self):
        self._session_until = time.monotonic() + SESSION_IDLE_SEC

    def _end_session(self, reason: str = "idle"):
        if not (self.expecting_command or self.allow_interrupt):
            orb_cmd("hide")
            return
        LOG.info("Sessão de voz encerrada (%s)", reason)
        self.expecting_command = False
        self.allow_interrupt = False
        self._chat_id = None
        self._voice_session = None
        # A trava não sobrevive à sessão: senão a próxima nasceria travada sem
        # ninguém ter pedido.
        self._hold_until = 0.0
        self._pedido_aberto = ""
        self._bump_tts()
        orb_cmd("hold 0")
        orb_cmd("hide")

    def _poll_cmdfile(self):
        p = Path(f"/run/user/{os.getuid()}/hermes-voice.cmd")
        try:
            txt = p.read_text()
            p.unlink(missing_ok=True)
        except OSError:
            return
        low = txt.lower()
        if "dismiss" in low:
            LOG.info("dismiss via cmdfile")
            self._kill_active(hide=True)
            self._end_session("dismiss")
        elif "hold" in low:
            self._hold_until = time.monotonic() + HOLD_MAX_SEC
            self._touch_session()
            orb_cmd("hold 1")
            LOG.info("Sessão travada a pedido do Jarvis (teto de %d min)",
                     int(HOLD_MAX_SEC // 60))
        elif "release" in low:
            if self._hold_until:
                self._hold_until = 0.0
                self._touch_session()
                orb_cmd("hold 0")
                LOG.info("Trava de sessão solta; timeout de %.0fs volta a valer",
                         SESSION_IDLE_SEC)

    def _is_dismiss(self, text: str) -> bool:
        return bool(_DISMISS_RE.search(text or ""))

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
        self._tts_proc = subprocess.Popen(
            ["/home/davi/.hermes/hermes-agent/venv/bin/python",
             "/home/davi/.hermes/scripts/hermes_voice_tts.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=logf,
            env={**get_desktop_env(),
                 "HERMES_HOME": "/home/davi/.hermes",
                 "HERMES_PROFILE": "jarvis"},
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
        if _normalize_utterance(s) not in _ACK_NORMS:
            self._tts_barge = True
            if self._tts_barge_after == 0.0:
                self._tts_barge_after = time.monotonic() + 0.55
            self._tts_playing = True
            self._last_spoken.append(s)
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
                    self._deaf_until = time.monotonic() + 0.55
                    orb_cmd("level 0")
                    self.speech_frames = 0
                    self._int_frames = 0
                    self.preroll_buffer.clear()
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
        opcoes = [p for p in ACK_PHRASES if p != self._last_ack] or list(ACK_PHRASES)
        self._last_ack = random.choice(opcoes)
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
        self._processing_thread = None
        self.expecting_command = True
        self.allow_interrupt = True
        self.state = "recording"
        self.rec = Recorder()
        self.rec.echo_skip_until = 6
        self.speech_frames = 0
        tail = list(self._tts_ring)[-8:]
        self._tts_ring.clear()
        self.preroll_buffer.clear()
        for pf, ps in tail:
            self.rec.feed(pf, ps)

    def _do_continuacao(self, rms: float):
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
        LOG.info("Fala durante a geração (rms=%.0f, %dms): continuação do pedido",
                 rms, INTERRUPT_SPEECH_FRAMES * FRAME_MS)
        self._int_frames = 0
        self._deaf_until = 0.0
        self._continuando = True
        self._kill_active(hide=False)
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
        """Rede de segurança para quando NÃO há cancelamento de eco.

        Com AEC não roda: o eco não chega mais ao sinal (medido, ele não
        sustenta nem 2 quadros contínuos em nenhum piso testado), e este
        filtro só produz dano.

        O dano é estrutural, não de calibragem. Numa conversa a réplica é
        lexicalmente parecida com a pergunta por construção: o Hermes
        perguntou "Quer mais uma?", o Davi respondeu "Fala mais um aí", e a
        similaridade difflib deu 0.643 contra um corte de 0.58 — a resposta
        foi descartada em silêncio como se fosse eco. Quanto mais natural o
        diálogo, mais o filtro barra. Por isso a comparação por similaridade
        saiu de vez; sobrou só contenção literal de uma fala LONGA, que é o
        que um eco de verdade produz.
        """
        if self._aec_ok:
            return False
        t = re.sub(r"[^a-z0-9áéíóúâêôãõç ]", "", (text or "").lower())
        t = " ".join(t.split())
        if len(t) < 8:
            return False
        for s in self._last_spoken:
            u = re.sub(r"[^a-z0-9áéíóúâêôãõç ]", "", s.lower())
            u = " ".join(u.split())
            # Falas curtas envenenam a contenção: "fala" está dentro de
            # metade das réplicas possíveis.
            if len(u) < 20:
                continue
            if t in u or u in t:
                return True
        return False

    # ── TTS interruptível ──

    def _speak(self, text: str):
        self._tts_push(text)

    def _ask_hermes(self, text: str) -> str:
        """Consulta Jarvis: raciocínio pro orbe, só a resposta pro TTS.

        O roteamento é por borda de painel, não por conteúdo. O CLI já separa
        os dois canais em caixas distintas (ver REASON_OPEN/ANSWER_OPEN), e o
        que estiver fora de qualquer caixa é cromo de terminal: banner, aviso
        de toolset, linha de sessão, rodapé de resume. Nada disso é falado.

        stdout e stderr saem em pipes separados. O PTY anterior fundia os
        dois num descritor só, e era daí que vinham falas como
        "Session ... found but has no messages. Starting fresh."
        """
        if not text or self._interrupted.is_set():
            return ""
        gen = self._tts_gen
        env = get_desktop_env()
        env.pop("HERMES_HOME", None)
        env["TERM"] = "dumb"
        # Painel largo: evita que o Rich quebre a resposta no meio de uma
        # frase e atrase o corte de sentença que alimenta o TTS.
        env["COLUMNS"] = "400"
        argv = [HERMES_BIN, "-p", HERMES_PROFILE, "chat",
                "-q", text, "--cli", "--yolo",
                "--reasoning", "low", "--max-turns", "8", "--run-budget", "45"]
        if self._chat_id:
            argv += ["--resume", self._chat_id]
        elif self._voice_session:
            argv += ["-c", self._voice_session, "--create-if-missing"]
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                close_fds=True,
            )
        except Exception as e:
            LOG.warning("Falha ao iniciar hermes: %s", e)
            return ""
        with self._proc_lock:
            self._active_proc = proc
        # O modelo vai levar segundos pensando; abre o socket do TTS agora,
        # em paralelo, pra primeira frase não pagar o handshake.
        self._tts_worker_warm()

        mode = None       # None = cromo do terminal | "reasoning" | "answer"
        answers = []      # respostas completas do turno, em ordem
        cur = []          # caixa de resposta em construção
        sent_buf = ""

        def _consume(raw: str):
            nonlocal mode, cur, sent_buf
            if self._tts_gen != gen:
                return
            line = _ANSI_RE.sub("", raw or "")
            line = _CSI_LEFTOVER.sub("", line).replace("\r", "").strip()
            line = line.strip("│").strip()   # borda lateral, quando desenhada
            if not line:
                return
            head = line[0]

            if head == ANSWER_OPEN:
                mode, cur = "answer", []
                return
            if head == ANSWER_CLOSE:
                if mode == "answer" and cur:
                    answers.append(" ".join(cur))
                mode, cur = None, []
                return
            if head == REASON_OPEN:
                mode = "reasoning"
                orb_cmd("state thinking")
                return
            if head == REASON_CLOSE:
                mode = None
                return

            if mode == "reasoning":
                # Raciocínio é exclusivo do overlay: nunca entra na fila de
                # voz. O orbe já mantém janela rolante das últimas linhas.
                orb_cmd("line " + line[:200])
                return
            if mode == "answer":
                cur.append(line)
                sent_buf += line + " "
                sents, sent_buf = _take_sentences(sent_buf)
                for s in sents:
                    self._tts_push(s, gen)
                return
            if head in TOOL_MARKS:
                orb_cmd("state tools")
                return
            # Fora de caixa é cromo. A única coisa aproveitável é o id de
            # sessão do rodapé, que encadeia o próximo turno no mesmo chat.
            if line.lower().startswith("session:"):
                sid = line.split(":", 1)[1].strip().split()
                if sid:
                    self._chat_id = sid[0]
                    LOG.info("chat id %s", sid[0])

        out_fd = proc.stdout.fileno()
        err_fd = proc.stderr.fileno()
        live = {out_fd, err_fd}
        buf = ""
        errbuf = ""
        deadline = time.monotonic() + 120
        try:
            while live:
                if self._tts_gen != gen or self._interrupted.is_set():
                    proc.kill()
                    return ""
                if time.monotonic() > deadline:
                    LOG.warning("hermes estourou o teto de 120s")
                    proc.kill()
                    break
                r, _, _ = select.select(list(live), [], [], 0.12)
                for fd in r:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        live.discard(fd)
                        continue
                    if not chunk:
                        live.discard(fd)
                        continue
                    data = chunk.decode("utf-8", "replace").replace("\r\n", "\n")
                    if fd == err_fd:
                        errbuf += data
                        while "\n" in errbuf:
                            eline, errbuf = errbuf.split("\n", 1)
                            if eline.strip():
                                LOG.debug("hermes stderr: %s", eline.strip()[:200])
                        continue
                    buf += data
                    while "\n" in buf:
                        raw, buf = buf.split("\n", 1)
                        _consume(raw)
            if buf.strip():
                _consume(buf)
            proc.wait(timeout=8)
        except Exception as e:
            LOG.warning("hermes stream: %s", e)
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            if sent_buf.strip() and self._tts_gen == gen:
                self._tts_push(sent_buf.strip(), gen)
            if self._tts_gen == gen:
                self._tts_drain()
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except Exception:
                    pass
            with self._proc_lock:
                self._active_proc = None
        if mode == "answer" and cur:
            answers.append(" ".join(cur))
        return "\n".join(a.strip() for a in answers if a.strip()).strip()

    # ── Main Loop ──

    def run(self):
        LOG.info("═══ Hermes Voice Daemon v4 (Groq Whisper) ═══")
        LOG.info("VAD: %d | Groq: %s", VAD_AGGRESSIVENESS, GROQ_MODEL)
        LOG.info("Diga \"Ei Hermes\" seguido do comando...")
        LOG.info("Wake: openWakeWord local (mesmo modelo da GUI)")
        self._ensure_tts_worker()
        threading.Thread(target=self._tts_consumer, daemon=True).start()
        threading.Thread(target=lambda: orb_cmd("warm"), daemon=True).start()

        # Inicializa volume de áudio do sistema (sink e source) no máximo (100%)
        env = get_desktop_env()
        try:
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "1.0"], capture_output=True, env=env)
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", "1.0"], capture_output=True, env=env)
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], capture_output=True, env=env)
            subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "100%"], capture_output=True, env=env)
            LOG.info("Volume de áudio inicializado no máximo (100%).")
        except Exception as e:
            LOG.warning("Erro ao inicializar volume de áudio: %s", e)

        # Taxa NATIVA do dispositivo, com blocksize proporcional, e a
        # reamostragem feita por nós em _callback. É o caminho da orelhinha da
        # GUI (tools/wake_word.py): ela nunca pede 16 kHz ao PortAudio.
        with sd.InputStream(
            samplerate=self.capture_rate, channels=CHANNELS,
            dtype=DTYPE, blocksize=self.capture_block,
            device=self.device,
            callback=self._callback,
        ):
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
                    continue
                if frame is None:
                    break

                if self._should_idle_end():
                    self._end_session("timeout 10s")
                self._poll_cmdfile()

                rms = frame_rms(frame)
                is_speech = (
                    rms >= MIN_SPEECH_RMS
                    and self.vad.is_speech(frame, SAMPLE_RATE)
                )

                if self._tts_playing and not self._tts_barge:
                    pass
                elif self.allow_interrupt and self._tts_playing and self._tts_barge:
                    self._tts_ring.append((frame, is_speech))
                    # O AEC tira a fala do orbe do sinal, então basta detectar
                    # voz sustentada. O rastreador exponencial de eco e a
                    # comparação rms > eco*1.45 saíram daqui: existiam só pra
                    # adivinhar quanto do que o mic ouvia era o próprio orbe.
                    onset = (
                        time.monotonic() >= self._tts_barge_after
                        and is_speech
                        and rms >= INTERRUPT_MIN_RMS
                    )
                    if onset:
                        self._int_frames += 1
                    else:
                        self._int_frames = 0
                    if self._int_frames >= INTERRUPT_SPEECH_FRAMES:
                        self._do_barge(rms)
                    else:
                        continue

                if time.monotonic() < self._deaf_until and self.state != "recording":
                    self.speech_frames = 0
                    self._int_frames = 0
                    if self.state == "listening":
                        self.preroll_buffer.clear()
                    continue

                if self.state == "listening":
                    in_session = self.expecting_command or self.allow_interrupt
                    if not in_session:
                        # idle: só openWakeWord. sem Groq, sem gravação.
                        if self.oww and self.oww.feed(frame):
                            LOG.info("⚡ openWakeWord: ei hermes")
                            orb_cmd("clear")
                            orb_cmd("show listening")
                            self.expecting_command = True
                            self.allow_interrupt = True
                            self._from_wake = True
                            self._chat_id = None
                            self._voice_session = f"orb-{int(time.time())}"
                            # Wake novo é turno novo: nada de emendar num
                            # pedido de uma sessão que já morreu.
                            self._pedido_aberto = ""
                            self._continuando = False
                            self._tts_barge = False
                            self._tts_barge_after = 0.0
                            self._touch_session()
                            self._tts_push(self._pick_ack())
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
                        self.speech_frames = max(0, self.speech_frames - 1)

                    if DEBUG_LEVELS:
                        # Por que a fala não abriu gravação: mostra o nível que
                        # chegou, se o VAD concordou, e até onde o acumulador
                        # subiu. Sem isto o sintoma é mudo e só resta supor.
                        self._dbg_max = max(self._dbg_max, rms)
                        self._dbg_sf = max(self._dbg_sf, self.speech_frames)
                        if time.monotonic() >= self._dbg_next:
                            self._dbg_next = time.monotonic() + 1.0
                            LOG.info("[dbg] escutando: rms_max=%.0f (piso %d) "
                                     "speech_frames_max=%d (precisa %d)",
                                     self._dbg_max, MIN_SPEECH_RMS,
                                     self._dbg_sf, SUSTAINED_SPEECH_FRAMES)
                            self._dbg_max = 0.0
                            self._dbg_sf = 0

                    if self.speech_frames >= SUSTAINED_SPEECH_FRAMES:
                        LOG.info("▶ Fala detectada, gravando...")
                        orb_cmd("warm")
                        self.state = "recording"
                        self.rec = Recorder()
                        for pf, ps in self.preroll_buffer:
                            self.rec.feed(pf, ps)
                        self.preroll_buffer.clear()
                        self.rec.echo_skip_until = 20 if self._tts_playing else 8

                elif self.state == "recording":
                    assert self.rec
                    self.rec.feed(frame, is_speech)
                    if self.rec.seconds > RECORD_MAX_SEC or self.rec.is_done():
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
                    # Continua monitorando mic enquanto processa em background
                    self.preroll_buffer.append((frame, is_speech))
                    if is_speech:
                        self.speech_frames += 1
                    else:
                        self.speech_frames = max(0, self.speech_frames - 2)
                    # contador de interrupção: exige voz FORTE e sustentada;
                    # ruído ambiente/teclado ficam abaixo do piso de RMS
                    if is_speech and rms >= INTERRUPT_MIN_RMS:
                        self._int_frames += 1
                    else:
                        self._int_frames = max(0, self._int_frames - 3)

                    # Esse contador existia e nunca era lido: falar durante a
                    # geração não produzia efeito nenhum, e o resto da frase só
                    # era ouvido depois da resposta inteira sair.
                    if (self._int_frames >= INTERRUPT_SPEECH_FRAMES
                            and self._processing_thread
                            and self._processing_thread.is_alive()):
                        self._do_continuacao(rms)
                        continue

                    # Thread de processamento terminou naturalmente
                    if self._processing_thread and not self._processing_thread.is_alive():
                        self._processing_thread = None
                        self.state = "listening"
                        self.speech_frames = 0
                        self.preroll_buffer.clear()

        LOG.info("Daemon encerrado")

    def _handle(self, rec: Recorder):
        """Processa gravação: STT → comando. Wake já veio do openWakeWord."""
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
            or (rec.seconds >= RECORD_MAX_SEC - 0.4 and ratio < 0.30)
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

        LOG.info("Enviando para Groq Whisper API...")
        t0 = time.time()
        text = transcribe_groq(wav_path)
        lat = time.time() - t0
        LOG.info("Groq respondeu em %.1fs: '%s'", lat, text[:200])

        try:
            os.unlink(wav_path)
        except OSError:
            pass

        if handle_gen != self._tts_gen:
            LOG.info("⚡ Processamento interrompido após STT")
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
            return

        cmd = self._emendar_pedido(cmd)
        LOG.info("Comando: \"%s\"", cmd)
        self._touch_session()
        orb_cmd("state thinking")

        self._tts_turn_n = 0
        resposta = self._ask_hermes(cmd)
        LOG.info("Resposta: \"%s\"", resposta[:200] if resposta else "")

        if handle_gen != self._tts_gen or self._interrupted.is_set():
            LOG.info("⚡ Processamento interrompido após Hermes")
            if self._continuando and self._tts_turn_n == 0:
                # Nenhuma palavra da resposta foi falada: o Davi ainda estava
                # formulando. Guarda o pedido para a próxima fala emendar.
                self._pedido_aberto = cmd
                self._pedido_ts = time.monotonic()
            self._continuando = False
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
    unit = (
        "[Unit]\n"
        "Description=Hermes Voice Daemon (Groq Whisper)\n"
        "After=graphical-session.target\n"
        "Wants=graphical-session.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStart=/home/davi/.hermes/scripts/hermes_voice_daemon.py\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "Environment=HOME=/home/davi\\n"
        "Environment=PATH=/home/davi/.hermes/hermes-agent/venv/bin:/home/davi/.local/bin:/usr/local/bin:/usr/bin:/bin\\n"
        "Environment=XDG_RUNTIME_DIR=/run/user/1000\\n"
        "Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus\\n"
        "Environment=WAYLAND_DISPLAY=wayland-1\\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
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
    if args.device is None:
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
