"""Avatares do orbe em Cairo puro: Ophanim, Ophanim com asas e Seraphim.

Ophanim: "rodas dentro de rodas", aros cheios de olhos (Ezequiel 1:15-21;
10:9-13, onde as rodas são chamadas galgal, "turbilhão").
Ophanim com asas: as rodas com as asas dos seres viventes (Ez 1:6-11, 1:23-25):
em pé, baixam as asas; andando, abrem-nas e o ruído é o de muitas águas; as
asas também são cheias de olhos (Ez 10:12).
Seraphim: seis asas, duas cobrem o rosto, duas os pés, com duas voa (Isaías
6:2); serafim é "o que arde"; a casa se enche de fumaça (6:4); a brasa tirada
do altar (6:6); os umbrais tremem à voz (6:4). Os olhos nas asas vêm dos seres
de seis asas de Apocalipse 4:8.

Reações por estado (pesos `mix`, os mesmos do anel de energia):
- ouvindo: as rodas quase param, todos os olhos se voltam para quem fala, a
  pupila dilata com a voz; o serafim abre as asas do rosto e olha.
- pensando: turbilhão, rodas girando rápido, olhos espalhados vasculhando,
  fogo subindo e descendo entre as rodas (Ez 1:13); asas batendo; fumaça e o
  pulso triplo do "santo, santo, santo" no serafim.
- ferramentas: as rodas travam nos eixos e giram em quartos de volta, indo às
  quatro direções sem virar (Ez 1:17), com relâmpagos (Ez 1:14); a brasa do
  altar circula o serafim.
- falando: ondas saem a cada sílaba (muitas águas), os raios crescem com a
  voz, os aros vibram; o serafim treme e as chamas sobem com a voz.
- despertar: as rodas desdobram de um ponto e os olhos abrem em cascata.

Cada avatar desenha a figura em branco numa máscara; desenhar() pinta a
máscara na cor dada, com glitch opcional (aberração cromática, faixas
arrancadas e linhas de varredura recortadas da própria figura, nunca do
fundo) e contorno escuro opcional para ler sobre qualquer fundo.
"""
import math
import random

import cairo

# Raio de referência do topo do app: os deslocamentos do glitch, em px,
# foram afinados nele e escalam com o raio em outros tamanhos.
R_REF = 82.0
# Tons de profundidade por anel: traços agrupados por tom em vez de um traço
# por segmento. Mesmo desenho, uma fração do custo.
TONS = 12
TAU = 2 * math.pi


def ruido(t: float, semente: float) -> float:
    """Ruído suave barato: soma de senos com fases irracionais, em [-1, 1]."""
    return (math.sin(t * 1.31 + semente) * 0.5 + math.sin(t * 2.17 + semente * 1.7) * 0.3
            + math.sin(t * 0.53 + semente * 2.9) * 0.2)


