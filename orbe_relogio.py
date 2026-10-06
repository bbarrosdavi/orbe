#!/usr/bin/env python3
"""Ponte do orbe para o relógio (orbe-wear): um WebSocket na rede local.

O relógio desenha o orbe na GPU dele, com os mesmos shaders do orbe-qt. Daqui
saem só as linhas do protocolo do orbe (as do orbe.sock) e entram
o toque, os comandos do orb_control e a fala captada pelo relógio.

Conversa (texto = uma linha por mensagem; binário = PCM s16le mono 16 kHz):
  ponte   → desafio <sal em hex>                    ao conectar
  relógio → ola {"prova": "...", "nome": "...", "voz": true, "voz_pc": false}
                                                    a prova de que tem o token;
                                                    voz: toca a resposta no relógio;
                                                    voz_pc: toca também no PC
  ponte   → ola {"v": 1, "orbe": {...}, "tema": {...}, "microfone": true, "voz": false,
                 "voz_pc": false, "agentes": [{"id", "nome", "instancias"}], "sessoes": [...],
                 "abre_claude": false}
                                                    voz_pc: o PC pode tocar junto;
                                                    agentes: os que cada orbe pode ter;
                                                    instancias: o agente tem uma sessão por
                                                    instância do orbe (o Claude, e os que
                                                    rodam numa janela do terminal);
                                                    abre_claude: falar numa instância sem
                                                    sessão abre uma no PC
  ponte   → show listening | state thinking | level 0.42 0.60 | mic 0.3
            line <texto> | hold 1 | hide | clear    as linhas que o orbe recebe
  ponte   → config {"orbe": {...}, "tema": {...}, "papel": [...]}   aparência, tema ou papel de parede mudaram
  relógio → touch down | touch up                   dedo no orbe
  relógio → toggle | trigger | dismiss | hold | release | interromper | encerrar
                                                    interromper: corta a fala e deixa ouvindo;
                                                    encerrar: fecha a sessão e, com o Claude no
                                                    orbe, a sessão do Claude Code
  relógio → agente <id>                             o agente do orbe em tela (vazio = Claude)
  ponte   → sessoes [{"agente", "vaga", "pid", "rotulo", "titulo", "pasta", "estado", "canal", "ouve"}]
                                                    as sessões abertas no PC dos agentes com
                                                    instâncias, cada uma na sua vaga (as vagas
                                                    contam por agente; também no "ola")
  relógio → vaga <k> | vaga                         a vaga do orbe em tela (nada: o agente
                                                    dele não tem instâncias)
  relógio → orbe <skin> <#cor | ->                  a skin e a cor da instância do orbe em tela
                                                    ("-": a do tema), para o orbe do PC seguir
  relógio → historico                               as sessões passadas do agente do orbe em tela
  ponte   → historico {"agente", "sessoes": [{"id", "titulo", "pasta", "quando"}], "erro"}
                                                    só a quem pediu; quando em segundos
  relógio → retomar <id>                            retoma uma delas no orbe em tela (no Claude,
                                                    num terminal, na vaga dele)
  relógio → (binário) a fala, enquanto o dedo segura o orbe (ou na sessão
            aberta por "trigger", enquanto ela ouve)
  os dois → ajustes {"t": ..., "agentes": {...}, "voz": true, ...}
                                                    os ajustes do app do relógio; vale o
                                                    "t" (ms) mais novo, guardado em
                                                    relogio.ajustes no config do PC

Quando quem serve a ponte fala pelo relógio (orbe_pulso.py, ou o
daemon numa sessão aberta pelo relógio), a resposta vai em PCM s16le mono,
na taxa anunciada:
  ponte   → voz 24000 | (binário) a resposta | voz fim | voz corta (cala já)
  relógio → voz acabou                              tocou até o fim

O token não passa pela rede: a prova é PBKDF2-HMAC-SHA256(token, sal) com um
sal novo a cada conexão, cara de adivinhar para quem só escuta a rede. O que
vem depois (o raciocínio, a fala) vai em claro: fora de uma rede de confiança,
ponha a ponte atrás de um proxy com TLS (o relógio aceita wss://) ou numa VPN.

Só a biblioteca padrão e o websockets, que o daemon já tem (o Pillow, se
houver, lê o papel de parede para o fundo do relógio). Avulso:
  orbe_relogio.py              mostra o endereço e o token do pareamento
  orbe_relogio.py --ligar      liga a ponte no config (--desligar desfaz)
  orbe_relogio.py --novo-token troca o token
  orbe_relogio.py --demo       serve o ciclo da prévia, sem o daemon
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import math
import random
import re
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import orbe_config as vcfg
import orbe_sessao as sessao

LOG = logging.getLogger("relogio")

VERSAO = 1
# custo da prova do token: caro o bastante para não valer adivinhar os oito
# caracteres a partir de uma conexão escutada, barato para o relógio (~0,2 s)
ITERACOES = 60000
TAXA = 16000
QUADRO = 960                 # 30 ms a 16 kHz, s16: o quadro do daemon
# sem "l", "1", "0" e "o": o token é digitado no relógio
ALFABETO = "abcdefghjkmnpqrstuvwxyz23456789"
# o que o relógio pode pedir além do toque (os verbos do orb_control)
# interromper: o toque curto contado no relógio (sem a trava do duplo toque);
# encerrar: três toques, fecha a sessão e o agente do orbe (o Claude no PC)
COMANDOS = ("toggle", "trigger", "dismiss", "hold", "release", "interromper", "encerrar")
ESTADOS = ("idle", "listening", "thinking", "speaking", "tools")

DANK_CSS = Path.home() / ".config" / "gtk-4.0" / "dank-colors.css"
ACCENT_CSS = Path.home() / "Projetos/Docs_rice_sistema/main.css"
DMS_SESSAO = Path.home() / ".local/state/DankMaterialShell/session.json"
PAPEL_LADO = 12
# a janela do app no meio da tela: 700 px de altura numa de 864 (lógicos) e
# 500 de largura; o relógio estica esse retângulo no mostrador
PAPEL_ALTURA = 700 / 864
PAPEL_ASPECTO = 500 / 700
TEMA_PADRAO = {"accent_bg_color": "#b8cacb", "accent_fg_color": "#233334", "window_bg_color": "#121414",
               "window_fg_color": "#e3e2e2", "view_bg_color": "#121414", "popover_bg_color": "#1f2020"}


def tema() -> dict:
    """Cores do matugen, as mesmas que o app lê (orbe_app._tema)."""
    cores = {}
    try:
        for m in re.finditer(r"@define-color\s+(\w+)\s+(#[0-9a-fA-F]{6})", DANK_CSS.read_text()):
            cores[m.group(1)] = m.group(2)
    except OSError:
        pass
    t = {k: cores.get(k, v) for k, v in TEMA_PADRAO.items()}
    try:
        m = re.search(r"--colorAccentBg:\s*(#[0-9a-fA-F]{6})", ACCENT_CSS.read_text())
        t["anel"] = m.group(1) if m else "#0087fc"
    except OSError:
        t["anel"] = "#0087fc"
    return t


def _papel_caminho():
    """O papel de parede do DMS; sem o DMS (ou noutro sistema), None."""
    try:
        p = json.loads(DMS_SESSAO.read_text()).get("wallpaperPath") or ""
    except (OSError, ValueError, AttributeError):
        return None
    return Path(p) if p else None


_papel_guardado = (None, [])


def papel() -> list:
    """O papel de parede atrás do app, para o fundo do relógio: no PC o fundo
    do app é o papel borrado pelo niri, e o relógio não tem papel nenhum. Vai o
    retângulo do meio da tela, onde a janela do app fica, em PAPEL_LADO x
    PAPEL_LADO cores (linha a linha, de cima). Vazio sem o papel ou sem o Pillow."""
    global _papel_guardado
    caminho = _papel_caminho()
    if caminho is None:
        return []
    chave = (str(caminho), _mtime(caminho))
    if _papel_guardado[0] == chave:
        return _papel_guardado[1]
    cores = []
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            im.draft("RGB", (im.width // 8, im.height // 8))   # o JPEG já decodifica reduzido
            im = im.convert("RGB")
            alto = int(im.height * PAPEL_ALTURA)
            largo = min(im.width, int(alto * PAPEL_ASPECTO))
            x0, y0 = (im.width - largo) // 2, (im.height - alto) // 2
            im = im.crop((x0, y0, x0 + largo, y0 + alto)).resize((PAPEL_LADO, PAPEL_LADO), Image.BOX)
            cores = ["#%02x%02x%02x" % im.getpixel((x, y)) for y in range(PAPEL_LADO) for x in range(PAPEL_LADO)]
    except Exception as e:
        LOG.debug("papel de parede: %s", e)
    _papel_guardado = (chave, cores)
    return cores


# as cores das instâncias, como no relógio (Instancias): a do tema e mais quatro
CORES_INSTANCIA = ("", "#4DD0E1", "#81C784", "#FFB74D", "#B39DDB")

PAPEL_IMAGEM_LADO = 384     # px: o mostrador tem ~450, e o fundo vai coberto pelo tom do tema
_papel_imagem_guardado = (None, {})


def _papel_escolhido():
    """A imagem escolhida no app para o fundo do relógio (relogio.papel), ou None."""
    p = str(vcfg.carregar()["relogio"].get("papel") or "").strip()
    return Path(p).expanduser() if p else None


def papel_imagem() -> dict:
    """A imagem escolhida para o fundo do relógio, recortada no quadrado do meio
    e reduzida: {"papel_imagem": JPEG em base64, "papel_id": o que muda com ela}.
    Vazio sem imagem escolhida (o relógio segue o papel de parede do PC)."""
    global _papel_imagem_guardado
    caminho = _papel_escolhido()
    if caminho is None or not caminho.is_file():
        return {}
    chave = (str(caminho), _mtime(caminho))
    if _papel_imagem_guardado[0] == chave:
        return _papel_imagem_guardado[1]
    saida = {}
    try:
        import base64, io
        from PIL import Image, ImageOps
        with Image.open(caminho) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            lado = min(im.width, im.height)
            x0, y0 = (im.width - lado) // 2, (im.height - lado) // 2
            im = im.crop((x0, y0, x0 + lado, y0 + lado)).resize((PAPEL_IMAGEM_LADO, PAPEL_IMAGEM_LADO), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        dados = buf.getvalue()
        saida = {"papel_imagem": base64.b64encode(dados).decode(), "papel_id": hashlib.sha1(dados).hexdigest()[:12]}
    except Exception as e:
        LOG.warning("imagem do fundo do relógio (%s): %s", caminho, e)
    _papel_imagem_guardado = (chave, saida)
    return saida


def aparencia() -> dict:
    """O que o relógio precisa para desenhar o orbe igual ao do PC."""
    o = vcfg.carregar()["orbe"]
    tam = (o.get("tamanhos") or {}).get(o["skin"])
    return {"orbe": {"skin": o["skin"], "glitch": bool(o["glitch"]), "tamanho": o["tamanho"] if tam is None else tam},
            "tema": tema(), "papel": papel(), **papel_imagem()}


def novo_token() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(8))


def prova(token: bytes, sal: bytes) -> str:
    """O que o relógio responde ao desafio: só quem tem o token calcula."""
    return hashlib.pbkdf2_hmac("sha256", token, sal, ITERACOES).hex()


def token_da_config(trocar: bool = False) -> str:
    """Token do pareamento; gerado e gravado no config na primeira vez."""
    cfg = vcfg.carregar()
    tok = str(cfg["relogio"].get("token") or "")
    if trocar or not tok:
        tok = novo_token()
        cfg["relogio"]["token"] = tok
        vcfg.salvar(cfg)
    return tok


# o que o app do relógio guarda e o app do PC também edita (relogio.ajustes)
CAMPOS_AJUSTES = {"voz": bool, "voz_pc": bool, "microfone": bool, "vibrar": bool,
                  "texto": bool, "glitch": bool, "linhas": bool, "seguir_pc": bool, "tamanho": float,
                  "etapas": bool, "idioma_etapas": str}
# a língua das etapas faladas: traduzidas para o português, ou como o agente escreve
IDIOMAS_ETAPAS = ("pt", "original")
# os que o PC só conhece pelo relógio: null no config até ele mandar os dele
CAMPOS_DO_RELOGIO = ("toques", "segurar", "live", "fundo", "ordem", "sacudida", "sair",
                     "sacudida_fora", "sacudida_dentro", "sair_fora")
ACOES_TOQUE = ("abrir", "live", "encerrar", "historico", "nada")
# com o último toque segurado também dá para falar (segurar para falar)
ACOES_SEGURAR = ACOES_TOQUE + ("falar",)


def _do_relogio(k: str, v):
    """Um dos CAMPOS_DO_RELOGIO validado; None se não serve."""
    if k in ("toques", "segurar"):
        acoes = ACOES_TOQUE if k == "toques" else ACOES_SEGURAR
        ok = isinstance(v, list) and len(v) == 4 and all(a in acoes for a in v)
        return list(v) if ok else None
    if k == "ordem":
        if not isinstance(v, list):
            return None
        lista = []
        for skin in v:
            if skin in vcfg.SKINS and skin not in lista:
                lista.append(skin)
        return lista + [skin for skin in vcfg.SKINS if skin not in lista]
    if k in ("sacudida_fora", "sacudida_dentro", "sair_fora"):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return round(min(50.0, max(0.0, float(v))), 2)
        return None
    return v if isinstance(v, bool) else None


def ajustes_relogio() -> dict:
    """Os ajustes do relógio que o PC conhece, com o "t" da última mudança."""
    return vcfg.carregar()["relogio"]["ajustes"]


def gravar_ajustes(novos: dict) -> bool:
    """Guarda os ajustes vindos do relógio se forem mais novos que os do config."""
    cfg = vcfg.carregar()
    atual = cfg["relogio"]["ajustes"]
    try:
        t = int(novos.get("t") or 0)
    except (TypeError, ValueError):
        return False
    # o que o PC ainda não conhece vem do relógio, seja qual for o "t"
    aprendeu = False
    for k in CAMPOS_DO_RELOGIO:
        if atual.get(k) is None:
            v = _do_relogio(k, novos.get(k))
            if v is not None:
                atual[k] = v
                aprendeu = True
    if t <= int(atual.get("t") or 0):
        if aprendeu:
            vcfg.salvar(cfg)
        return False
    for k in CAMPOS_DO_RELOGIO:
        v = _do_relogio(k, novos.get(k))
        if v is not None:
            atual[k] = v
    for k, tipo in CAMPOS_AJUSTES.items():
        v = novos.get(k)
        if tipo is bool and isinstance(v, bool):
            atual[k] = v
        elif tipo is float and isinstance(v, (int, float)) and not isinstance(v, bool):
            atual[k] = round(min(1.3, max(0.6, float(v))), 3)
        elif tipo is str and v in IDIOMAS_ETAPAS:
            atual[k] = v
    tamanhos = novos.get("tamanhos")
    if isinstance(tamanhos, dict):
        for skin in atual["tamanhos"]:
            v = tamanhos.get(skin)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                atual["tamanhos"][skin] = round(min(1.3, max(0.6, float(v))), 3)
    agentes = novos.get("agentes")
    if isinstance(agentes, dict):
        for skin in atual["agentes"]:
            if isinstance(agentes.get(skin), str):
                atual["agentes"][skin] = agentes[skin][:24]
    atual["t"] = t
    vcfg.salvar(cfg)
    return True


def enderecos() -> list:
    """IPs desta máquina na rede local (o que se digita no relógio)."""
    ips = []
    for alvo in ("192.0.2.1", "2001:db8::1"):       # endereços de documentação: nada é enviado
        fam = socket.AF_INET6 if ":" in alvo else socket.AF_INET
        try:
            with socket.socket(fam, socket.SOCK_DGRAM) as s:
                s.connect((alvo, 9))
                ip = s.getsockname()[0]
        except OSError:
            continue
        if ip and not ip.startswith(("127.", "::1", "fe80")) and ip not in ips:
            ips.append(ip)
    return ips


def _assinatura() -> tuple:
    caminho = _papel_caminho()
    escolhido = _papel_escolhido()
    return (tuple(_mtime(p) for p in (vcfg.CONFIG_PATH, DANK_CSS, ACCENT_CSS)) + (str(caminho), caminho and _mtime(caminho))
            + (str(escolhido), escolhido and _mtime(escolhido)))


class PonteRelogio:
    """Servidor da ponte. Roda num laço asyncio próprio, numa thread do daemon.

    ao_controle(linha) recebe "touch down" e "touch up" (a fila do socket de
    controle do daemon); ao_comando(op) recebe os verbos do orb_control;
    ao_quadro(pcm) recebe a fala do relógio em quadros de 30 ms. Os três são
    chamados da thread da ponte e não podem bloquear.

    Com voz=True a resposta toca no relógio: falar(pcm) manda o áudio a quem
    pediu voz e ao_fala_fim() avisa que o relógio tocou até o fim. Com
    voz_pc=True o PC também tem voz (o daemon), e cada relógio diz se quer a
    resposta tocando lá junto (quer_voz_pc).
    """

    def __init__(self, porta: int, token: str, ao_controle, ao_comando, ao_quadro=None,
                 host: str = "0.0.0.0", ao_fala_fim=None, voz: bool = False, voz_pc: bool = False,
                 agentes=None, abre_claude: bool = False, ao_historico=None, ao_retomar=None):
        self.porta = int(porta)
        self.host = host
        self._token = token.strip().lower().encode()
        self._ao_controle = ao_controle
        self._ao_comando = ao_comando
        self._ao_quadro = ao_quadro
        self._ao_fala_fim = ao_fala_fim
        self._voz = voz
        self._voz_pc = voz_pc
        self._agentes = list(agentes or [])   # [{"id", "nome", "instancias"}]: o relógio dá um a cada orbe
        self._abre_claude = abre_claude       # falar numa instância sem sessão abre uma (o daemon)
        self._ao_historico = ao_historico     # agente → {"agente", "sessoes", "erro"}
        self._ao_retomar = ao_retomar         # (agente, vaga, id): a sessão escolhida no histórico
        self._agente = ""             # o do orbe em tela no relógio ("agente <id>")
        self._orbe = ("", "")         # a skin e a cor dele ("orbe <skin> <#cor>"; "" = a do tema)
        # as sessões dos agentes com instâncias: cada uma numa vaga do agente
        # dela, que não muda enquanto ela vive (com m orbes do agente no
        # relógio, as vagas se alternam entre eles: a instância k do j-ésimo é
        # a vaga k·m + j; o relógio faz a conta)
        self._vaga = -1               # a do orbe em tela ("vaga <k>"); -1 = o agente não tem instâncias
        self._vagas = {}              # pid → (agente, vaga)
        self._sessoes = []            # o último "sessoes" difundido
        self._trava_vagas = threading.Lock()
        self._com_voz = set()         # conexões que tocam a resposta
        self._pc_junto = set()        # das que tocam, as que querem o PC tocando também
        self._loop = None
        self._servidor = None
        self._fim = None
        self._clientes = {}           # conexão → fila de saída
        self._restos = {}             # conexão → sobra de PCM que não fechou um quadro
        self._falhas = {}             # ip → (quantas, até quando recusar)
        self._mic_t = 0.0
        self._pronto = threading.Event()
        # o que o orbe do PC está mostrando, para quem conecta no meio da sessão
        self._visivel = False
        self._estado = "listening"
        self._travado = False
        self._linhas = []
        self._assinatura = None

    # ── vida ──

    def iniciar(self, espera: float = 5.0) -> bool:
        threading.Thread(target=self._rodar, name="relogio", daemon=True).start()
        self._pronto.wait(espera)
        return self._servidor is not None

    def parar(self):
        loop, fim = self._loop, self._fim
        if loop is not None and fim is not None and loop.is_running():
            loop.call_soon_threadsafe(fim.set)

    def _rodar(self):
        try:
            asyncio.run(self._servir())
        except Exception as e:
            LOG.warning("ponte do relógio caiu: %s", e)
        finally:
            self._loop = None
            self._servidor = None
            self._pronto.set()

    async def _servir(self):
        import websockets             # só aqui: sem a ponte ligada, nada é importado
        self._fim = asyncio.Event()
        try:
            servidor = await websockets.serve(
                self._cliente, self.host, self.porta, max_size=1 << 20, ping_interval=20, ping_timeout=20)
        except OSError as e:
            LOG.warning("ponte do relógio: porta %d indisponível (%s)", self.porta, e)
            return
        self._loop = asyncio.get_running_loop()
        self._servidor = servidor
        LOG.info("Ponte do relógio em %s:%d", self.host, self.porta)
        self._pronto.set()
        vigia = asyncio.ensure_future(self._vigiar())
        try:
            await self._fim.wait()
        finally:
            vigia.cancel()
            servidor.close()
            await servidor.wait_closed()

    # ── do daemon para o relógio ──

    def agente(self) -> str:
        """O agente do orbe em tela no relógio; vazio até ele dizer."""
        return self._agente

    def vaga(self) -> int:
        """A vaga do orbe em tela no relógio; -1 se o agente dele não tem instâncias."""
        return self._vaga

    def orbe(self) -> tuple[str, str]:
        """A skin e a cor ("#rrggbb", ou "" para a do tema) do orbe em tela no relógio."""
        return self._orbe

    def sessao_da_vaga(self, vaga: int, agente: str = "claude") -> int:
        """O pid da sessão do [agente] na [vaga]; 0 com ela livre."""
        with self._trava_vagas:
            return next((p for p, av in self._vagas.items() if av == (agente, vaga)), 0)

    def atribuir(self, pid: int, vaga: int, agente: str = "claude") -> None:
        """A sessão que o orbe acabou de abrir fica na vaga de onde foi pedida."""
        with self._trava_vagas:
            if vaga >= 0 and all(av != (agente, vaga) for p, av in self._vagas.items() if p != pid):
                self._vagas[pid] = (agente, vaga)
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self._atualizar_sessoes)
            except RuntimeError:
                pass

    def _lista_sessoes(self) -> list:
        """Lê as sessões e acerta as vagas: a nova fica com a menor livre do agente dela."""
        vivas = []
        try:
            vivas = [{"agente": "claude", "pid": s["pid"], "rotulo": sessao.rotulo(s),
                      "titulo": sessao.titulo(s), "pasta": s["pasta"], "estado": s["estado"],
                      "canal": s["canal"], "ouve": s["ouve"]} for s in sessao.sessoes()]
        except Exception as e:
            LOG.debug("sessões do Claude: %s", e)
        com_janela = {a["id"] for a in self._agentes if a.get("instancias") and a.get("id") != "claude"}
        if com_janela:
            try:
                import orbe_terminal as terminal      # usa pty: não existe no Windows
                for d in reversed(terminal.sessoes()):       # da mais velha: ela fica com a vaga menor
                    if d.get("agente") in com_janela:
                        pasta = Path(str(d.get("pasta") or "")).name
                        vivas.append({"agente": d["agente"], "pid": int(d["pid"]),
                                      "rotulo": pasta or str(d["pid"]), "titulo": str(d.get("titulo") or ""),
                                      "pasta": pasta, "estado": str(d.get("estado") or "parada"),
                                      "canal": False, "ouve": True})
            except Exception as e:
                LOG.debug("janelas de terminal: %s", e)
        with self._trava_vagas:
            pids = {s["pid"]: s["agente"] for s in vivas}
            self._vagas = {p: av for p, av in self._vagas.items() if pids.get(p) == av[0]}
            usadas = set(self._vagas.values())
            for s in vivas:
                if s["pid"] not in self._vagas:
                    v = 0
                    while (s["agente"], v) in usadas:
                        v += 1
                    self._vagas[s["pid"]] = (s["agente"], v)
                    usadas.add((s["agente"], v))
            return sorted((dict(s, vaga=self._vagas[s["pid"]][1]) for s in vivas),
                          key=lambda s: (s["agente"] != "claude", s["agente"], s["vaga"]))

    def _atualizar_sessoes(self):
        lista = self._lista_sessoes()
        if lista != self._sessoes:
            self._sessoes = lista
            self._difundir("sessoes " + json.dumps(lista, ensure_ascii=False))

    # ── orbes em paralelo (o daemon chama) ──

    def focar(self, skin: str, agente: str, vaga: int, cor: str) -> None:
        """Um orbe que esperava a vez de falar toma o lugar: passa a ser o orbe
        em tela daqui e do relógio ("foco"), que rola até ele."""
        self._agente, self._vaga, self._orbe = agente, vaga, (skin, cor)
        self._no_laco(self._difundir, "foco " + json.dumps({"skin": skin, "agente": agente, "vaga": vaga}, ensure_ascii=False))

    def esperas(self, lista: list) -> None:
        """Os orbes cuja resposta espera a vez de falar, na ordem ([{skin, vaga, cor}])."""
        self._no_laco(self._difundir, "espera " + json.dumps(lista, ensure_ascii=False))

    def _no_laco(self, f, *args) -> None:
        """Chamado de uma thread do daemon: as filas dos clientes são do laço da ponte."""
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(f, *args)
        except RuntimeError:
            pass

    def satelites(self, esperando=frozenset(), principal=None) -> list:
        """Os outros orbes em volta do em tela, para o orbe do PC (Satelites.qml):
        cada sessão ativa de cada orbe da lista do relógio é um "ativo" (na cor
        da instância), cada orbe sem sessão um "fantasma", e os de [esperando]
        ({(skin, vaga)}) "espera". Os orbes de um agente com instâncias dividem
        as vagas como no relógio (a instância k do j-ésimo de m é a vaga k·m + j).
        O [principal] ((skin, vaga)) fica de fora; sem ele, o orbe em tela aqui."""
        aj = vcfg.carregar()["relogio"]["ajustes"]
        ordem = [s for s in (aj.get("ordem") or vcfg.SKINS) if s in vcfg.SKINS]
        ordem += [s for s in vcfg.SKINS if s not in ordem]
        por_skin = aj.get("agentes") or {}

        def agente(s):
            return por_skin.get(s) or "claude"
        com_inst = {a["id"] for a in self._agentes if a.get("instancias")} | {"claude"}
        grupos: dict[str, list] = {}
        for s in ordem:
            grupos.setdefault(agente(s), []).append(s)
        foco_skin, foco_vaga = principal if principal else (self._orbe[0], self._vaga)
        sessoes = list(self._sessoes or [])
        saida = []
        for s in ordem:
            a = agente(s)
            vagas = []
            if a in com_inst:
                m, j = len(grupos[a]), grupos[a].index(s)
                vagas = sorted(x["vaga"] for x in sessoes if x.get("agente") == a and x.get("vaga", -1) % m == j)
                for v in vagas:
                    if s == foco_skin and v == foco_vaga:
                        continue
                    k = v // m
                    saida.append({"id": f"{s}/{v}", "skin": s, "cor": CORES_INSTANCIA[k % len(CORES_INSTANCIA)],
                                  "tipo": "espera" if (s, v) in esperando else "ativo"})
            elif (s, -1) in esperando:
                saida.append({"id": s, "skin": s, "cor": "", "tipo": "espera"})
                continue
            if not vagas and s != foco_skin:
                saida.append({"id": s, "skin": s, "cor": "", "tipo": "fantasma"})
        return saida

    def conectado(self) -> bool:
        """Algum relógio na ponte agora."""
        return bool(self._clientes)

    def mic_ativo(self) -> bool:
        """A fala está vindo do relógio agora: o microfone do PC não entra junto."""
        return time.monotonic() - self._mic_t < 0.4

    def publicar(self, linha: str) -> None:
        """Uma linha do protocolo do orbe (chamada de qualquer thread do daemon)."""
        loop = self._loop
        if loop is None:
            return
        linha = linha.strip()
        op = linha.split(" ", 1)[0]
        if op in ("warm", "quit", "olhos", ""):
            return                    # só do orbe do PC
        if not self._clientes and op in ("level", "mic"):
            return                    # dezenas por segundo: sem relógio, nem acorda o laço
        try:
            loop.call_soon_threadsafe(self._difundir, linha)
        except RuntimeError:
            pass                      # laço fechando

    def _difundir(self, linha: str):
        op, _, arg = linha.partition(" ")
        arg = arg.strip()
        if op == "show":
            self._visivel, self._linhas = True, []
            if arg in ESTADOS:
                self._estado = arg
        elif op == "state":
            self._visivel = True
            if arg in ESTADOS:
                self._estado = arg
        elif op == "hide":
            self._visivel, self._linhas = False, []
        elif op == "clear":
            self._linhas = []
        elif op == "line":
            self._linhas = (self._linhas + [arg])[-6:]
        elif op == "hold":
            self._travado = arg not in ("", "0", "false", "off")
        volatil = op in ("level", "mic")
        for ws, fila in list(self._clientes.items()):
            if fila.full():
                if not volatil:       # relógio lento: o nível seguinte substitui o perdido
                    self._soltar(ws)
                continue
            fila.put_nowait(linha)

    def _soltar(self, ws):
        LOG.info("relógio %s não acompanha; desconectando", _par(ws))
        self._clientes.pop(ws, None)
        self._com_voz.discard(ws)
        self._pc_junto.discard(ws)
        asyncio.ensure_future(ws.close(1013, "lento"))

    def quer_voz(self) -> bool:
        """Há relógio conectado que toca a resposta."""
        return bool(self._com_voz)

    def quer_voz_pc(self) -> bool:
        """Algum relógio que toca a resposta pediu o PC tocando junto."""
        return bool(self._com_voz & self._pc_junto)

    def falar(self, pcm: bytes) -> None:
        """Um trecho da resposta em voz, na taxa do "voz <taxa>" publicado antes."""
        loop = self._loop
        if loop is None or not self._com_voz:
            return
        try:
            loop.call_soon_threadsafe(self._difundir_voz, bytes(pcm))
        except RuntimeError:
            pass                      # laço fechando

    def _difundir_voz(self, pcm: bytes):
        for ws in list(self._com_voz):
            fila = self._clientes.get(ws)
            if fila is None:
                continue
            if fila.full():
                self._soltar(ws)
            else:
                fila.put_nowait(pcm)

    def _reprise(self) -> list:
        linhas = ["hold 1"] if self._travado else []
        if self._visivel:
            linhas.append("show " + self._estado)
            linhas += ["line " + l for l in self._linhas]
        return linhas

    async def _vigiar(self):
        """Config do orbe, tema do sistema e sessões do Claude: mudou, o relógio fica sabendo."""
        while True:
            await asyncio.sleep(2.0)
            if not self._clientes:
                continue
            self._atualizar_sessoes()
            ass = _assinatura()
            if ass != self._assinatura:
                self._assinatura = ass
                self._difundir("config " + json.dumps(aparencia(), ensure_ascii=False))
                # quem já tem estes (ou mais novos) ignora: vale o "t" maior
                self._difundir("ajustes " + json.dumps(ajustes_relogio(), ensure_ascii=False))

    # ── do relógio para o daemon ──

    async def _cliente(self, ws, *_):
        ip = _par(ws)
        quantas, ate = self._falhas.get(ip, (0, 0.0))
        if quantas >= 5 and time.monotonic() < ate:
            await ws.close(4429, "muitas tentativas")
            return
        sal = secrets.token_bytes(16)
        try:
            await ws.send("desafio " + sal.hex())
            primeira = await asyncio.wait_for(ws.recv(), 8.0)
        except Exception:
            return
        quem = self._autenticar(primeira, sal)
        if quem is None:
            self._falhas[ip] = (quantas + 1, time.monotonic() + 60.0)
            LOG.warning("relógio %s recusado: token errado", ip)
            await asyncio.sleep(1.0)
            await ws.close(4401, "token")
            return
        self._falhas.pop(ip, None)
        nome = str(quem.get("nome") or "relógio")[:40]
        fila = asyncio.Queue(maxsize=1024)
        self._sessoes = self._lista_sessoes()
        ola = dict(aparencia(), v=VERSAO, microfone=self._ao_quadro is not None, voz=self._voz,
                   voz_pc=self._voz_pc, agentes=self._agentes, sessoes=self._sessoes,
                   abre_claude=self._abre_claude)
        fila.put_nowait("ola " + json.dumps(ola, ensure_ascii=False))
        for l in self._reprise():
            fila.put_nowait(l)
        self._assinatura = _assinatura()
        self._clientes[ws] = fila
        self._restos[ws] = bytearray()
        if self._voz and quem.get("voz"):
            self._com_voz.add(ws)
            if self._voz_pc and quem.get("voz_pc"):
                self._pc_junto.add(ws)
        LOG.info("Relógio conectado: %s (%s)", nome, ip)
        escritor = asyncio.ensure_future(self._escrever(ws, fila))
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    self._audio(ws, msg)
                else:
                    self._linha(ws, msg)
        except Exception as e:
            LOG.debug("relógio %s: %s", ip, e)
        finally:
            escritor.cancel()
            self._clientes.pop(ws, None)
            self._restos.pop(ws, None)
            self._com_voz.discard(ws)
            self._pc_junto.discard(ws)
            LOG.info("Relógio desconectado: %s (%s)", nome, ip)

    def _autenticar(self, primeira, sal: bytes):
        """O que o relógio disse de si se a prova confere com o token; None se não."""
        if not self._token or not isinstance(primeira, str) or not primeira.startswith("ola "):
            return None
        try:
            d = json.loads(primeira[4:])
            recebida = str(d.get("prova") or "").strip().lower().encode()
        except (ValueError, AttributeError):
            return None
        if not hmac.compare_digest(recebida, prova(self._token, sal).encode()):
            return None
        return d

    async def _escrever(self, ws, fila):
        try:
            while True:
                await ws.send(await fila.get())
        except Exception:
            pass

    def _linha(self, ws, msg: str):
        if msg.startswith("ajustes "):
            self._ajustes(ws, msg[8:4096])
            return
        if msg.startswith("retomar "):
            sid = msg[8:200].strip()
            if sid and self._ao_retomar is not None:
                threading.Thread(target=self._ao_retomar, args=(self._agente, self._vaga, sid),
                                 name="retomar", daemon=True).start()
            return
        linha = " ".join(msg.split())[:64]
        if linha in ("touch down", "touch up"):
            if linha == "touch up":
                self._restos[ws].clear()
                if self.mic_ativo():
                    # os últimos quadros da fala ainda estão na fila de áudio
                    # do daemon: o dedo solto chega depois deles
                    self._loop.call_later(0.06, self._ao_controle, linha)
                    return
            self._ao_controle(linha)
        elif linha in COMANDOS:
            self._ao_comando(linha)
        elif linha == "agente" or linha.startswith("agente "):
            ag = linha[7:].strip()
            if not ag or any(a.get("id") == ag for a in self._agentes):
                self._agente = ag
        elif linha == "vaga" or linha.startswith("vaga "):
            k = linha[5:].strip()
            self._vaga = int(k) if k.isdigit() and int(k) < 1000 else -1
        elif linha.startswith("orbe "):
            skin, _, cor = linha[5:].strip().partition(" ")
            cor = cor.strip()
            self._orbe = (skin[:32], cor if re.fullmatch(r"#[0-9a-fA-F]{6}", cor) else "")
        elif linha == "voz acabou" and self._ao_fala_fim is not None:
            self._ao_fala_fim()
        elif linha == "historico" and self._ao_historico is not None:
            self._historico(ws)

    def _historico(self, ws):
        """Lista fora do laço (um agente ACP pode subir para isso) e responde só a quem pediu."""
        agente, loop = self._agente, self._loop

        def _listar():
            try:
                h = self._ao_historico(agente)
            except Exception as e:
                LOG.warning("histórico: %s", e)
                h = {"agente": agente, "sessoes": [], "erro": "o histórico falhou"}
            msg = "historico " + json.dumps(h, ensure_ascii=False)

            def _mandar():
                fila = self._clientes.get(ws)
                if fila is not None:
                    fila.put_nowait(msg)
            if loop is not None:
                try:
                    loop.call_soon_threadsafe(_mandar)
                except RuntimeError:
                    pass
        threading.Thread(target=_listar, name="historico", daemon=True).start()

    def _ajustes(self, ws, texto: str):
        """Os ajustes do relógio: os dele mais novos ficam; os do PC mais novos vão para ele."""
        try:
            d = json.loads(texto)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        if not gravar_ajustes(d):
            pc = ajustes_relogio()
            if int(pc.get("t") or 0) > int(d.get("t") or 0) and ws in self._clientes:
                self._clientes[ws].put_nowait("ajustes " + json.dumps(pc, ensure_ascii=False))

    def _audio(self, ws, pcm: bytes):
        if self._ao_quadro is None:
            return
        resto = self._restos[ws]
        resto += pcm
        while len(resto) >= QUADRO:
            self._mic_t = time.monotonic()
            self._ao_quadro(bytes(resto[:QUADRO]))
            del resto[:QUADRO]


def _par(ws) -> str:
    try:
        return str(ws.remote_address[0])
    except Exception:
        return "?"


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


# ── avulso: pareamento e demonstração ──

# o ciclo e as linhas da prévia do app (orbe_app.py)
DEMO_CICLO = [("idle", 4.0), ("listening", 5.0), ("thinking", 5.0), ("speaking", 6.0)]
DEMO_LINHAS = [
    "Pedido: resumir as mensagens não lidas de hoje.",
    "Começo pelas conversas com menções diretas.",
    "São três threads; a mais longa trata do prazo da entrega.",
    "Junto um resumo de uma frase por thread e respondo.",
]


class _Fala:
    """Envelope de fala sintético, o mesmo da prévia do app."""

    def __init__(self):
        self.t = self.ini = self.fim = 0.0
        self.pico = 0.0
        self.tom = 0.5

    def passo(self, dt):
        self.t += dt
        if self.t >= self.fim:
            self.ini = self.t
            if random.random() < 0.2:
                self.pico, dur = 0.0, random.uniform(0.12, 0.35)
            else:
                self.pico, dur = random.uniform(0.45, 1.0), random.uniform(0.12, 0.24)
                self.tom = min(1.0, max(0.0, self.tom + random.uniform(-0.25, 0.25)))
            self.fim = self.t + dur
        u = (self.t - self.ini) / max(1e-3, self.fim - self.ini)
        return self.pico * math.sin(math.pi * min(1.0, u)) ** 0.8, self.tom


def _demo(ponte: PonteRelogio):
    """O ciclo da prévia do app, servido ao relógio sem daemon nem agente."""
    fala = _Fala()
    fase, t, n_linha, ant = 0, 0.0, 0, time.monotonic()
    ponte.publicar("show idle")
    while True:
        time.sleep(0.033)
        agora = time.monotonic()
        dt, ant = min(0.1, agora - ant), agora
        t += dt
        estado, dur = DEMO_CICLO[fase]
        if estado == "listening":
            ponte.publicar(f"mic {0.03 + 0.75 * fala.passo(dt)[0]:.3f}")
        elif estado == "speaking":
            env, tom = fala.passo(dt)
            ponte.publicar(f"level {0.9 * env:.3f} {tom:.2f}")
        elif estado == "thinking" and n_linha < len(DEMO_LINHAS) and t >= 0.3 + n_linha:
            ponte.publicar("line " + DEMO_LINHAS[n_linha])
            n_linha += 1
        if t >= dur:
            fase, t, n_linha = (fase + 1) % len(DEMO_CICLO), 0.0, 0
            if fase == 0:
                for l in ("level 0", "mic 0", "clear"):
                    ponte.publicar(l)
            ponte.publicar("state " + DEMO_CICLO[fase][0])


def main():
    ap = argparse.ArgumentParser(description="Ponte do orbe para o relógio (orbe-wear)")
    ap.add_argument("--ligar", action="store_true", help="liga a ponte no config")
    ap.add_argument("--desligar", action="store_true", help="desliga a ponte no config")
    ap.add_argument("--novo-token", action="store_true", help="troca o token do pareamento")
    ap.add_argument("--demo", action="store_true", help="serve o ciclo da prévia, sem o daemon")
    ap.add_argument("--porta", type=int, default=0, help="porta do --demo (padrão: a do config)")
    args = ap.parse_args()

    if args.ligar or args.desligar:
        cfg = vcfg.carregar()
        cfg["relogio"]["ligado"] = bool(args.ligar)
        vcfg.salvar(cfg)
    tok = token_da_config(trocar=args.novo_token)
    rc = vcfg.carregar()["relogio"]
    porta = args.porta or int(rc["porta"])

    print("Ponte do relógio:", "ligada" if rc["ligado"] else "desligada (--ligar)")
    for ip in enderecos() or ["<ip desta máquina>"]:
        print(f"  servidor: {ip}:{porta}")
    print(f"  token:    {tok}")
    if args.ligar or args.desligar or args.novo_token:
        print("Reinicie o daemon para valer: systemctl --user restart orbe")

    if args.demo:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
        fala = []

        def toque(linha):
            # segurando o orbe, a fala do relógio chega aqui em quadros de 30 ms
            if linha == "touch up" and fala:
                LOG.info("toque: %s (%.1f s de fala do relógio)", linha, len(fala) * 0.03)
                fala.clear()
            else:
                LOG.info("toque: %s", linha)

        ponte = PonteRelogio(porta, tok, ao_controle=toque,
                             ao_comando=lambda op: LOG.info("comando: %s", op),
                             ao_quadro=fala.append)
        if not ponte.iniciar():
            sys.exit(1)
        print("Demonstração no ar (Ctrl+C sai).")
        try:
            _demo(ponte)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
