#!/usr/bin/env python3
import wave
import random
import numpy as np
import scipy.signal
import torch
import torch.nn as nn
from pathlib import Path

import orbe_config as vcfg
from piper import PiperVoice, SynthesisConfig
from openwakeword.model import Model

print("=== Multi-Speaker Portuguese Wake Word Training ('Ei Hermes') ===")

cache_dir = vcfg.dado("ativacao", "cache/wakewords")
cache_dir.mkdir(parents=True, exist_ok=True)
tmp_dir = Path("/tmp/wakeword_pt_multi")
tmp_dir.mkdir(parents=True, exist_ok=True)

onnx_path = cache_dir / "ei_hermes_pt.onnx"

piper_models = [
    str(vcfg.dado("piper/pt_BR-faber-medium.onnx", "piper_models/pt_BR-faber-medium.onnx")),
    str(vcfg.dado("piper/pt_BR-cadu-medium.onnx", "piper_models/pt_BR-cadu-medium.onnx")),
    str(vcfg.dado("piper/pt_BR-edresson-low.onnx", "piper_models/pt_BR-edresson-low.onnx")),
    str(vcfg.dado("piper/pt_BR-dii-high.onnx", "piper_models/pt_BR-dii-high.onnx")),
    str(vcfg.dado("piper/en_US-amy-medium.onnx", "piper_models/en_US-amy-medium.onnx"))
]

voices = []
for p in piper_models:
    try:
        voices.append(PiperVoice.load(p))
        print(f"Loaded voice: {Path(p).name}")
    except Exception as e:
        print(f"Failed to load {p}: {e}")

def resample_to_16k(audio_int16, orig_sr):
    if orig_sr == 16000:
        return audio_int16
    target_length = int(len(audio_int16) * 16000 / orig_sr)
    resampled_float = scipy.signal.resample(audio_int16.astype(np.float32), target_length)
    return np.clip(resampled_float, -32768, 32767).astype(np.int16)

# 1. Generate Positive Synthetic Samples
print("1. Generating positive speech samples ('Ei Hermes', 'Hey Hermes')...")
pos_phrases = ["Ei Hermes", "Ei, Hermes!", "Ei Hermes.", "Ei Hermes?", "Êi Hêrmis", "Hey Hermes", "Ei Ermes"]
pos_wavs = []

count = 0
for v in voices:
    for _ in range(80):
        phrase = random.choice(pos_phrases)
        syn_cfg = SynthesisConfig(
            length_scale=random.uniform(0.7, 1.35),
            noise_scale=random.uniform(0.3, 0.9),
            volume=random.uniform(0.7, 1.2)
        )
        wav_file = tmp_dir / f"pos_{count}.wav"
        count += 1
        
        with wave.open(str(wav_file), "wb") as wf:
            v.synthesize_wav(phrase, wf, syn_config=syn_cfg)
        
        with wave.open(str(wav_file), "rb") as wf:
            orig_sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
            audio_orig = np.frombuffer(raw, dtype=np.int16)
        
        audio_16k = resample_to_16k(audio_orig, orig_sr)
        
        # Audio augmentation: background noise
        noise_level = random.uniform(10, 300)
        audio_16k = audio_16k + (np.random.randn(len(audio_16k)) * noise_level).astype(np.int16)
        
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_16k.tobytes())
            
        pos_wavs.append(wav_file)

print(f"Generated {len(pos_wavs)} multi-speaker positive samples.")

# 2. Generate Negative Speech & Noise Samples
print("2. Generating negative speech & noise samples...")
neg_phrases = [
    "olá", "bom dia", "boa tarde", "sim", "não", "computador", "teclado",
    "ajuda", "cancelar", "continuar", "abrir", "fechar", "parar", "música",
    "fala comigo", "tudo bem", "como vai", "ok", "entendi", "fechar janela",
    "fazer isso", "qual a boa", "áudio", "teste", "voz", "silêncio", "vamos ver",
    "mesmo", "aqui", "agora", "este", "escuta", "irmão", "homem", "herói"
]
neg_wavs = []

