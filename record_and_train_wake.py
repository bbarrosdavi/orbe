#!/usr/bin/env python3
"""Retrain ei_hermes_pt.onnx and refuse to write a dead model."""
from __future__ import annotations

import os
import random
import wave
from pathlib import Path

import numpy as np
import scipy.signal
import torch
import torch.nn as nn
from openwakeword.model import Model
from piper import PiperVoice, SynthesisConfig

CACHE = Path.home() / ".hermes/cache/wakewords"
ONNX_PATH = CACHE / "ei_hermes_pt.onnx"
TMP = Path("/tmp/wakeword_pt_retrain")
TMP.mkdir(parents=True, exist_ok=True)
BUNDLED = str(Path.home() / ".hermes/hermes-agent/tools/wakewords/hey_hermes.onnx")

PIPER_MODELS = [
    str(Path.home() / ".hermes/piper_models/pt_BR-faber-medium.onnx"),
    str(Path.home() / ".hermes/piper_models/pt_BR-cadu-medium.onnx"),
    str(Path.home() / ".hermes/piper_models/pt_BR-dii-high.onnx"),
    str(Path.home() / ".hermes/piper_models/pt_BR-edresson-low.onnx"),
]
POS_PHRASES = [
    "Ei Hermes", "Ei Hermes!", "Êi Hermes", "Ei, Hermes",
    "Hey Hermes", "Oi Hermes", "Ok Hermes",
]
NEG_PHRASES = [
    "olá", "bom dia", "boa tarde", "sim", "não", "computador", "teclado",
    "ajuda", "cancelar", "continuar", "abrir", "fechar", "parar", "música",
    "fala comigo", "tudo bem", "como vai", "ok", "entendi", "fechar janela",
    "Hermes", "ei", "e aí", "obrigado", "por favor", "vamos lá",
    "ei João", "oi Davi", "hey Google", "ok computador", "fala Hermes depois",
]