def _lim(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def _suave(p):
    p = _lim(p)
    return p * p * (3 - 2 * p)


def olho(cr, x, y, ang, tam, abertura, alvo, alfa, pupila=1.0, lw=1.0):
    """Olho amendoado com íris e pupila vazada; ``alvo`` em coordenadas do olho."""
    cr.save()
    cr.translate(x, y)
    cr.rotate(ang)
    w, h = tam, tam * 0.48 * abertura
    cr.move_to(-w, 0)
    cr.curve_to(-w * 0.45, -h * 1.25, w * 0.45, -h * 1.25, w, 0)
    cr.curve_to(w * 0.45, h * 1.25, -w * 0.45, h * 1.25, -w, 0)
    cr.close_path()
    cr.set_source_rgba(1, 1, 1, _lim(alfa * 0.95))
    cr.set_line_width(max(0.8, tam * 0.13) * lw)
    cr.stroke_preserve()
    cr.set_source_rgba(1, 1, 1, _lim(alfa * 0.10))
    cr.fill_preserve()
    if abertura > 0.25:
        cr.clip()
        ix, iy = alvo
        cr.arc(ix * w * 0.35, iy * h * 0.35, tam * 0.42, 0, TAU)
        cr.set_source_rgba(1, 1, 1, _lim(alfa * 0.85))
        cr.fill()
        cr.arc(ix * w * 0.40, iy * h * 0.40, tam * 0.17 * pupila, 0, TAU)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.fill()
    cr.restore()


class Avatar:
    nome = ""
    alcance = (1.55, 1.55)     # extensão da figura em múltiplos de R (x, y)
    alcance_radial = 1.55      # ponto mais longe do centro (medido), para caber num disco

    def __init__(self):
        self.t = 0.0
        self.fase = 0.0
        self.glitch = True
        self.contorno = False
        self.peso = 1.0           # traço mais grosso e opaco (o orbe usa > 1)
        self.mix = {"idle": 1.0}
        self.voz = 0.0
        self.mic = 0.0
        self.desperto = 1.0
        self._voz_ant = 0.0
        self._mascara = None
        self._glitch_ate = 0.0
        self._prox_glitch = 1.2
        self._piscar = {}

    # ── estado ──

    def p(self, estado: str) -> float:
        return self.mix.get(estado, 0.0)

    def mistura(self, **valores) -> float:
        """Média dos valores por estado, pesada pelo mix."""
        tot = acc = 0.0
        for st, w in self.mix.items():
            if st in valores and w > 0:
                acc += w * valores[st]
                tot += w
        if tot <= 0:
            return valores.get("idle", valores.get("listening", 0.0))
        return acc / tot

    def agitacao(self) -> float:
        return _lim(self.p("thinking") + 0.6 * self.p("tools"))

    def avancar(self, dt, mix=None, voz=0.0, mic=0.0, desperto=1.0):
        self.mix = mix or {"idle": 1.0}
        self.voz, self.mic, self.desperto = _lim(voz), _lim(mic), _lim(desperto)
        self.t += dt
        self._evoluir(dt)
        self._voz_ant = self.voz

    def _evoluir(self, dt):
        pass

    def _ao_glitch(self):
        pass

    def raio(self, w, h, disco=None) -> float:
        """R que cabe no retângulo w×h e, com disco, também num círculo desse raio."""
        ax, ay = self.alcance
        R = min(w / 2 / ax, h / 2 / ay)
        return R if disco is None else min(R, disco / self.alcance_radial)

    # ── desenho comum ──

    def _a(self, a):
        return _lim(a * self.peso)

    def _pisca(self, chave, chance=0.0025) -> float:
        ini = self._piscar.get(chave)
        if ini is None and random.random() < chance:
            self._piscar[chave] = ini = self.t
        if ini is None:
            return 1.0
        f = (self.t - ini) / 0.22
        if f >= 1:
            del self._piscar[chave]
            return 1.0
        return abs(1 - 2 * f)

    def _olhar_para(self, x, y, ang, gaze, foco=1.0, semente=0.0):
        """Direção do olho no referencial dele: para o alvo, ou vagando."""
        dx, dy = gaze[0] - x, gaze[1] - y
        dl = math.hypot(dx, dy) or 1.0
        vx, vy = dx / dl, dy / dl
        if foco < 1.0:
            th = ruido(self.t * 0.9, semente) * math.pi
            vx = foco * vx + (1 - foco) * math.cos(th)
            vy = foco * vy + (1 - foco) * math.sin(th)
            vl = math.hypot(vx, vy) or 1.0
            vx, vy = vx / vl, vy / vl
        ca, sa = math.cos(-ang), math.sin(-ang)
        return (vx * ca - vy * sa, vx * sa + vy * ca)

    def _vagar(self, cx, cy, R):
        return (cx + ruido(self.t * 0.6, 3) * R * 1.4, cy + ruido(self.t * 0.5, 9) * R * 0.8)

    def _raios(self, m, cx, cy, R, lim, n, giro, comp, alfa):
        """Raios atrás de tudo, que se apagam antes da borda da região."""
        t = self.t
        r0 = R * 0.30
        m.set_line_width(0.8 * self.peso)
        for k in range(n):
            a = k * (TAU / n) + giro
            L = min(lim, R * comp * (1.0 + 0.22 * abs(ruido(t * 2.0, k))))
            if L <= r0:
                continue
            meio = r0 + (L - r0) * 0.55
            al = alfa * (0.6 + 0.4 * (0.5 + 0.5 * ruido(t * 3.1, k * 2)))
            ca, sa = math.cos(a), math.sin(a)
            for ra, rb, f in ((r0, meio, 1.0), (meio, L, 0.4)):
                m.move_to(cx + ca * ra, cy + sa * ra)
                m.line_to(cx + ca * rb, cy + sa * rb)
                m.set_source_rgba(1, 1, 1, self._a(al * f))
                m.stroke()

    def _asa(self, m, rx, ry, ang, L, lado, abert, n_olhos, gaze, chave, ocultar=False, alfa=1.0):
        """Asa de penas em traço. ``ang`` é a elevação (0 = horizontal para
        fora, positivo para cima); ``lado`` = +1 estende para a direita."""
        e1 = (lado * math.cos(ang), -math.sin(ang))
        e2 = (lado * math.sin(ang), math.cos(ang))

        def P(u, v):
            return (rx + u * e1[0] + v * e2[0], ry + u * e1[1] + v * e2[1])

        c0, c1, c2, c3 = (0.0, 0.0), (0.25 * L, -0.24 * L), (0.65 * L, -0.22 * L), (L, -0.06 * L)

        def osso(s):
            a, b, c, d = (1 - s) ** 3, 3 * (1 - s) ** 2 * s, 3 * (1 - s) * s * s, s ** 3
            return (a * c0[0] + b * c1[0] + c * c2[0] + d * c3[0],
                    a * c0[1] + b * c1[1] + c * c2[1] + d * c3[1])

        n = 9
        penas = []
        for k in range(n):
            # do corpo (secundárias, curtas e caídas) à ponta (primárias,
            # longas e deitadas na direção da asa)
            f = k / (n - 1)
            bu, bv = osso(0.18 + 0.82 * f)
            phi = (1.50 - 1.15 * f ** 0.8) * (0.30 + 0.70 * abert)
            ell = L * (0.34 + 0.36 * f) * (0.75 + 0.25 * abert)
            tu, tv = bu + ell * math.cos(phi), bv + ell * math.sin(phi)
            cu = (bu + tu) / 2 - 0.10 * ell * math.sin(phi)
            cv = (bv + tv) / 2 + 0.10 * ell * math.cos(phi)
            penas.append(((bu, bv), (cu, cv), (tu, tv), phi))

        if ocultar:
            # A asa da frente esconde o que está atrás dela (o rosto, as chamas).
            m.save()
            m.set_operator(cairo.OPERATOR_DEST_OUT)
            m.move_to(*P(0, 0))
            for s in (0.25, 0.5, 0.75, 1.0):
                m.line_to(*P(*osso(s)))
            for _b, _c, tp, _ph in reversed(penas):
                m.line_to(*P(*tp))
            m.close_path()
            m.set_source_rgba(0, 0, 0, 0.92)
            m.fill()
            m.restore()

        lw = self.peso
        m.move_to(*P(*c0))
        m.curve_to(*P(*c1), *P(*c2), *P(*c3))
        m.set_source_rgba(1, 1, 1, self._a(0.9 * alfa))
        m.set_line_width(1.5 * lw)
        m.stroke()
        for b, c, tp, _ph in penas:
            m.move_to(*P(*b))
            m.curve_to(*P(*c), *P(*c), *P(*tp))
        m.set_source_rgba(1, 1, 1, self._a(0.55 * alfa))
        m.set_line_width(1.0 * lw)
        m.stroke()
        # borda de fuga recortada entre as pontas das penas
        m.move_to(*P(*penas[0][2]))
        for (_b0, _c0, t0, _p0), (_b1, _c1, t1, _p1) in zip(penas, penas[1:]):
            mu, mv = (t0[0] + t1[0]) / 2, (t0[1] + t1[1]) / 2
            m.curve_to(*P(mu, mv + 0.04 * L), *P(mu, mv + 0.04 * L), *P(*t1))
        m.set_source_rgba(1, 1, 1, self._a(0.28 * alfa))
        m.set_line_width(0.8 * lw)
        m.stroke()
        # coberteiras: penas curtas junto ao osso
        for k in range(5):
            bu, bv = osso(0.12 + 0.16 * k)
            phi = 1.25 * (0.4 + 0.6 * abert)
            ell = L * 0.20
            m.move_to(*P(bu, bv))
            m.line_to(*P(bu + ell * math.cos(phi), bv + ell * math.sin(phi)))
        m.set_source_rgba(1, 1, 1, self._a(0.35 * alfa))
        m.set_line_width(0.8 * lw)
        m.stroke()
        # olhos nas penas (Ez 10:12; Ap 4:8)
        if n_olhos and gaze is not None:
            for j in range(n_olhos):
                k = 1 + j * max(1, (n - 2) // max(1, n_olhos))
                if k >= n:
                    break
                b, c, tp, phi = penas[k]
                s = 0.7
                u = (1 - s) ** 2 * b[0] + 2 * (1 - s) * s * c[0] + s * s * tp[0]
                v = (1 - s) ** 2 * b[1] + 2 * (1 - s) * s * c[1] + s * s * tp[1]
                x, y = P(u, v)
                dx, dy = P(u + math.cos(phi), v + math.sin(phi))
                a = math.atan2(dy - y, dx - x)
                ab = self._pisca((chave, j)) * _lim(abert * 1.4)
                olho(m, x, y, a, L * 0.07, ab, self._olhar_para(x, y, a, gaze, 1.0),
                     self._a(0.85 * alfa), lw=lw)

    def _figura(self, m, cx, cy, R, olhar, lim):
        raise NotImplementedError

    def desenhar(self, cr, x, y, w, h, escala, cor, olhar=None, R=None, zoom=1.0, alfa=1.0):
        """Pinta o avatar centrado na região (x, y, w, h) de cr, na cor dada.

        ``olhar``: ponto em coordenadas de cr para onde os olhos olham.
        ``R``: raio da figura; sem ele, o maior que cabe na região.
        """
        if w < 10 or h < 10 or alfa <= 0.01:
            return
        R = (self.raio(w, h) if R is None else R) * zoom
        lx, ly = w / 2, h / 2
        lim = min(w, h) / 2 - 1
        sw, sh = max(1, int(w * escala)), max(1, int(h * escala))
        if self._mascara is None or self._mascara.get_width() != sw or self._mascara.get_height() != sh:
            self._mascara = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
            self._mascara.set_device_scale(escala, escala)
        m = cairo.Context(self._mascara)
        m.set_operator(cairo.OPERATOR_CLEAR)
        m.paint()
        m.set_operator(cairo.OPERATOR_OVER)
        m.set_line_cap(cairo.LINE_CAP_ROUND)
        self._figura(m, lx, ly, R, None if olhar is None else (olhar[0] - x, olhar[1] - y), lim)
        mascara = self._mascara
        r, g, b = cor
        t = self.t
        k = R / R_REF

        glitch = False
        sep = 0.0
        if self.glitch:
            if t >= self._prox_glitch:
                self._glitch_ate = t + random.uniform(0.08, 0.28)
                self._prox_glitch = t + random.uniform(0.9, 3.6) / (1.0 + 3.0 * self.agitacao())
                if random.random() < 0.5:
                    self._ao_glitch()
            glitch = t < self._glitch_ate
            sep = (random.uniform(2.5, 6.0) if glitch else 0.8 + 0.5 * abs(ruido(t, 1))) * max(0.6, k)
            # linhas de varredura recortadas da figura: o fundo fica intocado
            m.set_operator(cairo.OPERATOR_DEST_OUT)
            m.set_source_rgba(0, 0, 0, 0.30)
            yy = (t * 18) % 3
            while yy < h:
                m.rectangle(0, yy, w, 1)
                yy += 3
            m.fill()

        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        if self.contorno:
            # sombra de 1 px em volta do traço: lê sobre fundo claro ou cheio
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_source_rgba(0, 0, 0, 0.32 * alfa)
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                cr.mask_surface(mascara, x + ox, y + oy)
        cr.set_operator(cairo.OPERATOR_ADD)
        if self.glitch:
            # aberração cromática: vermelho e ciano deslocados, a cor no centro
            cr.set_source_rgba(1.0, 0.18, 0.32, 0.40 * alfa)
            cr.mask_surface(mascara, x - sep, y)
            cr.set_source_rgba(0.15, 0.85, 1.0, 0.40 * alfa)
            cr.mask_surface(mascara, x + sep, y)
        cr.set_source_rgba(r, g, b, alfa)
        cr.mask_surface(mascara, x, y)
        if glitch:
            # faixas horizontais da figura arrancadas do lugar
            for _ in range(random.randint(3, 7)):
                y0 = y + ly + random.uniform(-lim, lim)
                fh = random.uniform(2, 14) * max(0.5, k)
                cr.save()
                cr.rectangle(x, y0, w, fh)
                cr.clip()
                cr.set_source_rgba(min(1, r + 0.3), min(1, g + 0.3), min(1, b + 0.3), 0.9 * alfa)
                cr.mask_surface(mascara, x + random.uniform(-26, 26) * k, y)
                cr.restore()
            # cacos soltos, só perto da figura
            for _ in range(random.randint(4, 12)):
                a = random.uniform(0, TAU)
                rr = random.uniform(0.2, 1.0) * min(lim, R * 1.3)
                cr.rectangle(x + lx + math.cos(a) * rr, y + ly + math.sin(a) * rr,
                             random.uniform(4, 28) * max(0.5, k), random.uniform(1, 2))
                cr.set_source_rgba(r, g, b, random.uniform(0.2, 0.6) * alfa)
                cr.fill()
        cr.restore()


class Ofanim(Avatar):
    nome = "Ophanim"
    alcance = (1.55, 1.55)
    alcance_radial = 1.25
    N_ANEIS = 4
    OLHOS = (7, 8, 6, 9)
    # Eixos das rodas travadas (ferramentas): três planos ortogonais e uma diagonal.
    EIXOS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.577, 0.577, 0.577))

    def __init__(self):
        super().__init__()
        self._salto = [0.0] * self.N_ANEIS
        self._semente = [random.uniform(0, 100) for _ in range(self.N_ANEIS)]
        self._foco = 0.3
        self._trava = 0.0
        self._quarto = 0.0
        self._quarto_alvo = 0.0
        self._prox_quarto = 0.0
        self._ondas = []          # (início, força)
        self._ultima_onda = -1.0
        self._brasas = []         # [x, y, vx, vy, início, vida] em unidades de R
        self._acum_brasa = 0.0
        self._relampagos = []     # (início, anel0, ang0, anel1, ang1, semente)
        self._giro_raios = 0.0
        self._pupila = 1.0
        self._clarao = 0.0

    def _ao_glitch(self):
        i = random.randrange(self.N_ANEIS)
        self._salto[i] += random.choice((-1, 1)) * random.uniform(0.4, 1.4)

    def _evoluir(self, dt):
        t = self.t
        ouvir, pensar, ferr = self.p("listening"), self.p("thinking"), self.p("tools")
        falar = self.p("speaking") * self.voz
        giro = self.mistura(idle=1.0, listening=0.45, thinking=3.4, tools=1.4, speaking=1.1) + 1.8 * falar
        giro += (1 - self.desperto) * 5.0      # desdobrando: as rodas giram soltas
        self.fase += dt * giro
        self._giro_raios += dt * (0.07 + 0.5 * pensar + 0.25 * falar)
        foco = self.mistura(idle=0.3, listening=1.0, thinking=0.0, tools=0.55, speaking=0.85)
        self._foco += (foco - self._foco) * min(1.0, dt * 5)
        self._trava += (ferr - self._trava) * min(1.0, dt * 4)
        if ferr > 0.4 and t >= self._prox_quarto:
            self._quarto_alvo += random.choice((1, 1, -1)) * math.pi / 2
            self._prox_quarto = t + random.uniform(0.45, 0.9)
        self._quarto += (self._quarto_alvo - self._quarto) * min(1.0, dt * 9)

        subida = self.voz - self._voz_ant
        if (self.p("speaking") > 0.3 and t - self._ultima_onda > 0.12
                and (subida > 0.05 or (self.voz > 0.3 and t - self._ultima_onda > 0.3))):
            self._ondas.append((t, min(1.0, 0.35 + self.voz)))
            self._ultima_onda = t
        self._ondas = [o for o in self._ondas if t - o[0] < 1.3]

        self._acum_brasa += dt * (16 * pensar + 5 * ferr)
        while self._acum_brasa >= 1:
            self._acum_brasa -= 1
            a, r = random.uniform(0, TAU), random.uniform(0.15, 0.9)
            self._brasas.append([math.cos(a) * r, math.sin(a) * r, random.uniform(-0.15, 0.15),
                                 -random.uniform(0.5, 1.1), t, random.uniform(0.7, 1.4)])
        for b in self._brasas:
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            b[3] += 1.1 * dt          # sobe e desce
        self._brasas = [b for b in self._brasas if t - b[4] < b[5]]

        if random.random() < dt * (2.4 * ferr + 0.5 * pensar):
            self._relampagos.append((t, random.randrange(self.N_ANEIS), random.uniform(0, TAU),
                                     random.randrange(self.N_ANEIS), random.uniform(0, TAU),
                                     random.random() * 100))
        self._relampagos = [r for r in self._relampagos if t - r[0] < 0.12]
        self._clarao = 1.0 if self._relampagos else self._clarao * max(0.0, 1 - dt * 8)

        alvo_p = 1.0 + 0.25 * ouvir + 0.6 * ouvir * self.mic - 0.25 * pensar
        self._pupila += (alvo_p - self._pupila) * min(1.0, dt * 8)

    def _base(self, i):
        """Base (u, v) do plano do anel i, girando em eixos diferentes."""
        t, f = self.t, self.fase
        s = self._semente[i]
        a = f * (0.35 + 0.17 * i) * (1 if i % 2 else -1) + ruido(t * 0.4, s) * 0.6 + self._salto[i]
        b = 0.9 + i * 0.55 + ruido(t * 0.25, s + 7) * 0.5
        n = (math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b))
        if self._trava > 0.01:
            # travadas nos eixos, girando em quartos de volta (Ez 1:17)
            ex = self.EIXOS[i]
            c, sn = math.cos(self._quarto), math.sin(self._quarto)
            ex = (ex[0] * c - ex[1] * sn, ex[0] * sn + ex[1] * c, ex[2])
            c, sn = math.cos(0.55), math.sin(0.55)      # inclinação para ler em 3D
            ex = (ex[0], ex[1] * c - ex[2] * sn, ex[1] * sn + ex[2] * c)
            c, sn = math.cos(0.45), math.sin(0.45)
            ex = (ex[0] * c + ex[2] * sn, ex[1], -ex[0] * sn + ex[2] * c)
            w = self._trava
            n = tuple((1 - w) * n[j] + w * ex[j] for j in range(3))
            nl = math.sqrt(sum(c * c for c in n)) or 1.0
            n = tuple(c / nl for c in n)
        ref = (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)
        u = (n[1] * ref[2] - n[2] * ref[1], n[2] * ref[0] - n[0] * ref[2], n[0] * ref[1] - n[1] * ref[0])
        nu = math.sqrt(sum(c * c for c in u)) or 1.0
        u = tuple(c / nu for c in u)
        v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
        return u, v

    @staticmethod
    def _ponto(u, v, r, th, cx, cy):
        c, s = math.cos(th), math.sin(th)
        x3 = r * (c * u[0] + s * v[0])
        y3 = r * (c * u[1] + s * v[1])
        z3 = r * (c * u[2] + s * v[2])
        p = 1.0 + z3 / (r * 5.0)       # perspectiva leve
        return cx + x3 * p, cy + y3 * p, z3 / r

    def _antes_das_rodas(self, m, cx, cy, R, gaze, lim):
        pass

    def _figura(self, m, cx, cy, R, olhar, lim):
        t = self.t
        d = self.desperto
        R *= 0.25 + 0.75 * _suave(d)
        ouvir, pensar = self.p("listening"), self.p("thinking")
        falar = self.p("speaking") * self.voz
        lw = self.peso

        comp = 1.25 + 0.45 * falar - 0.18 * ouvir + 0.10 * pensar
        self._raios(m, cx, cy, R, lim, 28, self._giro_raios, comp,
                    (0.06 + 0.06 * pensar + 0.10 * falar + 0.15 * self._clarao) * _suave(d))

        # ondas da voz: "o ruído das suas asas, como o de muitas águas"
        for t0, forca in self._ondas:
            idade = (t - t0) / 1.3
            r = R * (0.55 + idade * 1.2)
            if r >= lim:
                continue
            m.arc(cx, cy, r, 0, TAU)
            m.set_source_rgba(1, 1, 1, self._a(forca * (1 - idade) * (1 - r / lim) * 0.55))
            m.set_line_width(1.0 * lw)
            m.stroke()

        gaze = olhar if olhar is not None else self._vagar(cx, cy, R)
        self._antes_das_rodas(m, cx, cy, R, gaze, lim)

        olhos = []
        geo = []
        idx = 0
        total = sum(self.OLHOS)
        for i in range(self.N_ANEIS):
            u, v = self._base(i)
            r = (R * (1.0 - i * 0.075) * (1 - 0.06 * ouvir * self.mic)
                 * (1 + 0.09 * falar * math.sin(t * 9.0 + i * 1.7))
                 * (1 + 0.025 * pensar * math.sin(t * 2.2 + i)))
            geo.append((u, v, r))
            pts = [self._ponto(u, v, r, j * TAU / 96, cx, cy) for j in range(97)]
            for dd, lwb in ((0.0, 1.5), (0.06, 0.5)):
                grupos = [[] for _ in range(TONS)]
                for j in range(96):
                    x0, y0, z0 = pts[j]
                    x1, y1, _ = pts[j + 1]
                    if dd:
                        x0, y0 = cx + (x0 - cx) * (1 - dd), cy + (y0 - cy) * (1 - dd)
                        x1, y1 = cx + (x1 - cx) * (1 - dd), cy + (y1 - cy) * (1 - dd)
                    grupos[min(TONS - 1, int((z0 + 1) / 2 * TONS))].append((x0, y0, x1, y1))
                for kk, segs in enumerate(grupos):
                    if not segs:
                        continue
                    prof = (kk + 0.5) / TONS
                    for x0, y0, x1, y1 in segs:
                        m.move_to(x0, y0)
                        m.line_to(x1, y1)
                    m.set_source_rgba(1, 1, 1, self._a(0.25 + 0.6 * prof))
                    m.set_line_width(lwb * (0.6 + 0.6 * prof) * lw)
                    m.stroke()
            for kk in range(self.OLHOS[i]):
                th = kk * TAU / self.OLHOS[i] + self.fase * 0.05 * (i + 1)
                x, y, z = self._ponto(u, v, r, th, cx, cy)
                x2, y2, _ = self._ponto(u, v, r, th + 0.05, cx, cy)
                olhos.append((z, i, kk, idx, x, y, math.atan2(y2 - y, x2 - x)))
                idx += 1

        # fogo entre as rodas: sobe e desce (Ez 1:13)
        for bx, by, _vx, _vy, t0, vida in self._brasas:
            f = (t - t0) / vida
            px, py = cx + bx * R, cy + by * R
            if math.hypot(px - cx, py - cy) >= lim:
                continue
            m.arc(px, py, max(0.6, 1.1 * lw * (1 - 0.5 * f)), 0, TAU)
            m.set_source_rgba(1, 1, 1, self._a((1 - f) * (0.55 + 0.45 * abs(ruido(t * 9, bx * 50)))))
            m.fill()

        # relâmpagos entre os olhos dos aros (Ez 1:14)
        for t0, i0, a0, i1, a1, sem in self._relampagos:
            al = 1 - (t - t0) / 0.12
            u0, v0, r0 = geo[i0]
            u1, v1, r1 = geo[i1]
            p0 = self._ponto(u0, v0, r0, a0, cx, cy)
            p1 = self._ponto(u1, v1, r1, a1, cx, cy)
            rng = random.Random(sem)
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            dl = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / dl, dx / dl
            pts = [p0[:2]]
            for j in range(1, 6):
                s = j / 6
                o = rng.uniform(-0.14, 0.14) * dl
                pts.append((p0[0] + dx * s + nx * o, p0[1] + dy * s + ny * o))
            pts.append(p1[:2])
            for largura, a in ((3.0, 0.18), (1.2, 0.95)):
                m.move_to(*pts[0])
                for q in pts[1:]:
                    m.line_to(*q)
                m.set_source_rgba(1, 1, 1, self._a(a * al))
                m.set_line_width(largura * lw)
                m.stroke()

        # olhos de trás primeiro; abrem em cascata ao despertar
        olhos.sort()
        for z, i, kk, n, x, y, ang in olhos:
            ab = self._pisca((i, kk)) * _lim((d - 0.45 - 0.4 * n / total) / 0.12)
            if ab <= 0.02:
                continue
            alvo = self._olhar_para(x, y, ang, gaze, self._foco, semente=i * 13 + kk * 7)
            tam = R * 0.125 * (0.6 + 0.5 * (z + 1) / 2)
            olho(m, x, y, ang, tam, ab, alvo, self._a(0.35 + 0.65 * (z + 1) / 2),
                 pupila=self._pupila, lw=lw)

        # núcleo: o olho grande; pálpebra pelo estado, vasculha quando pensa
        m.arc(cx, cy, R * 0.34, 0, TAU)
        m.set_source_rgba(1, 1, 1, self._a(0.08 + 0.10 * falar + 0.08 * pensar * (0.5 + 0.5 * math.sin(t * 6))
                                           + 0.20 * self._clarao))
        m.fill()
        abre = self.mistura(idle=1.0, listening=1.15, thinking=0.55, tools=0.7, speaking=1.0)
        abre *= (1.0 if (t % 6.3) > 0.18 else 0.1) * _lim((d - 0.3) / 0.3)
        if pensar > 0.05:
            vg = (cx + ruido(t * 1.7, 21) * R * 2, cy - R * (0.6 + 0.6 * abs(ruido(t * 1.1, 4))))
            gaze = (gaze[0] * (1 - pensar) + vg[0] * pensar, gaze[1] * (1 - pensar) + vg[1] * pensar)
        dx, dy = gaze[0] - cx, gaze[1] - cy
        dl = math.hypot(dx, dy) or 1.0
        olho(m, cx, cy, 0.0, R * 0.32, abre, (dx / dl, dy / dl), 1.0, pupila=self._pupila, lw=lw)


