"""Configuração do orbe de voz: um JSON lido pelo daemon, pelo TTS e pelo app.

Os padrões são os valores que o daemon usava como constantes até 2026-10-03;
o arquivo só guarda o que difere deles. Só biblioteca padrão: o daemon, o
worker de TTS e o app rodam em Pythons diferentes.
"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

MAC = sys.platform == "darwin"

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hermes-voice" / "config.json"
# Estado que o daemon publica para o app (modelos que o agente oferece etc.).
STATE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hermes-voice" / "agente.json"


def _runtime() -> Path:
    """Pasta dos sockets e arquivos de comando da sessão do usuário.

    No Linux é o XDG_RUNTIME_DIR (/run/user/UID). O macOS não tem um; a
    pasta temporária por usuário do Darwin (/var/folders/.../T) é o
    equivalente: só do usuário, a mesma para o launchd e o Terminal, limpa
    no boot e curta o bastante para o limite de 104 bytes do AF_UNIX.
    """
    if os.environ.get("XDG_RUNTIME_DIR"):
        return Path(os.environ["XDG_RUNTIME_DIR"])
    linux = Path(f"/run/user/{os.getuid()}")
    if not MAC and linux.is_dir():
        return linux
    try:
        # _CS_DARWIN_USER_TEMP_DIR (o Python não exporta o nome)
        base = Path((os.confstr(65537) if MAC else "") or "/tmp")
    except (ValueError, OSError):
        base = Path("/tmp")
    pasta = base / f"orbe-{os.getuid()}"
    pasta.mkdir(mode=0o700, parents=True, exist_ok=True)
    return pasta


RUNTIME = _runtime()

# Serviço do daemon: unit do systemd no Linux, LaunchAgent no macOS.
SERVICO = "hermes-voice"
LAUNCHD_LABEL = "io.hermes.orbe"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_alvo() -> str:
    return f"gui/{os.getuid()}/{LAUNCHD_LABEL}"


def servico_estado() -> str:
    """'active', 'inactive' ou o que o gerenciador disser."""
    try:
        if MAC:
            r = subprocess.run(["launchctl", "print", _launchd_alvo()],
                               capture_output=True, text=True, timeout=2)
            if r.returncode != 0:
                return "inactive"
            return "active" if "state = running" in r.stdout else "inactive"
        return subprocess.run(["systemctl", "--user", "is-active", SERVICO + ".service"],
                              capture_output=True, text=True, timeout=2).stdout.strip() or "?"
    except Exception:
        return "?"


def servico_iniciar(reiniciar: bool = False) -> None:
    """Sobe (ou reinicia) o daemon sem esperar por ele."""
    if MAC:
        if not LAUNCHD_PLIST.exists():
            return
        r = subprocess.run(["launchctl", "print", _launchd_alvo()], capture_output=True, timeout=2)
        if r.returncode != 0:
            subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(LAUNCHD_PLIST)],
                           capture_output=True, timeout=5)
        argv = ["launchctl", "kickstart"] + (["-k"] if reiniciar else []) + [_launchd_alvo()]
    else:
        argv = ["systemctl", "--user", "restart" if reiniciar else "start", SERVICO + ".service"]
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


INSTRUCAO_VOZ = (
    "Você é um assistente de voz. A mensagem do usuário é a transcrição automática "
    "do que ele falou ao microfone, e a sua resposta é convertida em fala. Responda "
    "em português do Brasil, em texto corrido de duas a quatro frases, sem markdown, "
    "listas, tabelas, caminhos de arquivo ou URLs."
)

DEFAULTS = {
    "agente": {
        # hermes | opencode | gemini | comando
        "tipo": "hermes",
        "perfil": "jarvis",
        # Vazio = o modelo que o agente já usa.
        "modelo": "",
        # Linha de comando de um agente ACP qualquer (tipo "comando").
        "comando": "",
        # Prefixo do primeiro pedido de cada conversa, para agentes que não têm
        # um perfil de voz próprio. O Hermes já tem o SOUL do perfil.
        "instrucao_voz": INSTRUCAO_VOZ,
        # 0 = processo do agente sempre carregado. N = descarrega N minutos
        # depois que a sessão de voz fecha. Medido em 2026-10-03: o hermes acp
        # do jarvis ocupa 515 MB depois do primeiro turno; subir de novo custa
        # ~2 s de initialize mais a sessão, feito em paralelo à fala.
        "manter_carregado_min": 10,
    },
    "ativacao": {
        # nenhum | openwakeword | sherpa | microwakeword
        "provedor": "nenhum",
        "oww_modelo": str(Path.home() / ".hermes/cache/wakewords/ei_hermes_pt.onnx"),
        "mww_modelo": str(Path.home() / ".hermes/cache/wakewords/ei_hermes_mww.tflite"),
        "sherpa_dir": str(Path.home() / ".hermes/cache/wakewords/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"),
        # Frase do sherpa-onnx: tokenizada na hora contra o vocabulário do modelo.
        "frase": "ei hermes",
        # Limiar de score de cada motor (mais alto = mais exigente). Valores de
        # partida: o do perfil jarvis no openWakeWord, o recomendado pelo Hermes
        # no sherpa (0.5 vira keywords_threshold 0.25) e o do hermes_voice_mww.py.
        "limiar_oww": 0.78,
        "limiar_sherpa": 0.5,
        "limiar_mww": 0.45,
        # Quadros seguidos acima do limiar (openWakeWord e microWakeWord).
        "confirmacao": 2,
        # Mod = Super no niri, Command no macOS. No Mac, Cmd+A é "selecionar
        # tudo" e Ctrl+Space troca o teclado; Ctrl+Alt+O não briga com nada.
        "atalho": "Ctrl+Alt+O" if MAC else "Mod+A",
    },
    "voz": {
        # groq | gemini | "" (Groq se houver GROQ_API_KEY, senão Gemini)
        "stt_provedor": "",
        "stt_modelo": "whisper-large-v3-turbo",
        "stt_gemini_modelo": "gemini-flash-lite-latest",
        "stt_idioma": "pt",
        # Vazio = segue tts.provider do perfil jarvis.
        "tts_provedor": "",
        "gemini_voz": "",
        "xai_voz": "",
        "piper_voz": "",
    },
    "conversa": {
        "silencio_fim_s": 0.90,
        "fala_rms": 1500,
        "fala_quadros": 12,
        "barge_in": True,
        "barge_quadros": 12,
        "barge_rms": 2000,
        "gravacao_max_s": 12,
        "sessao_ociosa_s": 10.0,
    },
    "toque": {
        "segurar_s": 0.35,
        "gravacao_max_s": 90.0,
    },
    "diagnostico": {
        "rastro_niveis": True,
    },
    "orbe": {
        # ofanim | ofanim_alado | serafim (orbe-qt/comum/Figura.qml) | anel (rotoscope)
        "skin": "ofanim",
        "glitch": True,
        # sombra radial atrás do orbe (pos.frag); a chave guarda o nome antigo
        "vidro": False,
        # escala do orbe na tela (0.6 a 1.6); 1.0 = célula de 148 px
        "tamanho": 1.0,
        # onde aparece o texto do raciocínio: lado | abaixo
        "texto": "lado",
    },
}


def _mesclar(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mesclar(out[k], v)
        elif k in out:
            out[k] = v
    return out


def _diferenca(cfg: dict, base: dict) -> dict:
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            sub = _diferenca(v, base[k])
            if sub:
                out[k] = sub
        elif base.get(k) != v:
            out[k] = v
    return out


def carregar() -> dict:
    try:
        bruto = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bruto = {}
    return _mesclar(DEFAULTS, bruto if isinstance(bruto, dict) else {})


def salvar(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_diferenca(cfg, DEFAULTS), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


def ler_estado() -> dict:
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_estado(estado: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)
