# Orbe de voz do Hermes

Assistente de voz headless: wake word local, comando por fala, resposta
sintetizada e overlay circular no Wayland.

| Arquivo | Papel |
|---|---|
| `hermes_voice_daemon.py` | captura, wake, VAD, STT, orquestracao |
| `hermes_voice_tts.py` | worker de sintese e reproducao |
| `orbe-qt/orbe.qml` | overlay em Quickshell (layer-shell), desenho em shaders na GPU |
| `orbe-qt/app/` + `hermes_voice_app.py` | app de configuracao (PySide6 + QML) |
| `orb_control.py` | controle do overlay por socket e cmdfile |
| `pipewire-hermes-aec.conf` | modulo de cancelamento de eco (monitor.mode) |
| `*.service.unit` | copias das units systemd de usuario |

Copias, nao fontes: as units vivem em `~/.config/systemd/user/` e a config do
PipeWire em `~/.config/pipewire/pipewire.conf.d/`. Aqui elas sao versionadas
para o estado ser reconstituivel.
