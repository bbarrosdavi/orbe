"""Configuração do orbe de voz: um JSON lido pelo daemon, pelo TTS e pelo app.

Os padrões são os valores que o daemon usava como constantes até 2026-10-03;
o arquivo só guarda o que difere deles. Só biblioteca padrão: o daemon, o
worker de TTS e o app rodam em Pythons diferentes.
"""
import copy
import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hermes-voice" / "config.json"
# Estado que o daemon publica para o app (modelos que o agente oferece etc.).
STATE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hermes-voice" / "agente.json"

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
        "oww_modelo": "/home/davi/.hermes/cache/wakewords/ei_hermes_pt.onnx",
        "mww_modelo": "/home/davi/.hermes/cache/wakewords/ei_hermes_mww.tflite",
        "sherpa_dir": "/home/davi/.hermes/cache/wakewords/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01",
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
        "atalho": "Mod+A",
    },
    "voz": {
        "stt_modelo": "whisper-large-v3-turbo",
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
        # disco translúcido com blur atrás do orbe (ext-background-effect no niri)
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
