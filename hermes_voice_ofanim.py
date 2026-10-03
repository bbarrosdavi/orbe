"""Ofanim: o anjo de rodas com olhos, com glitch (Cairo puro).

"Rodas dentro de rodas, os aros cheios de olhos" (Ezequiel 1:16-18, 10:12):
anéis girando em eixos diferentes, olhos nos aros, um olho grande no centro,
raios atrás, aberração cromática e rajadas de glitch erráticas. Os olhos
seguem o ponteiro quando ele está sobre o desenho; sem ponteiro, vagueiam.

Um desenho só para dois lugares: o topo do app de configuração
(hermes_voice_app.py) e a skin "ofanim" do orbe (hermes_voice_orb.py). O app
chama sem energia nem agitação; o orbe passa o nível da voz (energia) e o
peso de pensando/ferramentas (agitação), que aceleram o giro, o pulso e a
frequência do glitch.
"""
import math
import random

import cairo

N_ANEIS = 4
OLHOS = (7, 8, 6, 9)
# Raio de referência do topo do app: os deslocamentos do glitch, em px,
# foram afinados nele e escalam com o raio em outros tamanhos.
R_REF = 82.0
# Tons de profundidade por anel: traços agrupados por tom em vez de um traço
# por segmento (96 por anel). Mesmo desenho, uma fração do custo.
TONS = 12


def ruido(t: float, semente: float) -> float:
    """Ruído suave barato: soma de senos com fases irracionais, em [-1, 1]."""
    return (math.sin(t * 1.31 + semente) * 0.5 + math.sin(t * 2.17 + semente * 1.7) * 0.3
            + math.sin(t * 0.53 + semente * 2.9) * 0.2)


