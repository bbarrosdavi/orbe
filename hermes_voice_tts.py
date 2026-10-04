#!/usr/bin/env python3
"""TTS do orb. Segue tts.provider do perfil Jarvis a cada frase.
xAI = mesmo OAuth da GUI (wss://api.x.ai/v1/tts → PCM 24 kHz).
CANCEL em thread — corta pw-cat no meio da frase.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

ENV_PATH = Path.home() / ".hermes" / ".env"
JARVIS_CFG = Path.home() / ".hermes" / "profiles" / "jarvis" / "config.yaml"
HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
PIPER_BIN = str(Path.home() / ".hermes/hermes-agent/venv/bin/piper")
PIPER_MODEL = str(Path.home() / ".hermes/piper_models/pt_BR-faber-medium.onnx")
RATE = 24000
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
ACK_DIR = Path.home() / ".hermes" / "cache" / "voice_ack"
ACK_PHRASES = (
    "Sim?", "Pois não?", "Manda.", "Escuto.",
)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _load_env():
    os.environ.setdefault("HERMES_HOME", str(Path.home() / ".hermes"))
    os.environ.setdefault("HERMES_PROFILE", "jarvis")
    if str(HERMES_AGENT) not in sys.path:
        sys.path.insert(0, str(HERMES_AGENT))
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _jarvis_tts() -> dict:
    out = {
        "provider": "gemini",
        "gemini_model": "gemini-3.1-flash-tts-preview",
        "gemini_voice": "Kore",
        "xai_voice": "eve",
        "xai_language": "pt",
    }
    try:
        import yaml
        cfg = yaml.safe_load(JARVIS_CFG.read_text()) or {}
        tts = cfg.get("tts") or {}
        g = tts.get("gemini") or {}
        x = tts.get("xai") or {}
        out["gemini_model"] = str(g.get("model") or out["gemini_model"])
        out["gemini_voice"] = str(g.get("voice") or out["gemini_voice"])
        out["xai_voice"] = str(x.get("voice_id") or out["xai_voice"])
        out["xai_language"] = str(x.get("language") or out["xai_language"])
        p = str(tts.get("provider") or "gemini").lower().strip()
        if p in ("grok", "grok-tts", "xai-oauth"):
            p = "xai"
        out["provider"] = p
        out["piper_voice"] = str((tts.get("piper") or {}).get("voice") or "")
    except Exception as e:
        sys.stderr.write(f"cfg: {e}\n")
    # Escolhas do app de configuração do orbe; vazio = segue o perfil.
    try:
        import hermes_voice_config as vcfg
        v = vcfg.carregar()["voz"]
        if v.get("tts_provedor"):
            out["provider"] = str(v["tts_provedor"])
        if v.get("gemini_voz"):
            out["gemini_voice"] = str(v["gemini_voz"])
        if v.get("xai_voz"):
            out["xai_voice"] = str(v["xai_voz"])
        if v.get("piper_voz"):
            out["piper_voice"] = str(v["piper_voz"])
    except Exception as e:
        sys.stderr.write(f"cfg do app: {e}\n")
    return out


def _gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def clean(text: str) -> str:
    t = _ANSI.sub("", text or "")
    t = re.sub(r"[\u2500-\u257F╭╮╰╯│─┌┐└┘┊╌╎]+", " ", t)
    t = "".join(ch for ch in t if ch >= " " or ch in "\n")
    return " ".join(t.split())


def _ack_key(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").strip().lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w]+", "_", t).strip("_")
    return t


def _ack_path(text: str) -> Path:
    return ACK_DIR / (_ack_key(text) + ".s16")


def _is_ack(text: str) -> bool:
    return _ack_key(text) in {_ack_key(p) for p in ACK_PHRASES}


class Worker:
    # Conexao quente do WebSocket da xAI. Medido em 2026-09-01: handshake
    # 0.56s contra 0.53s de sintese, ou seja mais da METADE da latencia ate o
    # primeiro audio e so abrir socket. Abrindo o socket quando o turno
    # comeca — enquanto o modelo ainda gera — a primeira frase sai em ~0.55s
    # em vez de ~1.10s. TTL curto porque socket ocioso e fechado do outro lado.
    WARM_TTL = 45.0

    def __init__(self):
        self.cancel = threading.Event()
        self._play = None
        self._play_lock = threading.Lock()
        self._cmds: queue.Queue = queue.Queue()
        self._loop = None            # loop persistente; a conexao quente e dele
        self._warm = None            # future da conexao pre-aberta
        self._warm_at = 0.0
        self._warm_lock = threading.Lock()

    def _kill_play(self):
        with self._play_lock:
            p = self._play
            self._play = None
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def _open_play(self, rate: int) -> subprocess.Popen:
        self._kill_play()
        proc = subprocess.Popen(
            ["pw-cat", "-p", "-a", "--format", "s16", "--rate", str(rate),
             "--channels", "1", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with self._play_lock:
            self._play = proc
        # pw-cat descarta o primeiro buffer; 80ms de silêncio evita a fala
        # começar no meio da primeira sílaba.
        if proc.stdin:
            try:
                proc.stdin.write(b"\x00" * (rate * 2 * 80 // 1000))
                proc.stdin.flush()
            except BrokenPipeError:
                pass
        return proc

    LEVEL_WIN_MS = 40

    def _level(self, pcm: bytes):
        """Emite um LEVEL por janela de ~40ms, com nível e tom reais.

        Antes saía UM level por chunk do WebSocket. Medido em 2026-09-01:
        7 amostras de envelope para uma frase inteira, ou seja ~1 ponto por
        segundo. O orbe desenha a 60 fps, então entre dois pontos ele apenas
        decaía — a fala parecia inexpressiva porque o anel não tinha
        informação de sílaba para reagir, não porque a amplitude fosse baixa.
        A 40ms saem ~25 pontos por segundo, que é resolução de sílaba.

        O tom era a constante 0.50, o que travava a cor no meio exato entre
        graves e agudos. Agora vem da taxa de cruzamentos por zero, que separa
        vogal (baixa) de fricativa (alta) a custo de uma chamada em C.
        """
        if len(pcm) < 4:
            return
        step = int(RATE * self.LEVEL_WIN_MS / 1000) * 2   # bytes por janela
        if step < 2:
            return
        try:
            import audioop
        except ImportError:
            audioop = None
        for off in range(0, len(pcm) - step + 1, step):
            win = pcm[off:off + step]
            if audioop is not None:
                rms = audioop.rms(win, 2) / 32768.0
                # cruzamentos por amostra: ~0.02 em vogal, ~0.20 em fricativa
                zcr = audioop.cross(win, 2) / max(1, len(win) // 2)
                tone = min(1.0, max(0.0, zcr / 0.15))
            else:
                import struct
                n = len(win) // 2
                s = struct.unpack("<" + "h" * n, win)
                rms = ((sum(v * v for v in s) / n) ** 0.5) / 32768.0
                tone = 0.5
            print(f"LEVEL {min(1.0, rms * 6.5):.3f} {tone:.2f}", flush=True)

    def _feed(self, play, raw: bytes) -> bool:
        if self.cancel.is_set():
            self._kill_play()
            return False
        if play.stdin:
            try:
                play.stdin.write(raw)
                play.stdin.flush()
            except BrokenPipeError:
                return False
        self._level(raw)
        return True

    def _save_ack(self, text: str, pcm: bytes) -> None:
        if not _is_ack(text) or len(pcm) < 64:
            return
        try:
            ACK_DIR.mkdir(parents=True, exist_ok=True)
            path = _ack_path(text)
            if path.exists() and path.stat().st_size >= len(pcm):
                return
            path.write_bytes(pcm)
            sys.stderr.write(f"ack cache write {path.name} {len(pcm)}b\n")
        except OSError as e:
            sys.stderr.write(f"ack cache write fail {e}\n")

    def _play_ack_cache(self, text: str) -> bool:
        path = _ack_path(text)
        if not path.exists() or path.stat().st_size < 64:
            return False
        t0 = time.time()
        data = path.read_bytes()
        play = self._open_play(RATE)
        sys.stderr.write(f"ack cache {path.name} ttfa {time.time() - t0:.3f}s\n")
        step = int(RATE * self.LEVEL_WIN_MS / 1000) * 2
        for off in range(0, len(data), max(step, 2)):
            if not self._feed(play, data[off:off + step]):
                break
        if play and play.stdin:
            try:
                play.stdin.close()
            except OSError:
                pass
        if play:
            try:
                play.wait(timeout=8)
            except Exception:
                pass
        return True

    def _fill_ack_cache(self) -> None:
        """Sintetiza ACKs via HTTP, sem tocar no speaker."""
        missing = [p for p in ACK_PHRASES if not (_ack_path(p).exists() and _ack_path(p).stat().st_size > 64)]
        if not missing:
            return
        try:
            from tools.xai_http import resolve_xai_http_credentials
            import requests
        except Exception as e:
            sys.stderr.write(f"ack cache deps {e}\n")
            return
        cfg = _jarvis_tts()
        token = str(resolve_xai_http_credentials(prefer_api_key=False).get("api_key") or "").strip()
        if not token:
            sys.stderr.write("ack cache: sem token\n")
            return
        ACK_DIR.mkdir(parents=True, exist_ok=True)
        for phrase in missing:
            if self.cancel.is_set():
                return
            try:
                r = requests.post(
                    "https://api.x.ai/v1/tts",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json={"text": phrase, "voice_id": cfg["xai_voice"],
                          "language": cfg["xai_language"],
                          "output_format": {"codec": "pcm", "sample_rate": RATE}},
                    timeout=40,
                )
                if r.status_code != 200 or len(r.content) < 64:
                    sys.stderr.write(f"ack cache {phrase!r} http {r.status_code}\n")
                    continue
                _ack_path(phrase).write_bytes(r.content)
                sys.stderr.write(f"ack cache fill {_ack_path(phrase).name} {len(r.content)}b\n")
            except Exception as e:
                sys.stderr.write(f"ack cache fill {phrase!r}: {e}\n")

    def gemini(self, text: str, model: str, voice: str) -> bool:
        import requests
        key = _gemini_key()
        if not key:
            return False
        url = f"{GEMINI_BASE}/models/{model}:streamGenerateContent"
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}},
                },
            },
        }
        t0 = time.time()
        r = requests.post(
            url, params={"alt": "sse", "key": key}, json=payload, timeout=20, stream=True,
        )
        if r.status_code != 200:
            sys.stderr.write(f"gemini http {r.status_code} {r.text[:200]}\n")
            return False
        play = None
        n = 0
        try:
            for line in r.iter_lines(decode_unicode=True):
                if self.cancel.is_set():
                    self._kill_play()
                    return True
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                    parts = ev["candidates"][0]["content"]["parts"]
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                for part in parts:
                    inline = part.get("inlineData") or part.get("inline_data") or {}
                    b64 = inline.get("data") or ""
                    if not b64:
                        continue
                    raw = base64.b64decode(b64)
                    if play is None:
                        play = self._open_play(RATE)
                        sys.stderr.write(f"gemini ttfa {time.time() - t0:.2f}s voice={voice}\n")
                    if not self._feed(play, raw):
                        return True
                    n += 1
        finally:
            if play and play.stdin:
                try:
                    play.stdin.close()
                except OSError:
                    pass
            if play:
                try:
                    play.wait(timeout=8)
                except Exception:
                    pass
        return n > 0

    def _ws_url(self, voice_id: str, language: str) -> str:
        from urllib.parse import urlencode
        return "wss://api.x.ai/v1/tts?" + urlencode({
            "language": language,
            "voice": voice_id,
            "codec": "pcm",
            "sample_rate": str(RATE),
        })

    def _ensure_loop(self):
        """Loop asyncio persistente. A conexao quente pertence a ele, entao a
        sintese tambem roda nele: socket aberto num loop nao serve em outro."""
        import asyncio
        if self._loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, daemon=True).start()
            self._loop = loop
        return self._loop

    def prewarm(self):
        """Abre o WebSocket antes de existir texto pra falar.

        Chamado pelo daemon quando o turno comeca. Fail-soft por inteiro: se
        qualquer coisa aqui der errado, o say() cai no caminho de sempre e a
        unica perda e a latencia que ja existia.
        """
        import asyncio
        try:
            cfg = _jarvis_tts()
            if cfg["provider"] != "xai":
                return
            with self._warm_lock:
                if self._warm is not None and (time.time() - self._warm_at) < self.WARM_TTL:
                    return
            from tools.xai_http import resolve_xai_http_credentials
            token = str(
                resolve_xai_http_credentials(prefer_api_key=False).get("api_key") or ""
            ).strip()
            if not token:
                return
            import websockets
            url = self._ws_url(cfg["xai_voice"], cfg["xai_language"])

            async def _open():
                return await websockets.connect(
                    url,
                    additional_headers={"Authorization": f"Bearer {token}"},
                    open_timeout=20,
                )

            fut = asyncio.run_coroutine_threadsafe(_open(), self._ensure_loop())
            with self._warm_lock:
                self._warm = fut
                self._warm_at = time.time()
            sys.stderr.write("prewarm: abrindo ws\n")
        except Exception as e:
            sys.stderr.write(f"prewarm fail {e}\n")

    def _take_warm(self):
        """Devolve a conexao pre-aberta, ou None. Consome: so serve uma vez."""
        with self._warm_lock:
            fut, at = self._warm, self._warm_at
            self._warm, self._warm_at = None, 0.0
        if fut is None or (time.time() - at) >= self.WARM_TTL:
            if fut is not None:
                fut.cancel()
            return None
        try:
            # Se o handshake ainda esta em curso, esperar aqui nao custa nada:
            # teriamos de abrir a conexao de qualquer jeito.
            ws = fut.result(timeout=20)
        except Exception as e:
            sys.stderr.write(f"warm descartada: {e}\n")
            return None
        if getattr(ws, "close_code", None) is not None:
            return None
        return ws

    def xai(self, text: str, voice_id: str, language: str) -> bool:
        from urllib.parse import urlencode
        from tools.xai_http import resolve_xai_http_credentials

        creds = resolve_xai_http_credentials(prefer_api_key=False)
        token = str(creds.get("api_key") or "").strip()
        if not token:
            sys.stderr.write("xai: sem token OAuth\n")
            return False
        t0 = time.time()
        try:
            ok = self._xai_ws(text, token, voice_id, language, t0)
            if ok or self.cancel.is_set():
                return True
        except Exception as e:
            sys.stderr.write(f"xai ws fail {e}\n")
        try:
            return self._xai_http(text, token, voice_id, language, t0)
        except Exception as e:
            sys.stderr.write(f"xai http fail {e}\n")
            return False

    def _xai_ws(self, text, token, voice_id, language, t0) -> bool:
        import asyncio
        import websockets

        ws_url = self._ws_url(voice_id, language)
        warm = self._take_warm()

        async def _pump(ws, quente: bool):
            play = None
            n = 0
            pcm = bytearray()
            await ws.send(json.dumps({"type": "text.delta", "delta": text}))
            await ws.send(json.dumps({"type": "text.done"}))
            async for message in ws:
                if self.cancel.is_set():
                    self._kill_play()
                    return n > 0
                raw = b""
                if isinstance(message, (bytes, bytearray, memoryview)):
                    raw = bytes(message)
                else:
                    try:
                        env = json.loads(message)
                    except (ValueError, TypeError):
                        continue
                    et = env.get("type")
                    if et in ("audio.done", "done"):
                        break
                    if et == "error":
                        sys.stderr.write(f"xai ws error {env}\n")
                        break
                    if et == "audio.delta":
                        delta = env.get("delta") or ""
                        if delta:
                            raw = base64.b64decode(delta)
                if not raw:
                    continue
                pcm.extend(raw)
                if play is None:
                    play = self._open_play(RATE)
                    sys.stderr.write(
                        f"xai ttfa {time.time() - t0:.2f}s voice={voice_id}"
                        f" {'quente' if quente else 'frio'}\n"
                    )
                if not self._feed(play, raw):
                    break
                n += 1
            if play and play.stdin:
                try:
                    play.stdin.close()
                except OSError:
                    pass
            if play:
                try:
                    play.wait(timeout=8)
                except Exception:
                    pass
            if n > 0:
                self._save_ack(text, bytes(pcm))
            return n > 0

        async def _fresh():
            async with websockets.connect(
                ws_url,
                additional_headers={"Authorization": f"Bearer {token}"},
                open_timeout=20,
            ) as ws:
                return await _pump(ws, False)

        async def _reuse(ws):
            try:
                return await _pump(ws, True)
            finally:
                try:
                    await ws.close()
                except Exception:
                    pass

        if warm is not None:
            # A conexao quente pertence ao loop persistente, entao a sintese
            # roda la. Se falhar, cai no caminho frio de sempre.
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    _reuse(warm), self._ensure_loop())
                return bool(fut.result(timeout=180))
            except Exception as e:
                sys.stderr.write(f"ws quente falhou, refazendo frio: {e}\n")
        return bool(asyncio.run(_fresh()))

    def _xai_http(self, text, token, voice_id, language, t0) -> bool:
        import requests
        r = requests.post(
            "https://api.x.ai/v1/tts",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "voice_id": voice_id,
                "language": language,
                "output_format": {"codec": "pcm", "sample_rate": RATE},
            },
            timeout=40,
            stream=True,
        )
        if r.status_code != 200:
            sys.stderr.write(f"xai http {r.status_code} {r.text[:200]}\n")
            return False
        play = None
        n = 0
        try:
            for chunk in r.iter_content(4096):
                if self.cancel.is_set():
                    self._kill_play()
                    return True
                if not chunk:
                    continue
                if play is None:
                    play = self._open_play(RATE)
                    sys.stderr.write(f"xai http ttfa {time.time() - t0:.2f}s\n")
                if not self._feed(play, chunk):
                    return True
                n += 1
        finally:
            if play and play.stdin:
                try:
                    play.stdin.close()
                except OSError:
                    pass
            if play:
                try:
                    play.wait(timeout=8)
                except Exception:
                    pass
        return n > 0

    def piper(self, text: str, modelo: str = PIPER_MODEL) -> bool:
        if not Path(PIPER_BIN).exists() or not Path(modelo).exists():
            return False
        wav = f"/tmp/hermes-orb-tts-{os.getpid()}.wav"
        try:
            r = subprocess.run(
                [PIPER_BIN, "--model", modelo, "--output_file", wav],
                input=text, text=True, capture_output=True, timeout=12,
            )
            if r.returncode != 0 or not os.path.exists(wav) or os.path.getsize(wav) < 64:
                return False
            if self.cancel.is_set():
                return True
            subprocess.run(["pw-play", wav], timeout=30, capture_output=True)
            return True
        finally:
            try:
                os.unlink(wav)
            except OSError:
                pass

    def say(self, text: str):
        text = clean(text)
        if not text:
            print("DONE", flush=True)
            return
        self.cancel.clear()
        if _is_ack(text) and self._play_ack_cache(text):
            print("DONE", flush=True)
            return
        cfg = _jarvis_tts()
        provider = cfg["provider"]
        sys.stderr.write(f"say provider={provider}\n")
        ok = False
        try:
            if provider == "xai":
                ok = self.xai(text, cfg["xai_voice"], cfg["xai_language"])
            elif provider == "gemini":
                ok = self.gemini(text, cfg["gemini_model"], cfg["gemini_voice"])
            elif provider == "piper":
                ok = self.piper(text, cfg.get("piper_voice") or PIPER_MODEL)
            else:
                sys.stderr.write(f"provider {provider} não suportado no orb, tentando xai\n")
                ok = self.xai(text, cfg["xai_voice"], cfg["xai_language"])
        except Exception as e:
            sys.stderr.write(f"{provider} fail {e}\n")
        if not ok and not self.cancel.is_set() and provider not in ("gemini", "piper"):
            try:
                ok = self.gemini(text, cfg["gemini_model"], cfg["gemini_voice"])
            except Exception as e:
                sys.stderr.write(f"gemini fallback {e}\n")
        if not ok and not self.cancel.is_set():
            try:
                ok = self.piper(text, cfg.get("piper_voice") or PIPER_MODEL)
            except Exception as e:
                sys.stderr.write(f"piper fail {e}\n")
        if self.cancel.is_set():
            print("DONE", flush=True)
            return
        if not ok:
            print("ERR synth_failed", flush=True)
            return
        print("DONE", flush=True)

    def _stdin(self):
        for line in sys.stdin:
            line = line.rstrip("\n")
            if not line:
                continue
            if line == "QUIT":
                self.cancel.set()
                self._kill_play()
                self._cmds.put(None)
                return
            if line == "CANCEL":
                self.cancel.set()
                self._kill_play()
                while True:
                    try:
                        self._cmds.get_nowait()
                    except queue.Empty:
                        break
                continue
            if line == "WARM":
                # Fora da fila de comandos de proposito: o pre-aquecimento
                # nao pode esperar a frase anterior terminar de tocar.
                threading.Thread(target=self.prewarm, daemon=True).start()
                continue
            if line.startswith("SAY "):
                self._cmds.put(line[4:])

    def run(self):
        threading.Thread(target=self._stdin, daemon=True).start()
        threading.Thread(target=self.prewarm, daemon=True).start()
        threading.Thread(target=self._fill_ack_cache, daemon=True).start()
        while True:
            item = self._cmds.get()
            if item is None:
                return
            if self.cancel.is_set():
                self.cancel.clear()
            self.say(item)


if __name__ == "__main__":
    _load_env()
    cfg = _jarvis_tts()
    sys.stderr.write(
        f"tts worker provider={cfg['provider']} "
        f"xai_voice={cfg['xai_voice']} gemini={cfg['gemini_model']}\n"
    )
    Worker().run()
