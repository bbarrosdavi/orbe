#!/usr/bin/env python3
"""microWakeWord ear. stdin = s16le 16 kHz mono. stdout = WAKE\\n.

O tflite [1,3,40] foi treinado/exportado no frontend TF micro_speech
com window_step=20 ms. pymicro-features (10 ms) não acorda — max 0.04.
"""
import os
import sys

import numpy as np
import tensorflow as tf
from tensorflow.lite.python.interpreter import Interpreter
from tensorflow.lite.experimental.microfrontend.python.ops import (
    audio_microfrontend_op as frontend_op,
)

MODEL = os.environ.get(
    "MWW_MODEL",
    os.path.expanduser("~/.hermes/cache/wakewords/ei_hermes_mww.tflite"),
)
CUTOFF = float(os.environ.get("MWW_CUTOFF", "0.45"))
STREAK_N = int(os.environ.get("MWW_STREAK", "2"))
LOG = "/tmp/hermes-voice-mww.log"
STEP = 320  # 20 ms @ 16 kHz
KEEP = 16000  # 1 s de PCM pro PCAN


def spectrogram(pcm: np.ndarray) -> np.ndarray:
    with tf.device("/cpu:0"):
        spec = frontend_op.audio_microfrontend(
            tf.convert_to_tensor(pcm),
            sample_rate=16000,
            window_size=30,
            window_step=20,
            num_channels=40,
            upper_band_limit=7500,
            lower_band_limit=125,
            enable_pcan=True,
            min_signal_remaining=0.05,
            out_scale=1,
            out_type=tf.uint16,
        ).numpy().astype(np.float32) * 0.0390625
    return spec


def main() -> None:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    it = Interpreter(model_path=MODEL)
    it.allocate_tensors()
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    in_scale, in_zp = inp["quantization"]
    out_scale, out_zp = out["quantization"]
    buf = np.zeros(0, dtype=np.int16)
    streak = 0
    peak = 0.0
    n = 0
    stdin = sys.stdin.buffer
    while True:
        data = stdin.read(STEP * 2)
        if not data:
            break
        buf = np.concatenate([buf, np.frombuffer(data, dtype=np.int16)])
        if buf.size > KEEP:
            buf = buf[-KEEP:]
        if buf.size < 480:
            continue
        spec = spectrogram(buf)
        if spec.shape[0] < 3:
            continue
        chunk = np.reshape(spec[-3:], (1, 3, 40))
        q = np.clip(np.round(chunk / in_scale + in_zp), -128, 127).astype(np.int8)
        it.set_tensor(inp["index"], q)
        it.invoke()
        raw = np.asarray(it.get_tensor(out["index"]), dtype=np.float32).reshape(-1)[0]
        score = float((raw - out_zp) * out_scale)
        peak = max(peak, score)
        n += 1
        if n % 50 == 0:
            try:
                with open(LOG, "a") as f:
                    f.write(f"peak={peak:.3f} cutoff={CUTOFF}\n")
            except OSError:
                pass
            peak = 0.0
        if score >= CUTOFF:
            streak += 1
            if streak >= STREAK_N:
                streak = 0
                buf = np.zeros(0, dtype=np.int16)
                sys.stdout.write("WAKE\n")
                sys.stdout.flush()
        else:
            streak = 0


if __name__ == "__main__":
    main()