count = 0
for v in voices:
    for _ in range(80):
        phrase = random.choice(neg_phrases)
        syn_cfg = SynthesisConfig(
            length_scale=random.uniform(0.7, 1.3),
            noise_scale=random.uniform(0.3, 0.9),
            volume=1.0
        )
        wav_file = tmp_dir / f"neg_{count}.wav"
        count += 1
        
        with wave.open(str(wav_file), "wb") as wf:
            v.synthesize_wav(phrase, wf, syn_config=syn_cfg)
        
        with wave.open(str(wav_file), "rb") as wf:
            orig_sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
            audio_orig = np.frombuffer(raw, dtype=np.int16)
        
        audio_16k = resample_to_16k(audio_orig, orig_sr)
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_16k.tobytes())
            
        neg_wavs.append(wav_file)

# Add silence & noise
for i in range(100):
    dur = random.uniform(0.8, 2.5)
    sr = 16000
    noise_data = (np.random.randn(int(dur * sr)) * random.uniform(20, 1200)).astype(np.int16)
    wav_file = tmp_dir / f"neg_noise_{i}.wav"
    with wave.open(str(wav_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(noise_data.tobytes())
    neg_wavs.append(wav_file)

print(f"Generated {len(neg_wavs)} negative samples.")

# 3. Extract Feature Vectors via OpenWakeWord
print("3. Extracting feature vectors via OpenWakeWord...")
bundled_path = str(Path.home() / ".hermes/hermes-agent/tools/wakewords/hey_hermes.onnx")
m_oww = Model(wakeword_models=[bundled_path], inference_framework="onnx")

def extract_features(wav_file):
    with wave.open(str(wav_file), "rb") as wf:
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    feats = []
    m_oww.reset()
    for start in range(0, len(audio) - 1280, 1280):
        chunk = audio[start:start + 1280]
        m_oww.predict(chunk)
        feat = m_oww.preprocessor.get_features() # shape (1, 16, 96)
        if feat is not None and feat.shape == (1, 16, 96):
            feats.append(feat)
    return feats

X_pos_list, X_neg_list = [], []

for p in pos_wavs:
    feats = extract_features(p)
    if feats:
        X_pos_list.extend(feats[-3:]) # grab spoken frames

for n in neg_wavs:
    feats = extract_features(n)
    if feats:
        X_neg_list.extend(feats)

X_pos = np.array(X_pos_list, dtype=np.float32) # (N, 1, 16, 96)
X_neg = np.array(X_neg_list, dtype=np.float32)

y_pos = np.ones((len(X_pos), 1), dtype=np.float32)
y_neg = np.zeros((len(X_neg), 1), dtype=np.float32)

X = np.vstack([X_pos, X_neg]) # shape (Total, 1, 16, 96)
y = np.vstack([y_pos, y_neg]) # shape (Total, 1)

print(f"Dataset ready: {len(X_pos)} positive samples, {len(X_neg)} negative samples.")

# 4. PyTorch Classifier
class EiHermesNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(1536, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        return self.net(x)

model = EiHermesNet()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
criterion = nn.BCELoss()

X_tensor = torch.from_numpy(X)
y_tensor = torch.from_numpy(y)

print("4. Training PyTorch Classifier...")
model.train()
for epoch in range(200):
    optimizer.zero_grad()
    outputs = model(X_tensor)
    loss = criterion(outputs, y_tensor)
    loss.backward()
    optimizer.step()

model.eval()
with torch.no_grad():
    preds = (model(X_tensor) > 0.5).float()
    acc = (preds == y_tensor).float().mean().item()
    print(f"Final Model Accuracy: {acc * 100:.2f}%")

# 5. Export to ONNX
print("5. Exporting model to ONNX...")
dummy_input = torch.randn(1, 16, 96, dtype=torch.float32)
torch.onnx.export(
    model,
    dummy_input,
    str(onnx_path),
    input_names=["onnx::Flatten_0"],
    output_names=["output"],
    dynamic_axes={"onnx::Flatten_0": {0: "batch_size"}, "output": {0: "batch_size"}},
    opset_version=13
)

print(f"Successfully exported multi-speaker ONNX model to: {onnx_path}")
print("=== Training Complete ===")
