#!/usr/bin/env python3
"""Quem está falando com o orbe: o dono do PC ou outra pessoa na sala.

Cada trecho de fala vira uma impressão vocal (embedding de 512 dimensões do
CAM++ treinado no VoxCeleb, rodando no sherpa-onnx, CPU). O cadastro guarda a
média normalizada das impressões do dono; a decisão é a similaridade de
cosseno contra ela, acima de um limiar medido.

Uso:
  orbe_speaker.py enroll [--seconds 25]   grava o dono falando sozinho
  orbe_speaker.py test [--seconds 5]      grava e mostra a similaridade
  orbe_speaker.py gravar --out F [--seconds 90]   grava conversa (calibração)

Sem cadastro (ou sem sherpa-onnx) o porteiro fica desligado e o daemon
aceita qualquer voz, como antes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

import orbe_config as vcfg

MODEL = str(vcfg.dado("locutor/campplus_voxceleb.onnx", "cache/speaker/campplus_voxceleb.onnx"))
PROFILE = vcfg.dado("locutor/dono.npz", "cache/speaker/dono.npz")
MIC = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"
SR = 16000
# Abaixo disso a impressão vocal é ruído: o CAM++ precisa de voz contínua.
MIN_VOICE_SEC = 0.8


class SpeakerGate:
    def __init__(self, profile: Path | None = PROFILE, model: str = MODEL):
        import sherpa_onnx

        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model, num_threads=1)
        self._ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        self.centro: np.ndarray | None = None
        self.limiar = 1.0
        if profile is not None and profile.exists():
            dados = np.load(profile)
            self.centro = dados["centro"]
            self.limiar = float(dados["limiar"])

    @property
    def ativo(self) -> bool:
        return self.centro is not None

    def embed(self, pcm: np.ndarray) -> np.ndarray:
        st = self._ext.create_stream()
        st.accept_waveform(SR, pcm.astype(np.float32) / 32768.0)
        st.input_finished()
        e = np.asarray(self._ext.compute(st), dtype=np.float32)
        return e / (np.linalg.norm(e) + 1e-9)

    def score(self, pcm: np.ndarray) -> float | None:
        """Similaridade com o dono; None = pouca voz para decidir."""
        if self.centro is None or len(pcm) < MIN_VOICE_SEC * SR:
            return None
        return float(self.embed(pcm) @ self.centro)

    def e_o_dono(self, pcm: np.ndarray) -> tuple[bool, float | None]:
        """Na dúvida (pouca voz, sem cadastro), deixa passar."""
        s = self.score(pcm)
        return (s is None or s >= self.limiar), s


def _gravar(segundos: float) -> np.ndarray:
    """Mesmo caminho do daemon: 48 kHz e média por janela de 1440 -> 480.

    Cadastrar pelo reamostrador do PipeWire daria ao perfil uma coloração
    que o áudio do daemon não tem.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from orbe_daemon import _resample_frame  # noqa: E402

    if sys.platform == "darwin":
        # CoreAudio, entrada padrão, a 48 kHz como o daemon abre o mic do Mac
        import sounddevice as sd
        a48 = sd.rec(int(segundos * 48000), samplerate=48000, channels=1, dtype="int16")
        sd.wait()
        a48 = a48.reshape(-1)
    else:
        raw = subprocess.run(
            ["timeout", str(segundos), "pw-record", "--target", MIC, "--rate", "48000",
             "--channels", "1", "--format", "s16", "--container", "raw", "-"],
            capture_output=True,
        ).stdout
        a48 = np.frombuffer(raw, dtype=np.int16)
    blocos = [a48[i:i + 1440] for i in range(0, len(a48) - 1439, 1440)]
    return np.concatenate([_resample_frame(b, 480) for b in blocos]) if blocos else a48[:0]


def _janelas_de_voz(pcm: np.ndarray, janela_s: float = 1.5) -> list[np.ndarray]:
    """Janelas com >=70% de voz segundo o Silero, passo de meia janela."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from orbe_daemon import SileroVad  # noqa: E402

    vad = SileroVad()
    quadros = [pcm[i:i + 480] for i in range(0, len(pcm) - 479, 480)]
    voz = np.array([vad.feed(q.tobytes()) >= 0.5 for q in quadros])
    w = int(janela_s / 0.03)
    return [np.concatenate(quadros[k:k + w])
            for k in range(0, len(quadros) - w, w // 2) if voz[k:k + w].mean() >= 0.7]


def _contagem(segundos: float, instrucao: str) -> np.ndarray:
    for n in (3, 2, 1):
        print(f"Começa em {n}...", flush=True)
        time.sleep(1)
    print(f">>> GRAVANDO {segundos:.0f} s: {instrucao}", flush=True)
    pcm = _gravar(segundos)
    print(">>> ACABOU, pode parar.", flush=True)
    return pcm


def gravar(segundos: float, out: str) -> None:
    pcm = _contagem(segundos, "conversem normalmente, os dois falando.")
    pcm.tofile(out)
    print(f"salvo: {out} ({len(pcm) / SR:.0f} s)")


def enroll(segundos: float, limiar: float) -> None:
    pcm = _contagem(segundos, "fale normalmente, SOZINHO, como fala com o orbe.")
    jan = _janelas_de_voz(pcm)
    if len(jan) < 6:
        sys.exit(f"Só {len(jan)} janelas com voz; grave de novo falando mais.")
    gate = SpeakerGate(profile=None)
    E = np.array([gate.embed(j) for j in jan])
    centro = E.mean(0)
    centro /= np.linalg.norm(centro)
    sims = E @ centro
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(PROFILE, centro=centro, limiar=limiar, janelas=E)
    print(json.dumps({"janelas": len(jan), "sim_mediana": round(float(np.median(sims)), 3),
                      "sim_min": round(float(sims.min()), 3), "limiar": limiar,
                      "perfil": str(PROFILE)}, ensure_ascii=False))


def test(segundos: float) -> None:
    gate = SpeakerGate()
    if not gate.ativo:
        sys.exit("Sem cadastro: rode 'enroll' antes.")
    print(f"GRAVANDO {segundos:.0f} s...", flush=True)
    jan = _janelas_de_voz(_gravar(segundos))
    for j in jan:
        ok, s = gate.e_o_dono(j)
        print(f"similaridade {s:.3f} -> {'dono' if ok else 'outra pessoa'} (limiar {gate.limiar:.3f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll")
    e.add_argument("--seconds", type=float, default=25)
    e.add_argument("--limiar", type=float, default=0.85)
    t = sub.add_parser("test")
    t.add_argument("--seconds", type=float, default=5)
    g = sub.add_parser("gravar")
    g.add_argument("--seconds", type=float, default=90)
    g.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "enroll":
        enroll(a.seconds, a.limiar)
    elif a.cmd == "gravar":
        gravar(a.seconds, a.out)
    else:
        test(a.seconds)
