#!/usr/bin/env python3
"""Ponte do orbe para o relógio (orbe-wear): um WebSocket na rede local.

O relógio desenha o orbe na GPU dele, com os mesmos shaders do orbe-qt. Daqui
saem só as linhas do protocolo do orbe (as do hermes-voice-orb.sock) e entram
o toque, os comandos do orb_control e a fala captada pelo relógio.

Conversa (texto = uma linha por mensagem; binário = PCM s16le mono 16 kHz):
  ponte   → desafio <sal em hex>                    ao conectar
  relógio → ola {"prova": "...", "nome": "...", "voz": true, "voz_pc": false}
                                                    a prova de que tem o token;
                                                    voz: toca a resposta no relógio;
                                                    voz_pc: toca também no PC
  ponte   → ola {"v": 1, "orbe": {...}, "tema": {...}, "microfone": true, "voz": false,
                 "voz_pc": false, "agentes": [{"id", "nome"}]}
                                                    voz_pc: o PC pode tocar junto;
                                                    agentes: os que cada orbe pode ter
  ponte   → show listening | state thinking | level 0.42 0.60 | mic 0.3
            line <texto> | hold 1 | hide | clear    as linhas que o orbe recebe
  ponte   → config {"orbe": {...}, "tema": {...}, "papel": [...]}   aparência, tema ou papel de parede mudaram
  relógio → touch down | touch up                   dedo no orbe
  relógio → toggle | trigger | dismiss | hold | release | interromper | encerrar
                                                    interromper: corta a fala e deixa ouvindo;
                                                    encerrar: fecha a sessão e, com o Claude no
                                                    orbe, a sessão do Claude Code
  relógio → agente <id>                             o agente do orbe em tela (vazio = Claude)
  relógio → (binário) a fala, enquanto o dedo segura o orbe (ou na sessão
            aberta por "trigger", enquanto ela ouve)
  os dois → ajustes {"t": ..., "agentes": {...}, "voz": true, ...}
                                                    os ajustes do app do relógio; vale o
                                                    "t" (ms) mais novo, guardado em
                                                    relogio.ajustes no config do PC

Quando quem serve a ponte fala pelo relógio (hermes_voice_pulso.py, ou o
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
  hermes_voice_relogio.py              mostra o endereço e o token do pareamento
  hermes_voice_relogio.py --ligar      liga a ponte no config (--desligar desfaz)
  hermes_voice_relogio.py --novo-token troca o token
  hermes_voice_relogio.py --demo       serve o ciclo da prévia, sem o daemon
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

import hermes_voice_config as vcfg

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
    """Cores do matugen, as mesmas que o app lê (hermes_voice_app._tema)."""
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


def aparencia() -> dict:
    """O que o relógio precisa para desenhar o orbe igual ao do PC."""
    o = vcfg.carregar()["orbe"]
    return {"orbe": {"skin": o["skin"], "glitch": bool(o["glitch"]), "tamanho": o["tamanho"]},
            "tema": tema(), "papel": papel()}


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
                  "texto": bool, "glitch": bool, "linhas": bool, "seguir_pc": bool, "tamanho": float}


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
    if t <= int(atual.get("t") or 0):
        return False
    for k, tipo in CAMPOS_AJUSTES.items():
        v = novos.get(k)
        if tipo is bool and isinstance(v, bool):
            atual[k] = v
        elif tipo is float and isinstance(v, (int, float)) and not isinstance(v, bool):
            atual[k] = round(min(1.3, max(0.6, float(v))), 3)
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
    return tuple(_mtime(p) for p in (vcfg.CONFIG_PATH, DANK_CSS, ACCENT_CSS)) + (str(caminho), caminho and _mtime(caminho))


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
                 agentes=None):
        self.porta = int(porta)
        self.host = host
        self._token = token.strip().lower().encode()
        self._ao_controle = ao_controle
        self._ao_comando = ao_comando
        self._ao_quadro = ao_quadro
        self._ao_fala_fim = ao_fala_fim
        self._voz = voz
        self._voz_pc = voz_pc
        self._agentes = list(agentes or [])   # [{"id", "nome"}]: o relógio dá um a cada orbe
        self._agente = ""             # o do orbe em tela no relógio ("agente <id>")
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
        """Config do orbe e tema do sistema: mudou, o relógio fica sabendo."""
        while True:
            await asyncio.sleep(2.0)
            if not self._clientes:
                continue
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
        ola = dict(aparencia(), v=VERSAO, microfone=self._ao_quadro is not None, voz=self._voz,
                   voz_pc=self._voz_pc, agentes=self._agentes)
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
        elif linha == "voz acabou" and self._ao_fala_fim is not None:
            self._ao_fala_fim()

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

# o ciclo e as linhas da prévia do app (hermes_voice_app.py)
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
        print("Reinicie o daemon para valer: systemctl --user restart hermes-voice")

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
