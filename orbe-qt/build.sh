#!/bin/sh
# Compila os shaders do orbe para .qsb (SPIR-V + GLSL 150/ES 100), uma
# variante da figura por skin: desenhadas (figura.frag) e de imagem
# (imagem.frag, que lê o atlas em arte/<skin>.png).
set -e
cd "$(dirname "$0")/shaders"
QSB=${QSB:-/usr/lib/qt6/bin/qsb}
for s in 0:ofanim 1:ofanim_alado 3:shoggoth; do
    "$QSB" --glsl "100es,150" -DSKIN="${s%%:*}" -o "figura_${s#*:}.frag.qsb" figura.frag
done
for s in 1:serafim_gravura 2:entidade; do
    "$QSB" --glsl "100es,150" -DIMG="${s%%:*}" -o "figura_${s#*:}.frag.qsb" imagem.frag
done
for f in pos anel; do
    [ -f "$f.frag" ] && "$QSB" --glsl "100es,150" -o "$f.frag.qsb" "$f.frag"
done
rm -f figura.frag.qsb
ls -la *.qsb