class OfanimAlado(Ofanim):
    nome = "Ophanim com asas"
    alcance = (2.1, 1.55)
    alcance_radial = 2.08

    def __init__(self):
        super().__init__()
        self._fase_asa = 0.0

    def _evoluir(self, dt):
        super()._evoluir(dt)
        falar = self.p("speaking") * self.voz
        f = self.mistura(idle=0.3, listening=0.3, thinking=2.6, tools=6.0, speaking=1.6) + 1.2 * falar
        self._fase_asa += dt * TAU * f

    def _antes_das_rodas(self, m, cx, cy, R, gaze, lim):
        falar = self.p("speaking") * self.voz
        de = _suave(self.desperto)
        # "quando paravam, abaixavam as asas" (Ez 1:24); abertas para ouvir e
        # batendo no turbilhão; retas e vibrando nas ferramentas (Ez 1:23)
        sup = self.mistura(idle=-0.22, listening=0.32, thinking=0.55, tools=0.10, speaking=0.40)
        inf = self.mistura(idle=-1.05, listening=-0.80, thinking=-0.62, tools=-0.75, speaking=-0.72)
        amp = self.mistura(idle=0.04, listening=0.02, thinking=0.32, tools=0.07, speaking=0.10) + 0.30 * falar
        abert = self.mistura(idle=0.25, listening=0.7, thinking=1.0, tools=0.9, speaking=0.85) * de
        bat = math.sin(self._fase_asa)
        for lado in (-1, 1):
            self._asa(m, cx + lado * 0.52 * R, cy - 0.22 * R, sup + amp * bat, 0.88 * R * de, lado,
                      abert, 3, gaze, ("sup", lado))
            self._asa(m, cx + lado * 0.46 * R, cy + 0.30 * R, inf - 0.5 * amp * bat, 0.66 * R * de, lado,
                      abert * 0.8, 2, gaze, ("inf", lado))


