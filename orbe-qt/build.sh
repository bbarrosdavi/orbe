#!/bin/sh
# Compila os shaders do orbe para .qsb (SPIR-V + GLSL 150/ES 100), uma
# variante da figura por skin.
set -e
cd "$(dirname "$0")/shaders"
QSB=${QSB:-/usr/lib/qt6/bin/qsb}
for s in 0:ofanim 1:ofanim_alado 2:serafim; do
    "$QSB" --glsl "100es,150" -DSKIN="${s%%:*}" -o "figura_${s#*:}.frag.qsb" figura.frag
done
for f in pos anel; do
    [ -f "$f.frag" ] && "$QSB" --glsl "100es,150" -o "$f.frag.qsb" "$f.frag"
done
rm -f figura.frag.qsb
ls -la *.qsb
