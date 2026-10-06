#!/bin/sh
# Instala o Orbe a partir desta pasta: serviço do usuário, atalho do app e,
# se o Hermes Agent estiver instalado, as skills de segurar e dispensar a sessão.
# Não liga o cancelamento de eco (opcional, ver README).
#
# Também migra uma instalação de antes da troca de nome (hermes-voice, até
# 2026-10-06): config, serviços, hook do Claude Code e o link do claude-orbe.
set -eu

ORBE=$(cd "$(dirname "$0")" && pwd)
UNITS="$HOME/.config/systemd/user"
APPS="$HOME/.local/share/applications"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
PIPEWIRE="$CONFIG/pipewire/pipewire.conf.d"

# Python do daemon: ORBE_PY, ou o .venv desta pasta, ou o python3 do PATH
if [ -n "${ORBE_PY:-}" ]; then PY=$ORBE_PY
elif [ -x "$ORBE/.venv/bin/python" ]; then PY=$ORBE/.venv/bin/python
else PY=$(command -v python3)
fi

preencher() { sed -e "s|@ORBE@|$ORBE|g" -e "s|@PY@|$PY|g" "$1" > "$2"; }
servico_ligado() { systemctl --user is-enabled --quiet "$1" 2>/dev/null; }
servico_ativo() { systemctl --user is-active --quiet "$1" 2>/dev/null; }

# shaders: os .qsb já vêm compilados; recompila só se o qsb existir
if [ -x "${QSB:-/usr/lib/qt6/bin/qsb}" ]; then
    "$ORBE/orbe-qt/build.sh" >/dev/null
fi

# ── migração: config de ~/.config/hermes-voice para ~/.config/orbe, com um
#    link no lugar antigo para o que ainda estiver rodando da versão velha ──
if [ -d "$CONFIG/hermes-voice" ] && [ ! -L "$CONFIG/hermes-voice" ] && [ ! -e "$CONFIG/orbe" ]; then
    mv "$CONFIG/hermes-voice" "$CONFIG/orbe"
    ln -s orbe "$CONFIG/hermes-voice"
    echo "config movida para $CONFIG/orbe"
fi

# ── migração: os serviços antigos saem; os novos herdam o ligado/ativo ──
ligar_orbe=0; subir_orbe=0; ligar_aec=0
if [ -f "$UNITS/hermes-voice.service" ]; then
    servico_ligado hermes-voice && ligar_orbe=1
    servico_ativo hermes-voice && subir_orbe=1
    systemctl --user disable --now hermes-voice 2>/dev/null || true
    rm -f "$UNITS/hermes-voice.service"
fi
if [ -f "$UNITS/hermes-aec.service" ]; then
    servico_ligado hermes-aec && ligar_aec=1
    systemctl --user disable --now hermes-aec 2>/dev/null || true
    rm -f "$UNITS/hermes-aec.service"
fi

# ── migração: o módulo de eco do PipeWire com os nomes novos dos nós; quem
#    estava desligado (.disabled) continua desligado ──
for velho in "$PIPEWIRE/99-hermes-echo-cancel.conf" "$PIPEWIRE/99-hermes-echo-cancel.conf.disabled"; do
    [ -f "$velho" ] || continue
    novo=$(echo "$velho" | sed 's/99-hermes-echo-cancel/99-orbe-echo-cancel/')
    sed -e 's/hermes_aec_/orbe_aec_/g' -e 's/HermesMicAEC/OrbeMicAEC/g' -e 's/HermesSpkAEC/OrbeSpkAEC/g' \
        "$velho" > "$novo"
    rm -f "$velho"
    case "$novo" in
        *.disabled) ;;
        *) echo "cancelamento de eco renomeado: reinicie o PipeWire (systemctl --user restart pipewire)" ;;
    esac
done

mkdir -p "$UNITS" "$APPS"
preencher "$ORBE/orbe.service.unit" "$UNITS/orbe.service"
if [ "$ligar_aec" = 1 ]; then
    preencher "$ORBE/orbe-aec.service.unit" "$UNITS/orbe-aec.service"
fi
# um atalho que é link (de um repositório de dotfiles, por exemplo) é do
# usuário: escrever nele reescreveria o arquivo de lá
if [ -L "$APPS/orbe.desktop" ]; then
    atalho="$APPS/orbe.desktop (link seu, não mexi: Exec=$ORBE/orbe_app.py, StartupWMClass=io.orbe.Orbe)"
else
    preencher "$ORBE/orbe.desktop.in" "$APPS/orbe.desktop"
    atalho="$APPS/orbe.desktop"
fi
chmod +x "$ORBE"/*.py "$ORBE/claude-orbe" "$ORBE/orbe_aec_default.sh"

# ── migração: o link do claude-orbe e o hook do Claude Code apontam para cá ──
LINK="$HOME/.local/bin/claude-orbe"
if [ -L "$LINK" ] && [ "$(readlink "$LINK")" != "$ORBE/claude-orbe" ]; then
    ln -sfn "$ORBE/claude-orbe" "$LINK"
    echo "claude-orbe: $LINK -> $ORBE/claude-orbe"
fi
if grep -q 'hermes_voice_sessao.py' "$HOME/.claude/settings.json" 2>/dev/null; then
    python3 "$ORBE/orbe_sessao.py" --instalar >/dev/null && echo "hook do Claude Code atualizado"
fi

if [ -d "$HOME/.hermes" ]; then
    for s in "$ORBE"/skills/*/; do
        nome=$(basename "$s")
        mkdir -p "$HOME/.hermes/skills/$nome"
        preencher "$s/SKILL.md" "$HOME/.hermes/skills/$nome/SKILL.md"
    done
fi

systemctl --user daemon-reload
[ "$ligar_orbe" = 1 ] && systemctl --user enable orbe
[ "$subir_orbe" = 1 ] && systemctl --user start orbe
[ "$ligar_aec" = 1 ] && systemctl --user enable --now orbe-aec

cat <<FIM
Orbe instalado a partir de $ORBE (Python do daemon: $PY)

  serviço:  $UNITS/orbe.service
  atalho:   $atalho
FIM
[ -d "$HOME/.hermes" ] && echo "  skills:   $HOME/.hermes/skills/voice-orb-{hold,dismiss}"
[ "$subir_orbe" = 1 ] && exit 0
cat <<FIM

Próximos passos:
  1. abra o app "Orbe": escolha o agente, a ativação e a voz, e ponha as
     chaves (a do Groq, para a transcrição, é a obrigatória)
  2. systemctl --user enable --now orbe
FIM