class Ofanim:
    def __init__(self):
        self.t = 0.0          # relógio de parede (glitch, piscadas, ruído)
        self.fase = 0.0       # relógio do giro: acelera com energia e agitação
        self._salto = [0.0] * N_ANEIS
        self._glitch_ate = 0.0
        self._prox_glitch = 1.2
        self._piscar = {}     # (anel, olho) -> início da piscada
        self._semente = [random.uniform(0, 100) for _ in range(N_ANEIS)]
        self._mascara = None
        self._energia = 0.0
        self._agitacao = 0.0

    def avancar(self, dt: float, energia: float = 0.0, agitacao: float = 0.0) -> None:
        self._energia = max(0.0, min(1.0, energia))
        self._agitacao = max(0.0, min(1.0, agitacao))
        self.t += dt
        self.fase += dt * (1.0 + 1.6 * self._agitacao + 1.2 * self._energia)

    # ── geometria ──

    def _base(self, i: int) -> tuple:
        """Base (u, v) do plano do anel i, girando em eixos diferentes."""
        t, f = self.t, self.fase
        s = self._semente[i]
        a = f * (0.35 + 0.17 * i) * (1 if i % 2 else -1) + ruido(t * 0.4, s) * 0.6 + self._salto[i]
        b = 0.9 + i * 0.55 + ruido(t * 0.25, s + 7) * 0.5
        n = (math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b))
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

    # ── desenho ──

    @staticmethod
    def _olho(cr, x, y, ang, tam, abertura, alvo, alfa):
        cr.save()
        cr.translate(x, y)
        cr.rotate(ang)
        w, h = tam, tam * 0.48 * abertura
        cr.move_to(-w, 0)
        cr.curve_to(-w * 0.45, -h * 1.25, w * 0.45, -h * 1.25, w, 0)
        cr.curve_to(w * 0.45, h * 1.25, -w * 0.45, h * 1.25, -w, 0)
        cr.close_path()
        cr.set_source_rgba(1, 1, 1, alfa * 0.95)
        cr.set_line_width(max(0.8, tam * 0.13))
        cr.stroke_preserve()
        cr.set_source_rgba(1, 1, 1, alfa * 0.10)
        cr.fill_preserve()
        if abertura > 0.25:
            cr.clip()
            ix, iy = alvo
            cr.arc(ix * w * 0.35, iy * h * 0.35, tam * 0.42, 0, 2 * math.pi)
            cr.set_source_rgba(1, 1, 1, alfa * 0.85)
            cr.fill()
            cr.arc(ix * w * 0.40, iy * h * 0.40, tam * 0.17, 0, 2 * math.pi)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.fill()
        cr.restore()

    def _anjo(self, w, h, escala, cx, cy, R, olhar):
        """Desenha o anjo em branco numa máscara do tamanho da região."""
        sw, sh = max(1, int(w * escala)), max(1, int(h * escala))
        if self._mascara is None or self._mascara.get_width() != sw or self._mascara.get_height() != sh:
            self._mascara = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
            self._mascara.set_device_scale(escala, escala)
        m = cairo.Context(self._mascara)
        m.set_operator(cairo.OPERATOR_CLEAR)
        m.paint()
        m.set_operator(cairo.OPERATOR_OVER)
        t = self.t
        en = self._energia

        # raios atrás de tudo, tremulando
        for k in range(28):
            a = k * (2 * math.pi / 28) + t * 0.07
            comp = R * (1.25 + 0.35 * abs(ruido(t * 2.0, k)) + 0.25 * en)
            m.move_to(cx + math.cos(a) * R * 0.30, cy + math.sin(a) * R * 0.30)
            m.line_to(cx + math.cos(a) * comp, cy + math.sin(a) * comp)
            m.set_source_rgba(1, 1, 1, 0.05 + 0.06 * (0.5 + 0.5 * ruido(t * 3.1, k * 2)) + 0.08 * en)
            m.set_line_width(0.8)
            m.stroke()

        if olhar is not None:
            gx, gy = olhar
        else:
            gx = cx + ruido(t * 0.6, 3) * R * 1.4
            gy = cy + ruido(t * 0.5, 9) * R * 0.8

        olhos = []
        for i in range(N_ANEIS):
            u, v = self._base(i)
            r = R * (1.0 - i * 0.075)
            pts = [self._ponto(u, v, r, j * 2 * math.pi / 96, cx, cy) for j in range(97)]
            # aro duplo; tom e espessura pela profundidade, agrupados por tom
            for d, lw in ((0.0, 1.5), (0.06, 0.5)):
                grupos = [[] for _ in range(TONS)]
                for j in range(96):
                    x0, y0, z0 = pts[j]
                    x1, y1, _ = pts[j + 1]
                    if d:
                        x0, y0 = cx + (x0 - cx) * (1 - d), cy + (y0 - cy) * (1 - d)
                        x1, y1 = cx + (x1 - cx) * (1 - d), cy + (y1 - cy) * (1 - d)
                    k = min(TONS - 1, int((z0 + 1) / 2 * TONS))
                    grupos[k].append((x0, y0, x1, y1))
                for k, segs in enumerate(grupos):
                    if not segs:
                        continue
                    prof = (k + 0.5) / TONS
                    for x0, y0, x1, y1 in segs:
                        m.move_to(x0, y0)
                        m.line_to(x1, y1)
                    m.set_source_rgba(1, 1, 1, 0.25 + 0.6 * prof)
                    m.set_line_width(lw * (0.6 + 0.6 * prof))
                    m.stroke()
            n = OLHOS[i]
            for k in range(n):
                th = k * 2 * math.pi / n + self.fase * 0.05 * (i + 1)
                x, y, z = self._ponto(u, v, r, th, cx, cy)
                x2, y2, _ = self._ponto(u, v, r, th + 0.05, cx, cy)
                olhos.append((z, i, k, x, y, math.atan2(y2 - y, x2 - x)))

        # olhos de trás primeiro
        olhos.sort()
        for z, i, k, x, y, ang in olhos:
            ini = self._piscar.get((i, k))
            if ini is None and random.random() < 0.0025:
                self._piscar[(i, k)] = t
                ini = t
            abertura = 1.0
            if ini is not None:
                f = (t - ini) / 0.22
                if f >= 1:
                    del self._piscar[(i, k)]
                else:
                    abertura = abs(1 - 2 * f)
            dx, dy = gx - x, gy - y
            dl = math.hypot(dx, dy) or 1.0
            ca, sa = math.cos(-ang), math.sin(-ang)
            alvo = ((dx * ca - dy * sa) / dl, (dx * sa + dy * ca) / dl)
            tam = R * 0.125 * (0.6 + 0.5 * (z + 1) / 2)
            self._olho(m, x, y, ang, tam, abertura, alvo, 0.35 + 0.65 * (z + 1) / 2)

        # núcleo: um olho grande que pisca no próprio ritmo
        dx, dy = gx - cx, gy - cy
        dl = math.hypot(dx, dy) or 1.0
        m.arc(cx, cy, R * 0.34, 0, 2 * math.pi)
        m.set_source_rgba(1, 1, 1, 0.08 + 0.10 * en)
        m.fill()
        self._olho(m, cx, cy, 0.0, R * 0.32, 1.0 if (t % 6.3) > 0.18 else 0.1,
                   (dx / dl, dy / dl), 1.0)
        return self._mascara

    def desenhar(self, cr, x, y, w, h, escala, cor, olhar=None, R=None, cy=None, alfa=1.0):
        """Pinta o anjo na região (x, y, w, h) de cr, na cor dada.

        ``olhar``: ponto em coordenadas de cr para onde os olhos olham.
        ``R``: raio dos anéis; sem ele, o do topo do app (cabe na região).
        """
        if w < 10 or h < 10 or alfa <= 0.01:
            return
        if R is None:
            R = min(h * 0.42, w * 0.32)
        R *= 1.0 + 0.08 * self._energia
        lx, ly = w / 2, (h / 2 + 2 if cy is None else cy - y)
        olhar_local = None if olhar is None else (olhar[0] - x, olhar[1] - y)
        mascara = self._anjo(w, h, escala, lx, ly, R, olhar_local)
        r, g, b = cor
        t = self.t
        k = R / R_REF

        if t >= self._prox_glitch:
            self._glitch_ate = t + random.uniform(0.08, 0.28)
            self._prox_glitch = t + random.uniform(0.9, 3.6) / (1.0 + 3.0 * self._agitacao)
            if random.random() < 0.5:
                i = random.randrange(N_ANEIS)
                self._salto[i] += random.choice((-1, 1)) * random.uniform(0.4, 1.4)
        glitch = t < self._glitch_ate
        sep = (random.uniform(2.5, 6.0) if glitch else 0.8 + 0.5 * abs(ruido(t, 1))) * max(0.6, k)

        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.set_operator(cairo.OPERATOR_ADD)
        # aberração cromática: vermelho e ciano deslocados, a cor no centro
        cr.set_source_rgba(1.0, 0.18, 0.32, 0.40 * alfa)
        cr.mask_surface(mascara, x - sep, y)
        cr.set_source_rgba(0.15, 0.85, 1.0, 0.40 * alfa)
        cr.mask_surface(mascara, x + sep, y)
        cr.set_source_rgba(r, g, b, min(1.0, 0.9 + 0.1 * self._energia) * alfa)
        cr.mask_surface(mascara, x, y)

        if glitch:
            # faixas horizontais arrancadas do lugar
            for _ in range(random.randint(3, 7)):
                y0 = y + random.uniform(0, h)
                fh = random.uniform(2, 14) * max(0.5, k)
                cr.save()
                cr.rectangle(x, y0, w, fh)
                cr.clip()
                cr.set_source_rgba(min(1, r + 0.3), min(1, g + 0.3), min(1, b + 0.3), 0.9 * alfa)
                cr.mask_surface(mascara, x + random.uniform(-26, 26) * k, y)
                cr.restore()
            for _ in range(random.randint(4, 12)):
                cr.rectangle(x + random.uniform(0, w), y + random.uniform(0, h),
                             random.uniform(4, 40) * max(0.5, k), random.uniform(1, 2))
                cr.set_source_rgba(r, g, b, random.uniform(0.2, 0.6) * alfa)
                cr.fill()

        # linhas de varredura
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgba(0, 0, 0, 0.10 * alfa)
        yy = y + (t * 18) % 3
        while yy < y + h:
            cr.rectangle(x, yy, w, 1)
            yy += 3
        cr.fill()
        cr.restore()