def resample_to_16k(audio_int16: np.ndarray, orig_sr: int) -> np.ndarray:
    if orig_sr == 16000:
        return audio_int16
    target_length = int(len(audio_int16) * 16000 / orig_sr)
    resampled = scipy.signal.resample(audio_int16.astype(np.float32), target_length)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def write_wav(path: Path, audio: np.ndarray, sr: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return audio, sr


def synth(voice: PiperVoice, text: str, path: Path) -> None:
    syn_cfg = SynthesisConfig(
        length_scale=random.uniform(0.85, 1.2),
        noise_scale=random.uniform(0.4, 0.75),
        volume=1.0,
    )
    tmp = path.with_suffix(".raw.wav")
    with wave.open(str(tmp), "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=syn_cfg)
    audio, sr = read_wav(tmp)
    audio = resample_to_16k(audio, sr)
    # light gain jitter + optional noise so it isn't a pure TTS fingerprint
    gain = random.uniform(0.6, 1.0)
    noise = (np.random.randn(len(audio)) * random.uniform(0, 180)).astype(np.float32)
    mixed = np.clip(audio.astype(np.float32) * gain + noise, -32768, 32767).astype(np.int16)
    write_wav(path, mixed)
    tmp.unlink(missing_ok=True)


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(1536, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Embedding magnitudes are ~std 17; keep this scale inside the graph
        # so inference matches training.
        return torch.sigmoid(self.net(x / 20.0))


def extract_windows(oww: Model, audio: np.ndarray, kind: str) -> list[np.ndarray]:
    oww.reset()
    pre = np.zeros(16000, dtype=np.int16)
    post = np.zeros(8000, dtype=np.int16)
    padded = np.concatenate([pre, audio, post])
    scored: list[tuple[float, np.ndarray]] = []
    n = 0
    orig_start = len(pre)
    orig_end = len(pre) + len(audio)
    for start in range(0, len(padded) - 1280, 1280):
        chunk = padded[start : start + 1280]
        oww.predict(chunk)
        n += 1
        if n < 18:
            continue
        # keep windows that overlap the real utterance, not the silence pads
        if start + 1280 < orig_start or start > orig_end:
            continue
        feat = oww.preprocessor.get_features()
        if feat is None or feat.shape != (1, 16, 96):
            continue
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        scored.append((rms, feat[0].astype(np.float32)))
    if not scored:
        return []
    scored.sort(key=lambda t: t[0], reverse=True)
    if kind == "pos":
        return [f for _, f in scored[:3]]
    return [f for _, f in scored[:6]]


def main() -> None:
    random.seed(7)
    np.random.seed(7)
    torch.manual_seed(7)

    voices = []
    for p in PIPER_MODELS:
        if os.path.exists(p):
            try:
                voices.append(PiperVoice.load(p))
                print("loaded", p)
            except Exception as e:
                print("skip voice", p, e)
    if not voices:
        raise SystemExit("no piper voices")

    print("generating wavs...")
    pos_wavs: list[Path] = []
    neg_wavs: list[Path] = []
    n_pos = 0
    for v in voices:
        for _ in range(12):
            phrase = random.choice(POS_PHRASES)
            path = TMP / f"pos_{n_pos}.wav"
            synth(v, phrase, path)
            pos_wavs.append(path)
            n_pos += 1
        for _ in range(12):
            phrase = random.choice(NEG_PHRASES)
            path = TMP / f"neg_{len(neg_wavs)}.wav"
            synth(v, phrase, path)
            neg_wavs.append(path)
    for i in range(24):
        dur = random.uniform(0.8, 2.0)
        noise = (np.random.randn(int(dur * 16000)) * random.uniform(40, 900)).astype(np.int16)
        path = TMP / f"neg_noise_{i}.wav"
        write_wav(path, noise)
        neg_wavs.append(path)
    print("pos wavs", len(pos_wavs), "neg wavs", len(neg_wavs))

    print("extracting embeddings...")
    oww = Model(wakeword_models=[BUNDLED], inference_framework="onnx")
    speech_neg = [p for p in neg_wavs if p.name.startswith("neg_") and "noise" not in p.name]
    holdout_pos = pos_wavs[-6:]
    holdout_neg = speech_neg[-8:]
    train_pos = pos_wavs[:-6]
    train_neg = [p for p in neg_wavs if p not in holdout_neg]

    X_pos, X_neg = [], []
    for p in train_pos:
        audio, sr = read_wav(p)
        audio = resample_to_16k(audio, sr)
        X_pos.extend(extract_windows(oww, audio, "pos"))
    for n in train_neg:
        audio, sr = read_wav(n)
        audio = resample_to_16k(audio, sr)
        X_neg.extend(extract_windows(oww, audio, "neg"))

    print("windows pos", len(X_pos), "neg", len(X_neg))
    if len(X_pos) < 20 or len(X_neg) < 20:
        raise SystemExit(f"too few windows pos={len(X_pos)} neg={len(X_neg)}")

    rng = np.random.default_rng(7)
    n = min(len(X_pos), len(X_neg))
    X_pos_arr = np.stack(X_pos)
    X_neg_arr = np.stack(X_neg)
    X_pos_arr = X_pos_arr[rng.choice(len(X_pos_arr), n, replace=False)]
    X_neg_arr = X_neg_arr[rng.choice(len(X_neg_arr), n, replace=False)]
    X = np.concatenate([X_pos_arr, X_neg_arr], axis=0)
    y = np.concatenate(
        [np.ones((n, 1), np.float32), np.zeros((n, 1), np.float32)], axis=0
    )
    perm = rng.permutation(len(X))
    X, y = X[perm], y[perm]
    print("train tensor", X.shape, "pos/neg", n)

    model = Net()
    opt = torch.optim.Adam(model.parameters(), lr=5e-4, weight_decay=1e-3)
    crit = nn.BCELoss()
    Xt = torch.from_numpy(X)
    yt = torch.from_numpy(y)
    dummy = torch.randn(1, 16, 96)
    tmp_onnx = Path("/tmp/ei_hermes_pt.candidate.onnx")
    best = None  # (gap, epoch, pos_min, neg_max)

    import shutil
    import onnxruntime as ort

    def eval_oww(path: Path) -> tuple[list[float], list[float]]:
        m = Model(wakeword_models=[str(path)], inference_framework="onnx")

        def mx(wav: Path) -> float:
            audio, sr = read_wav(wav)
            audio = resample_to_16k(audio, sr)
            audio = np.concatenate(
                [np.zeros(8000, np.int16), audio, np.zeros(8000, np.int16)]
            )
            m.reset()
            best_s = 0.0
            for start in range(0, len(audio) - 1280, 1280):
                scores = m.predict(audio[start : start + 1280])
                best_s = max(best_s, max(float(v) for v in scores.values()))
            return best_s

        return [mx(p) for p in holdout_pos], [mx(n) for n in holdout_neg]

    model.train()
    for epoch in range(1, 121):
        opt.zero_grad()
        out = model(Xt)
        loss = crit(out, yt)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if epoch % 20 == 0 or epoch == 1:
            with torch.no_grad():
                acc = ((out > 0.5).float() == yt).float().mean().item()
            model.eval()
            torch.onnx.export(
                model, dummy, str(tmp_onnx),
                input_names=["onnx::Flatten_0"], output_names=["output"],
                dynamo=False, opset_version=17,
            )
            pos_scores, neg_scores = eval_oww(tmp_onnx)
            pmin, pmax = min(pos_scores), max(pos_scores)
            nmin, nmax = min(neg_scores), max(neg_scores)
            gap = pmin - nmax
            print(
                f"epoch {epoch:3d} loss={loss.item():.4f} acc={acc*100:.1f}% "
                f"pos {pmin:.3f}-{pmax:.3f} neg {nmin:.3f}-{nmax:.3f} gap={gap:.3f}"
            )
            if best is None or gap > best[0]:
                best = (gap, epoch, pmin, nmax)
                shutil.copy2(tmp_onnx, "/tmp/ei_hermes_pt.best.onnx")
            model.train()

    if best is None:
        raise SystemExit("no checkpoint")
    print("best", best)
    pos_ok = best[2] >= 0.70
    neg_ok = best[3] <= 0.40
    if not (pos_ok and neg_ok):
        raise SystemExit(
            f"REFUSING to install weak model pos_min={best[2]:.3f} neg_max={best[3]:.3f}"
        )

    CACHE.mkdir(parents=True, exist_ok=True)
    shutil.copy2("/tmp/ei_hermes_pt.best.onnx", ONNX_PATH)
    print("installed", ONNX_PATH, "size", ONNX_PATH.stat().st_size)


if __name__ == "__main__":
    main()