class Serafim(Avatar):
    nome = "Seraphim"
    alcance = (2.0, 1.6)
    alcance_radial = 1.95

    def __init__(self):
        super().__init__()
        self._fase_asa = 0.0
        self._fogo = 1.0
        self._tri = 0.0
        self._abre = 0.0
        self._fumaca = []          # (x0 em R, início, vida, semente)
        self._acum_fumaca = 0.0
        self._brasa_ang = 0.0
        self._brasa = 0.0

    def _evoluir(self, dt):
        t = self.t
        ouvir, pensar, ferr = self.p("listening"), self.p("thinking"), self.p("tools")
        falar = self.p("speaking") * self.voz
        f = self.mistura(idle=0.5, listening=0.3, thinking=2.2, tools=1.4, speaking=1.2) + 0.8 * falar
        self._fase_asa += dt * TAU * f
        # "Santo, santo, santo": três pulsos de luz a cada ciclo, pensando
        ciclo = t % 2.6
        self._tri = pensar * max(math.exp(-((ciclo - c) / 0.07) ** 2) for c in (0.2, 0.55, 0.9))
        alvo = (self.mistura(idle=1.0, listening=0.85, thinking=1.4, tools=1.15, speaking=1.0)
                + 0.6 * falar + 0.5 * self._tri)
        self._fogo += (alvo - self._fogo) * min(1.0, dt * (10 if alvo > self._fogo else 3))
        self._abre += (ouvir - self._abre) * min(1.0, dt * 4)
        self._acum_fumaca += dt * 3.5 * pensar
        while self._acum_fumaca >= 1:
            self._acum_fumaca -= 1
            self._fumaca.append((random.uniform(-0.35, 0.35), t, random.uniform(2.0, 2.8),
                                 random.uniform(0, 50)))
        self._fumaca = [s for s in self._fumaca if t - s[1] < s[2]]
        self._brasa_ang += dt * 2.4
        self._brasa += (ferr - self._brasa) * min(1.0, dt * 4)

    def _chamas(self, m, cx, cy, R):
        t, fogo = self.t, self._fogo
        base = cy + 0.38 * R
        lw = self.peso
        for j in range(11):
            off = (j - 5) / 5.0
            x0 = cx + off * 0.16 * R
            h = R * (0.72 + 0.30 * (0.5 + 0.5 * ruido(t * 3.0, j * 3.1))) * fogo * (1 - 0.45 * off * off)
            sway = ruido(t * 2.3, j * 1.9) * 0.10 * R + off * 0.22 * R
            wb = R * (0.06 + 0.03 * (1 - abs(off)))
            tx, ty = x0 + sway, base - h
            m.move_to(x0 - wb, base)
            m.curve_to(x0 - wb, base - h * 0.45, tx - wb * 0.2 + sway * 0.3, ty + h * 0.35, tx, ty)
            m.curve_to(tx + wb * 0.2 + sway * 0.3, ty + h * 0.35, x0 + wb, base - h * 0.45, x0 + wb, base)
            m.close_path()
            m.set_source_rgba(1, 1, 1, self._a(0.07))
            m.fill_preserve()
            m.set_source_rgba(1, 1, 1, self._a(0.35 + 0.25 * (1 - abs(off))))
            m.set_line_width(0.9 * lw)
            m.stroke()
        m.arc(cx, cy, R * 0.34, 0, TAU)
        m.set_source_rgba(1, 1, 1, self._a(0.14 + 0.30 * self._tri))
        m.fill()

    def _figura(self, m, cx, cy, R, olhar, lim):
        t = self.t
        de = _suave(self.desperto)
        R *= 0.3 + 0.7 * de
        falar = self.p("speaking") * self.voz
        lw = self.peso
        # "os umbrais tremeram à voz" (Is 6:4)
        k = R / 40.0
        cx += ruido(t * 40, 1) * 2.2 * k * falar
        cy += ruido(t * 37, 5) * 2.2 * k * falar
        gaze = olhar if olhar is not None else self._vagar(cx, cy, R)

        self._raios(m, cx, cy, R, lim, 24, t * 0.05, 1.35 + 0.4 * falar,
                    (0.05 + 0.10 * self._tri + 0.06 * falar) * de)

        # com duas voava: atrás do corpo
        ele = self.mistura(idle=0.20, listening=0.10, thinking=0.35, tools=0.25, speaking=0.30)
        amp = self.mistura(idle=0.16, listening=0.05, thinking=0.38, tools=0.25, speaking=0.18) + 0.3 * falar
        abert = self.mistura(idle=0.75, listening=0.6, thinking=1.0, tools=0.9, speaking=0.9) * de
        bat = math.sin(self._fase_asa)
        for lado in (-1, 1):
            self._asa(m, cx + lado * 0.22 * R, cy - 0.02 * R, ele + amp * bat, 1.0 * R * de, lado,
                      abert, 3, gaze, ("voo", lado))

        self._chamas(m, cx, cy, R)

        # o rosto: só aparece quando as asas de cima se abrem para ouvir
        if self._abre > 0.05:
            ex, ey = cx, cy - 0.20 * R
            dx, dy = gaze[0] - ex, gaze[1] - ey
            dl = math.hypot(dx, dy) or 1.0
            olho(m, ex, ey, 0.0, R * 0.17, self._abre * self._pisca("rosto"),
                 (dx / dl, dy / dl), 1.0, pupila=1.0 + 0.5 * self.mic, lw=lw)

        # com duas cobria os pés e com duas o rosto: na frente, escondendo
        respira = 0.04 * math.sin(self._fase_asa * 0.5)
        for lado in (-1, 1):
            self._asa(m, cx - lado * 0.10 * R, cy + 0.34 * R, -0.95 + respira, 0.72 * R * de, lado,
                      0.85 * de, 0, None, ("pes", lado), ocultar=True)
        # Fechadas, as penas pendem para dentro, sobre o rosto; abertas, para
        # fora. A troca de lado acontece com a asa em pé e as penas recolhidas,
        # onde não se vê: lê como um leque que abre.
        a = _suave(self._abre)
        for lado in (-1, 1):
            if a < 0.5:
                q = a / 0.5
                ang, para, ab = 1.05 + (math.pi / 2 - 1.05) * q, lado, 0.85 - 0.75 * q
            else:
                q = (a - 0.5) / 0.5
                ang, para, ab = math.pi / 2 - 0.55 * q, -lado, 0.10 + 0.65 * q
            self._asa(m, cx - lado * (0.10 + 0.12 * a) * R, cy - 0.30 * R, ang + respira,
                      0.85 * R * de, para, ab * de, 0, None, ("rosto", lado), ocultar=True)

        # "a casa se encheu de fumaça" (Is 6:4)
        for x0, t0, vida, sem in self._fumaca:
            f = (t - t0) / vida
            px = cx + x0 * R + ruido(t * 0.7, sem) * 0.25 * R * f
            py = cy - 0.55 * R - f * 0.9 * R
            if math.hypot(px - cx, py - cy) + 0.15 * R >= lim:
                continue
            s = 0.15 * R * (1 + f)
            m.move_to(px - s, py)
            m.curve_to(px - s * 0.3, py - s * 0.8, px + s * 0.3, py + s * 0.8, px + s, py)
            m.set_source_rgba(1, 1, 1, self._a(0.20 * math.sin(math.pi * f)))
            m.set_line_width((0.8 + 2.5 * f) * lw)
            m.stroke()

        # a brasa tirada do altar (Is 6:6), circulando nas ferramentas
        if self._brasa > 0.03:
            for j in range(7):
                a = self._brasa_ang - j * 0.12
                bx, by = cx + math.cos(a) * 1.05 * R, cy + math.sin(a) * 0.55 * R
                if j == 0:
                    m.arc(bx, by, 0.11 * R, 0, TAU)
                    m.set_source_rgba(1, 1, 1, self._a(0.22 * self._brasa))
                    m.fill()
                m.arc(bx, by, max(0.6, 0.05 * R * (1 - j / 8)), 0, TAU)
                m.set_source_rgba(1, 1, 1, self._a(self._brasa * (1 - j / 7)))
                m.fill()


SKINS = {"ofanim": Ofanim, "ofanim_alado": OfanimAlado, "serafim": Serafim}
NOMES = {"ofanim": "Ophanim", "ofanim_alado": "Ophanim com asas", "serafim": "Seraphim",
         "anel": "Anel de energia"}


def criar(skin: str) -> Avatar | None:
    cls = SKINS.get(skin)
    return cls() if cls else None
