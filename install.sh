#!/bin/sh
# Instala o Orbe a partir desta pasta: serviço do usuário, atalho do app e,
# se o Hermes estiver instalado, as skills de segurar e dispensar a sessão.
# Não mexe no áudio: o cancelamento de eco é opcional (ver README).
set -eu

ORBE=$(cd "$(dirname "$0")" && pwd)
UNITS="$HOME/.config/systemd/user"
APPS="$HOME/.local/share/applications"

# Python do daemon: ORBE_PY, ou o venv do Hermes Agent, ou o python3 do PATH
if [ -n "${ORBE_PY:-}" ]; then PY=$ORBE_PY
elif [ -x /opt/hermes-agent/venv/bin/python ]; then PY=/opt/hermes-agent/venv/bin/python
elif [ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ]; then PY=$HOME/.hermes/hermes-agent/venv/bin/python
else PY=$(command -v python3)
fi

preencher() { sed -e "s|@ORBE@|$ORBE|g" -e "s|@PY@|$PY|g" "$1" > "$2"; }

# shaders: os .qsb já vêm compilados; recompila só se o qsb existir
if [ -x "${QSB:-/usr/lib/qt6/bin/qsb}" ]; then
    "$ORBE/orbe-qt/build.sh" >/dev/null
fi

mkdir -p "$UNITS" "$APPS"
preencher "$ORBE/hermes-voice.service.unit" "$UNITS/hermes-voice.service"
preencher "$ORBE/orbe.desktop.in" "$APPS/orbe.desktop"
chmod +x "$ORBE"/*.py "$ORBE/claude-orbe" "$ORBE/hermes_aec_default.sh"

if [ -d "$HOME/.hermes" ]; then
    for s in "$ORBE"/skills/*/; do
        nome=$(basename "$s")
        mkdir -p "$HOME/.hermes/skills/$nome"
        preencher "$s/SKILL.md" "$HOME/.hermes/skills/$nome/SKILL.md"
    done
fi

systemctl --user daemon-reload

cat <<FIM
Orbe instalado a partir de $ORBE (Python do daemon: $PY)

  serviço:  $UNITS/hermes-voice.service
  atalho:   $APPS/orbe.desktop
FIM
[ -d "$HOME/.hermes" ] && echo "  skills:   $HOME/.hermes/skills/voice-orb-{hold,dismiss}"
cat <<FIM

Próximos passos:
  1. chave do Groq (transcrição) em ~/.hermes/.env:  GROQ_API_KEY=...
  2. abra o app "Orbe" e escolha o agente, a ativação e a voz
  3. systemctl --user enable --now hermes-voice
FIM
