#!/usr/bin/env python3
"""Toca PCM s16le mono do stdin no alto-falante padrão: o pw-cat do macOS.

Uso: orbe_play.py TAXA

O worker de TTS escreve o áudio aos pedaços enquanto ele chega da rede, e
mata este processo para cortar a fala no meio (barge-in, dispensa). A escrita
no stream bloqueia, então o pipe dá a contrapressão que o pw-cat dava: o
nível que o TTS manda ao orbe anda junto com o som.
"""
import os
import signal
import sys

import sounddevice as sd

QUADRO = 960  # amostras por escrita (40 ms a 24 kHz)


def main():
    taxa = int(sys.argv[1]) if len(sys.argv) > 1 else 24000
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    entrada = sys.stdin.buffer
    resto = b""
    with sd.RawOutputStream(samplerate=taxa, channels=1, dtype="int16",
                            latency="low") as saida:
        while True:
            bloco = entrada.read1(QUADRO * 2) if hasattr(entrada, "read1") else entrada.read(QUADRO * 2)
            if not bloco:
                break
            bloco = resto + bloco
            corte = len(bloco) - (len(bloco) % 2)
            bloco, resto = bloco[:corte], bloco[corte:]
            if bloco:
                saida.write(bloco)
        # o buffer do CoreAudio ainda tem o fim da frase
        saida.write(b"\0" * (taxa // 10 * 2))


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
