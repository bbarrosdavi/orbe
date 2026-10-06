"""Configuração do orbe de voz: um JSON lido pelo daemon, pelo TTS e pelo app.

Os padrões são os valores que o daemon usava como constantes até 2026-10-03;
o arquivo só guarda o que difere deles. Só biblioteca padrão: o daemon, o
worker de TTS e o app rodam em Pythons diferentes.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MAC = sys.platform == "darwin"

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "orbe" / "config.json"
# Estado que o daemon publica para o app (modelos que o agente oferece etc.).
STATE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "orbe" / "agente.json"
# Chaves de API do próprio orbe, fora do config.json (que vai e volta pela
# ponte do relógio): KEY=valor, só para o dono ler. Chave vazia aqui herda a
# do Hermes.
CHAVES_PATH = CONFIG_PATH.parent / "chaves.env"
HERMES_ENV = Path.home() / ".hermes" / ".env"
# as que o orbe usa: (variável, para quê)
CHAVES = (
    ("GROQ_API_KEY", "Groq: transcrição (Whisper)"),
    ("ELEVENLABS_API_KEY", "ElevenLabs: voz"),
    ("GEMINI_API_KEY", "Gemini: voz"),
    ("XAI_API_KEY", "xAI: voz (sem o login do Hermes)"),
)

# Modelos e dados (ativação, vozes do Piper, VAD, locutor): ORBE_DADOS, senão
# ~/.local/share/orbe/dados. Instalações antigas guardavam tudo em ~/.hermes;
# o que só existe lá continua valendo de lá, sem mover (o Hermes Agent pode
# estar usando os mesmos arquivos).
DADOS = Path(os.environ.get("ORBE_DADOS")
             or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "orbe" / "dados")
_DADOS_LEGADO = Path.home() / ".hermes"


def dado(rel: str, legado: str = "") -> Path:
    """DADOS/rel; se ele não existe e o legado (relativo a ~/.hermes) existe,
    o legado. Sem nenhum dos dois, DADOS/rel: é onde um arquivo novo nasce."""
    novo = DADOS / rel
    if legado and not novo.exists() and (_DADOS_LEGADO / legado).exists():
        return _DADOS_LEGADO / legado
    return novo


def piper_bin() -> str:
    """O piper do Python que está rodando (o venv do orbe), senão o do PATH."""
    junto = Path(sys.executable).with_name("piper")
    return str(junto) if junto.exists() else (shutil.which("piper") or str(junto))


def _runtime() -> Path:
    """Pasta dos sockets e arquivos de comando da sessão do usuário.

    No Linux é o XDG_RUNTIME_DIR (/run/user/UID). O macOS não tem um; a
    pasta temporária por usuário do Darwin (/var/folders/.../T) é o
    equivalente: só do usuário, a mesma para o launchd e o Terminal, limpa
    no boot e curta o bastante para o limite de 104 bytes do AF_UNIX.
    """
    if os.environ.get("XDG_RUNTIME_DIR"):
        return Path(os.environ["XDG_RUNTIME_DIR"])
    if not hasattr(os, "getuid"):
        # Windows (o orbe de pulso roda lá): o perfil local do usuário
        import tempfile
        return Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
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
SERVICO = "orbe"
LAUNCHD_LABEL = "io.orbe.daemon"
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
        # Onde cada agente roda: "terminal" abre uma janela do terminal no PC
        # com o agente (o Claude pelo claude-orbe, os outros pelo
        # orbe_terminal.py), e o pedido de voz aparece no chat dela;
        # "fundo" roda sem janela (o Claude com claude --bg, ouvindo pelo
        # hook; os outros por ACP). O "comando" é sempre ACP.
        "modos": {"claude": "terminal", "opencode": "terminal", "gemini": "terminal", "hermes": "fundo"},
        # O terminal das janelas, rodado como "<terminal> -e <agente>", e a
        # pasta em que elas abrem (vazio = a pasta do usuário). Vale para o
        # atalho e para o relógio.
        "terminal": "ghostty",
        "claude_pasta": "",
    },
    "ativacao": {
        # nenhum | openwakeword | sherpa | microwakeword
        "provedor": "nenhum",
        "oww_modelo": str(dado("ativacao/ei_hermes_pt.onnx", "cache/wakewords/ei_hermes_pt.onnx")),
        "mww_modelo": str(dado("ativacao/ei_hermes_mww.tflite", "cache/wakewords/ei_hermes_mww.tflite")),
        "sherpa_dir": str(dado("ativacao/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01",
                               "cache/wakewords/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01")),
        # Frase do sherpa-onnx: tokenizada na hora contra o vocabulário do modelo.
        "frase": "ei hermes",
        # Limiar de score de cada motor (mais alto = mais exigente). Valores de
        # partida: o do perfil jarvis no openWakeWord, o recomendado pelo Hermes
        # no sherpa (0.5 vira keywords_threshold 0.25) e o do orbe_mww.py.
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
        # ElevenLabs: o voice_id (da biblioteca da conta) e o modelo; a chave
        # é a ELEVENLABS_API_KEY (chaves.env do orbe, senão o .env do Hermes)
        "elevenlabs_voz": "",
        "elevenlabs_modelo": "eleven_flash_v2_5",
        # a voz de cada orbe, por provedor ({"gemini": {"olho": "Charon"}});
        # sem uma, o orbe fala com a voz de cima
        "orbes": {},
    },
    "conversa": {
        "silencio_fim_s": 0.90,
        # Pisos de RMS medidos no microfone do Linux (ruído de sala ~1700). O
        # do MacBook capta mais baixo: sala ~200, fala 1000 a 2400 (medido em
        # 2026-10-04); com 1500 a fala não sustentava 12 quadros e o orbe não
        # ouvia nada. O Silero segue decidindo o que é voz.
        "fala_rms": 450 if MAC else 1500,
        "fala_quadros": 12,
        "barge_in": True,
        "barge_quadros": 12,
        "barge_rms": 1500 if MAC else 2000,
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
        # ofanim | ofanim_alado (orbe-qt/comum/Figura.qml) | serafim_gravura | olho | humana
        # (imagem recortada, orbe-qt/arte) | anel (rotoscope)
        "skin": "ofanim",
        "glitch": True,
        # sombra radial atrás do orbe (pos.frag); a chave guarda o nome antigo
        "vidro": False,
        # opacidade da sombra no centro (0.1 a 1.0); 0.45 era o valor fixo
        "sombra": 0.45,
        # escala do orbe na tela (0.6 a 1.6); 1.0 = célula de 148 px. É a de
        # cada skin que ainda não tem a sua em "tamanhos" (null)
        "tamanho": 1.0,
        "tamanhos": {"anel": None, "serafim_gravura": None, "ofanim": None, "ofanim_alado": None, "olho": None, "humana": None},
        # onde aparece o texto do raciocínio: lado | abaixo
        "texto": "lado",
        # a nuvem no tom do fundo atrás do texto do raciocínio, e a opacidade
        # dela no meio (0.1 a 1.0)
        "texto_sombra": True,
        "texto_sombra_forca": 0.7,
        # os outros orbes (as sessões em paralelo) como mini orbes em volta deste;
        # desligado, nenhum aparece, nem o que espera a vez de falar
        "luas_ligadas": True,
        # só os com sessão ativa; desligado, os sem sessão orbitam também, em
        # repouso e sem o brilho dos ativos
        "luas_so_ativas": False,
        # como eles andam: vagalumes (soltos, vivos) | orbitas (elipses de
        # perfil, como elétrons)
        "luas": "vagalumes",
        # destravado, o orbe pode ser arrastado; a posição fica em
        # ~/.config/orbe/orbe-posicao.json (o padrão é o canto)
        "mover": False,
    },
    "relogio": {
        # ponte WebSocket para o app do relógio (orbe-wear), servida pelo
        # orbe_relogio.py; desligada, o daemon não abre porta nenhuma
        "ligado": False,
        # o orbe principal do PC: desligado, fica fixo no daqui; ligado, segue o
        # relógio e passa ao agente escolhido lá (a skin e a cor da instância),
        # com a troca animada, e fica nele mesmo com o relógio desconectado. Os
        # olhos ficam vermelhos na sessão do relógio com ou sem isto
        "seguir": False,
        "porta": 8777,
        # pareamento: gerado na primeira subida (orbe_relogio.py mostra)
        "token": "",
        # com o dedo no orbe do relógio, a fala vem do microfone dele
        "microfone": True,
        # o plano de fundo do relógio: "" segue o papel de parede do PC; um
        # caminho, a imagem escolhida no app
        "papel": "",
        # Os ajustes do app do relógio, nos dois sentidos: o relógio manda os
        # dele ao conectar e a cada mudança, o app do PC muda aqui, e vale o
        # lado de "t" mais novo (ms desde 1970 da última mudança).
        "ajustes": {
            "t": 0,
            # o agente de cada orbe da lista do relógio, pela skin; "" = Claude Code
            "agentes": {"ofanim": "", "ofanim_alado": "", "serafim_gravura": "", "olho": "", "humana": "", "anel": ""},
            "voz": True,          # a resposta toca no relógio
            "voz_pc": False,      # tocando lá, toca também no PC
            "microfone": True,    # segurando o orbe, a fala vem do relógio
            "vibrar": True,
            "texto": True,        # as linhas do raciocínio abaixo do orbe
            "glitch": True,
            "linhas": True,       # as linhas de TV (só no relógio; no PC elas vêm com o glitch)
            "tamanho": 1.0,
            # o orbe (aqui e no relógio) fala as etapas do agente enquanto ele
            # trabalha: a descrição de cada ferramenta, a linha que o terminal
            # mostra com o ponto. "pt" traduz pelo Groq; "original" fala como veio
            "etapas": False,
            "idioma_etapas": "pt",
            # a escala de cada orbe do relógio; null = a de "tamanho"
            "tamanhos": {"anel": None, "serafim_gravura": None, "ofanim": None, "ofanim_alado": None, "olho": None, "humana": None},
            "seguir_pc": True,    # o avatar e o glitch vêm do orbe do PC
            # Os de baixo o PC só conhece depois de o relógio mandar os dele:
            # null é "ainda não sei", e o relógio fica com o que tem.
            # a ação de 1, 2, 3 e 4 toques: abrir | live | encerrar | historico | nada
            "toques": None,
            # a de 1, 2, 3 e 4 toques com o último segurado: as mesmas e falar
            "segurar": None,
            "live": None,         # um toque no orbe fechado abre já no live
            "fundo": None,        # o fundo do menu também atrás dos orbes
            "ordem": None,        # a ordem dos orbes na lista do relógio, pelas skins
            "sacudida": None,     # uma sacudida do pulso abre o orbe
            "sair": None,         # com o orbe aberto, a sacudida para fora sai dele
            # as calibrações das sacudidas, em rad/s; 0 volta ao padrão do relógio
            "sacudida_fora": None,
            "sacudida_dentro": None,
            "sair_fora": None,
        },
    },
}


# as skins do orbe, na ordem do app do desktop (o Seraphim desenhado, o Shoggoth
# e a Entidade saíram); a lista do relógio tem a sua, em Skin.kt
SKINS = ("ofanim", "ofanim_alado", "serafim_gravura", "olho", "humana", "anel")


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


def skin_valida(skin) -> str:
    """Skin que saiu vira a que a substitui, ou o Ophanim."""
    skin = "serafim_gravura" if skin == "serafim" else skin
    return skin if skin in SKINS else "ofanim"


def carregar() -> dict:
    try:
        bruto = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bruto = {}
    cfg = _mesclar(DEFAULTS, bruto if isinstance(bruto, dict) else {})
    cfg["orbe"]["skin"] = skin_valida(cfg["orbe"]["skin"])
    return cfg


def agente_da_skin(cfg: dict | None = None) -> str:
    """O agente das sessões abertas no PC: o da skin em uso no mapa de agentes
    por skin, o mesmo que o relógio edita. Sem escolha ("" = o padrão), o
    relógio usa o Claude, e o PC também quando o relógio está ligado; sem ele,
    vale agente.tipo, como antes do mapa."""
    cfg = cfg or carregar()
    escolhido = str(cfg["relogio"]["ajustes"].get("agentes", {}).get(cfg["orbe"]["skin"]) or "")
    if escolhido:
        return escolhido
    return "claude" if cfg["relogio"]["ligado"] else cfg["agente"]["tipo"]


# os agentes que sabem rodar num terminal; o "comando" é um ACP qualquer
MODOS_TERMINAL = ("claude", "opencode", "gemini", "hermes")


def modo_do_agente(tipo: str, cfg: dict | None = None) -> str:
    """ "terminal" ou "fundo": onde o [tipo] roda (agente.modos)."""
    if tipo not in MODOS_TERMINAL:
        return "fundo"
    cfg = cfg or carregar()
    modo = (cfg["agente"].get("modos") or {}).get(tipo) or DEFAULTS["agente"]["modos"].get(tipo, "fundo")
    return "terminal" if modo == "terminal" else "fundo"


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


def ler_env(arquivo: Path) -> dict:
    """KEY=valor de um .env (aspas em volta saem; comentário e linha vazia, não contam)."""
    out = {}
    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for linha in linhas:
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def chaves_proprias() -> dict:
    return {k: v for k, v in ler_env(CHAVES_PATH).items() if v}


def gravar_chaves(chaves: dict) -> None:
    """Só as não vazias; o arquivo nasce 0600 (não passa por um instante legível)."""
    CHAVES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHAVES_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for k, v in chaves.items():
            v = str(v).strip()
            if v:
                f.write(f"{k}={v}\n")
    os.replace(tmp, CHAVES_PATH)


def aplicar_chaves(env=None) -> dict:
    """As chaves no ambiente: a própria do orbe vale; sem ela, a que já está no
    ambiente; sem nenhuma, a do .env do Hermes. Devolve de onde veio cada uma
    ("propria", "ambiente", "hermes" ou "")."""
    env = os.environ if env is None else env
    proprias, hermes = chaves_proprias(), ler_env(HERMES_ENV)
    origem = {}
    for k, _ in CHAVES:
        if proprias.get(k):
            env[k], origem[k] = proprias[k], "propria"
        elif env.get(k):
            origem[k] = "ambiente"
        elif hermes.get(k):
            env[k], origem[k] = hermes[k], "hermes"
        else:
            origem[k] = ""
    # o Gemini aceita a GOOGLE_API_KEY no lugar; ela só vem do Hermes
    if not env.get("GEMINI_API_KEY") and not env.get("GOOGLE_API_KEY") and hermes.get("GOOGLE_API_KEY"):
        env["GOOGLE_API_KEY"] = hermes["GOOGLE_API_KEY"]
    return origem
