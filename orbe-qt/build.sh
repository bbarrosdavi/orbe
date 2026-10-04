#!/bin/sh
# Compila os shaders do orbe para .qsb (SPIR-V + GLSL 150/ES 100 + MSL 1.2
# para o Metal do macOS), uma variante da figura por skin.
set -e
cd "$(dirname "$0")/shaders"
# qsb do Qt do sistema ou o que vem com o PySide6 (pyside6-qsb)
if [ -z "${QSB:-}" ]; then
    for q in /usr/lib/qt6/bin/qsb ../../.venv/bin/pyside6-qsb "$(command -v pyside6-qsb)" "$(command -v qsb)"; do
        [ -n "$q" ] && [ -x "$q" ] && { QSB=$q; break; }
    done
fi
for s in 0:ofanim 1:ofanim_alado 2:serafim; do
    "$QSB" --glsl "100es,150" --msl 12 -DSKIN="${s%%:*}" -o "figura_${s#*:}.frag.qsb" figura.frag
done
for f in pos anel; do
    [ -f "$f.frag" ] && "$QSB" --glsl "100es,150" --msl 12 -o "$f.frag.qsb" "$f.frag"
done
rm -f figura.frag.qsb
ls -la *.qsb
