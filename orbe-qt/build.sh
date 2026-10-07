#!/bin/sh
# Compila os shaders do orbe para .qsb (SPIR-V + GLSL 150/ES 100 + MSL 1.2
# para o Metal do macOS + HLSL 5.0 para o Direct3D do Windows), uma variante
# da figura por skin: desenhadas (figura.frag) e de imagem (imagem.frag, que
# lê o atlas em arte/<skin>.png).
set -e
cd "$(dirname "$0")/shaders"
# qsb do Qt do sistema ou o que vem com o PySide6 (pyside6-qsb)
if [ -z "${QSB:-}" ]; then
    for q in /usr/lib/qt6/bin/qsb ../../.venv/bin/pyside6-qsb "$(command -v pyside6-qsb)" "$(command -v qsb)"; do
        [ -n "$q" ] && [ -x "$q" ] && { QSB=$q; break; }
    done
fi
ALVOS="--glsl 100es,150 --msl 12 --hlsl 50"
for s in 0:ofanim 1:ofanim_alado; do
    "$QSB" $ALVOS -DSKIN="${s%%:*}" -o "figura_${s#*:}.frag.qsb" figura.frag
done
for s in 1:serafim_gravura 2:olho 3:humana; do
    "$QSB" $ALVOS -DIMG="${s%%:*}" -o "figura_${s#*:}.frag.qsb" imagem.frag
done
# o Seraphim em positivo (as cores da gravura): o mesmo atlas, outra saída
"$QSB" $ALVOS -DIMG=1 -DPOSITIVO -o figura_serafim_positivo.frag.qsb imagem.frag
for f in pos anel nuvem; do
    [ -f "$f.frag" ] && "$QSB" $ALVOS -o "$f.frag.qsb" "$f.frag"
done
rm -f figura.frag.qsb
ls -la *.qsb
