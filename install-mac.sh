#!/bin/sh
# Instala o Orbe no macOS a partir desta pasta: Python com as dependências,
# serviço do usuário (LaunchAgent), o app "Orbe" em ~/Applications e, se o
# Hermes estiver instalado, as skills de segurar e dispensar a sessão.
#
#   ./install-mac.sh             instala e liga o serviço
#   ./install-mac.sh --remover   desliga o serviço e apaga o LaunchAgent e o app
set -eu

ORBE=$(cd "$(dirname "$0")" && pwd)
LABEL=io.hermes.orbe
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP="$HOME/Applications/Orbe.app"
LOG="$HOME/Library/Logs/orbe.log"
ALVO="gui/$(id -u)"

if [ "${1:-}" = "--remover" ]; then
    launchctl bootout "$ALVO/$LABEL" 2>/dev/null || true
    pkill -f "$ORBE/orbe-qt/orbe_mac.py" 2>/dev/null || true
    rm -f "$PLIST"
    rm -rf "$APP"
    [ -L "$HOME/.local/bin/claude-orbe" ] && rm -f "$HOME/.local/bin/claude-orbe"
    echo "Orbe removido (o config em ~/.config/hermes-voice fica)."
    exit 0
fi

# ── Python: ORBE_PY, ou um venv 3.11 aqui (o mesmo Python do venv do Hermes,
#    cujos pacotes o daemon também enxerga) ──
if [ -n "${ORBE_PY:-}" ]; then
    PY=$ORBE_PY
else
    PY="$ORBE/.venv/bin/python"
    if [ ! -x "$PY" ]; then
        command -v uv >/dev/null || { echo "instale o uv: brew install uv"; exit 1; }
        uv venv --python 3.11 "$ORBE/.venv"
    fi
    uv pip install --python "$PY" -q numpy scipy sounddevice webrtcvad-wheels requests \
        onnxruntime websockets pyyaml PySide6
fi
"$PY" -c "import PySide6, sounddevice, webrtcvad, numpy" \
    || { echo "faltam dependências em $PY"; exit 1; }

# Silero VAD (v4, o formato que o daemon usa): sem ele o daemon cai no
# webrtcvad, que confunde ruído com fala. Melhor esforço, ~1,8 MB.
SILERO="$HOME/.hermes/cache/vad/silero_vad.onnx"
if [ ! -s "$SILERO" ]; then
    mkdir -p "$(dirname "$SILERO")"
    curl -fsSL -o "$SILERO" https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx \
        || { rm -f "$SILERO"; echo "aviso: Silero não baixou; o daemon usa o webrtcvad"; }
fi

# shaders: os .qsb já vêm com Metal; recompila se houver qsb à mão
"$ORBE/orbe-qt/build.sh" >/dev/null 2>&1 || true
chmod +x "$ORBE"/*.py "$ORBE/claude-orbe" "$ORBE/orbe-qt/orbe_mac.py"

# ── serviço: o daemon sobe no login e volta se cair ──
mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<FIM
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$ORBE/hermes_voice_daemon.py</string>
    </array>
    <key>WorkingDirectory</key><string>$ORBE</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>ThrottleInterval</key><integer>5</integer>
    <key>ProcessType</key><string>Interactive</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>PYTHONUNBUFFERED</key><string>1</string>
    </dict>
    <key>StandardOutPath</key><string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
FIM

# ── app de configuração: um .app mínimo que abre o hermes_voice_app.py ──
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/Orbe" <<FIM
#!/bin/sh
exec "$PY" "$ORBE/hermes_voice_app.py" "\$@"
FIM
chmod +x "$APP/Contents/MacOS/Orbe"
cat > "$APP/Contents/Info.plist" <<FIM
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Orbe</string>
    <key>CFBundleDisplayName</key><string>Orbe</string>
    <key>CFBundleIdentifier</key><string>io.hermes.Orbe</string>
    <key>CFBundleExecutable</key><string>Orbe</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleIconFile</key><string>orbe</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>O Orbe ouve o microfone para conversar com o agente por voz.</string>
</dict>
</plist>
FIM
# ícone: o orbe.svg rasterizado pelo Qt e empacotado pelo iconutil
ICONSET=$(mktemp -d)/orbe.iconset
mkdir -p "$ICONSET"
QT_QPA_PLATFORM=offscreen "$PY" - "$ORBE/orbe.svg" "$ICONSET" <<'FIM' 2>/dev/null || true
import sys
from PySide6.QtGui import QGuiApplication, QImage, QPainter, Qt
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication(sys.argv[:1])
r = QSvgRenderer(sys.argv[1])
for lado in (16, 32, 128, 256, 512):
    for esc, suf in ((1, ""), (2, "@2x")):
        img = QImage(lado * esc, lado * esc, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        r.render(p)
        p.end()
        img.save(f"{sys.argv[2]}/icon_{lado}x{lado}{suf}.png")
FIM
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/orbe.icns" 2>/dev/null || true

# claude-orbe no PATH (o ~/.local/bin é onde o instalador do Claude Code põe o claude)
mkdir -p "$HOME/.local/bin"
ln -sf "$ORBE/claude-orbe" "$HOME/.local/bin/claude-orbe"

# ── skills do Hermes ──
if [ -d "$HOME/.hermes" ]; then
    for s in "$ORBE"/skills/*/; do
        nome=$(basename "$s")
        mkdir -p "$HOME/.hermes/skills/$nome"
        sed -e "s|@ORBE@|$ORBE|g" -e "s|@PY@|$PY|g" "$s/SKILL.md" > "$HOME/.hermes/skills/$nome/SKILL.md"
    done
fi

# (re)liga o serviço
launchctl bootout "$ALVO/$LABEL" 2>/dev/null || true
launchctl bootstrap "$ALVO" "$PLIST"

cat <<FIM
Orbe instalado a partir de $ORBE (Python: $PY)

  serviço:  $PLIST  (log em $LOG)
  app:      $APP
  claude:   $HOME/.local/bin/claude-orbe
FIM
[ -d "$HOME/.hermes" ] && echo "  skills:   $HOME/.hermes/skills/voice-orb-{hold,dismiss}"
cat <<FIM

Próximos passos:
  1. chave da transcrição em ~/.hermes/.env: GROQ_API_KEY=... (ou só a
     GEMINI_API_KEY, que também transcreve)
  2. abra o app "Orbe" e escolha o agente, a ativação e a voz
  3. aperte $( "$PY" -c "import sys; sys.path.insert(0, '$ORBE'); import hermes_voice_config as c; print(c.carregar()['ativacao']['atalho'])" )
     (ou rode ./orb_control.py toggle). Na primeira vez o macOS pede o microfone.
FIM
