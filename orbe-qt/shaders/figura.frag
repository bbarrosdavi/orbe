#version 440
// Figuras do orbe (Ophanim, Ophanim com asas, Shoggoth) desenhadas inteiras na
// GPU por distância: cada traço do desenho em Cairo (hermes_voice_avatares.py)
// vira uma função de distância, e a cobertura sai da distância e da largura do
// traço. A saída é a máscara branca da figura no canal vermelho (e, no
// Shoggoth, a massa escura no verde); a cor, a
// aberração cromática, as faixas e as linhas de varredura são do pos.frag.
//
// O estado que tem memória (giro das rodas, asas, relâmpagos, ondas) vem do
// Figura.qml por uniform; o que é só função do tempo (brasas, fumaça, piscadas,
// olhos dos aros) nasce aqui.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 tam;        // tamanho do item, px lógicos
    vec2 centro;     // centro da figura
    vec2 olhar;      // para onde os olhos olham
    vec2 nucleoDir;  // direção do olho central (unitária)
    vec4 geo;        // R (já com o desdobrar), lim, t, peso
    vec4 est;        // ouvir, pensar, ferramentas, falar (speaking * voz)
    vec4 est2;       // voz, mic, desperto, skin (0 ofanim, 1 alado, 3 shoggoth)
    vec4 ofa;        // foco, pupila, clarão, abertura do olho central
    vec4 ofa2;       // fase, desperto suavizado, nº de asas, —
    vec4 raios;      // quantidade, giro, comprimento, alfa
    vec4 a0u; vec4 a0v; vec4 a1u; vec4 a1v;   // anéis: u.xyz + raio, v.xyz
    vec4 a2u; vec4 a2v; vec4 a3u; vec4 a3v;
    vec4 ondas0; vec4 ondas1; vec4 ondas2; vec4 ondas3;   // (raio, alfa) x 2
    vec4 rel0; vec4 rel1; vec4 relInfo;   // relâmpagos: p0, p1; (alfa, semente) x 2
    vec4 w0a; vec4 w0b; vec4 w1a; vec4 w1b; vec4 w2a; vec4 w2b;   // asas: raiz, ângulo, L;
    vec4 w3a; vec4 w3b; vec4 w4a; vec4 w4b; vec4 w5a; vec4 w5b;   //   lado, abertura, olhos, ocultar
    vec4 sho;        // Shoggoth: fase dos tentáculos, alcance, boca, pulso da voz
    vec4 sho2;       //   máscara: deslocamento x, y, inclinação, alfa
    vec4 sho3;       //   inclinação dos tentáculos para o olhar, —, —, crescer
    vec4 sho4;       //   —, —, abertura das bocas de dentes, —
    vec4 lacos;      // nº de olhos (30), vagas de brasa (24), vagas de fumaça (10), asas;
                     //   no Shoggoth: massas do monte, —, tentáculos, 0
};

// Os limites dos laços vêm de uniform de propósito: com constante, o
// compilador do driver desenrola tudo e embute cada chamada, e a primeira
// compilação passava de 25 s. O desenho é o mesmo.
int nOlhos_() { return int(lacos.x + 0.5); }
int nBrasas_() { return int(lacos.y + 0.5); }
int nFumaca_() { return int(lacos.z + 0.5); }
int nAsas_() { return int(lacos.w + 0.5); }

vec4 asaA(int i) { return i == 0 ? w0a : i == 1 ? w1a : i == 2 ? w2a : i == 3 ? w3a : i == 4 ? w4a : w5a; }
vec4 asaB(int i) { return i == 0 ? w0b : i == 1 ? w1b : i == 2 ? w2b : i == 3 ? w3b : i == 4 ? w4b : w5b; }

const float TAU = 6.283185307179586;
const float PI = 3.141592653589793;

float sat(float v) { return clamp(v, 0.0, 1.0); }
float suave(float x) { x = sat(x); return x * x * (3.0 - 2.0 * x); }

float ruido(float t, float s) {
    return sin(t * 1.31 + s) * 0.5 + sin(t * 2.17 + s * 1.7) * 0.3 + sin(t * 0.53 + s * 2.9) * 0.2;
}

float hash(float n) {
    n = fract(n * 0.1031);
    n *= n + 33.33;
    n *= n + n;
    return fract(n);
}

float hash2(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

// alfa com o peso do traço (o orbe usa traço mais grosso e opaco que o menu)
float pa(float a) { return sat(a * geo.w); }

// cobertura de um traço de largura w a distância d do eixo; abaixo de 1 px
// físico, o traço espalha num pixel com a intensidade proporcional, como o Cairo
float traco(float d, float w, float aa) {
    float we = max(w, aa);
    return (w / we) * sat((0.5 * we - d) / aa + 0.5);
}

float cobre(float sd, float aa) { return sat(0.5 - sd / aa); }

// Cobertura da íris no pixel (canal b da máscara): o pos.frag pinta ali a cor
// própria dos olhos, quando há uma. O que é desenhado por cima a cobre também.
float IR_ = 0.0;

void sobre(inout float A, float a) { A = a + A * (1.0 - a); IR_ *= 1.0 - a; }

float segd(vec2 p, vec2 a, vec2 b) {
    vec2 pa_ = p - a, ba = b - a;
    float h = sat(dot(pa_, ba) / max(dot(ba, ba), 1e-8));
    return length(pa_ - ba * h);
}

float dot2(vec2 v) { return dot(v, v); }

// distância exata a uma bézier quadrática (Inigo Quilez)
float bezq(vec2 pos, vec2 A, vec2 B, vec2 C) {
    vec2 a = B - A;
    vec2 b = A - 2.0 * B + C;
    if (dot(b, b) < 1e-6) return segd(pos, A, C);
    vec2 c = a * 2.0;
    vec2 d = A - pos;
    float kk = 1.0 / dot(b, b);
    float kx = kk * dot(a, b);
    float ky = kk * (2.0 * dot(a, a) + dot(d, b)) / 3.0;
    float kz = kk * dot(d, a);
    float p = ky - kx * kx;
    float p3 = p * p * p;
    float q = kx * (2.0 * kx * kx - 3.0 * ky) + kz;
    float h = q * q + 4.0 * p3;
    float res;
    if (h >= 0.0) {
        h = sqrt(h);
        vec2 x = (vec2(h, -h) - q) / 2.0;
        vec2 uv = sign(x) * pow(abs(x), vec2(1.0 / 3.0));
        float tt = sat(uv.x + uv.y - kx);
        res = dot2(d + (c + b * tt) * tt);
    } else {
        float z = sqrt(-p);
        float v = acos(clamp(q / (p * z * 2.0), -1.0, 1.0)) / 3.0;
        float m = cos(v);
        float n = sin(v) * 1.732050808;
        vec3 tt = clamp(vec3(m + m, -n - m, n - m) * z - kx, 0.0, 1.0);
        res = min(dot2(d + (c + b * tt.x) * tt.x), dot2(d + (c + b * tt.y) * tt.y));
    }
    return sqrt(res);
}

vec2 cubica(vec2 a, vec2 b, vec2 c, vec2 d, float s) {
    float u = 1.0 - s;
    return u * u * u * a + 3.0 * u * u * s * b + 3.0 * u * s * s * c + s * s * s * d;
}

// distância com sinal a um polígono (negativa dentro), Inigo Quilez
float sdPoly14(vec2 p, vec2 v[14], int n) {
    float d = dot2(p - v[0]);
    float s = 1.0;
    int j = n - 1;
    for (int i = 0; i < 14; i++) {
        if (i >= n) break;
        vec2 e = v[j] - v[i];
        vec2 w = p - v[i];
        vec2 b = w - e * sat(dot(w, e) / max(dot(e, e), 1e-8));
        d = min(d, dot2(b));
        bvec3 cond = bvec3(p.y >= v[i].y, p.y < v[j].y, e.x * w.y > e.y * w.x);
        if (all(cond) || all(not(cond))) s *= -1.0;
        j = i;
    }
    return s * sqrt(d);
}

// ── olhos ──

// piscada: cada olho pisca uma vez a cada 9 a 18 s, por 0,22 s
float pisca(float chave) {
    float T = 9.0 + 9.0 * hash(chave * 7.13 + 0.7);
    float ph = mod(geo.z + hash(chave * 3.71 + 1.3) * T, T);
    return ph >= 0.22 ? 1.0 : abs(1.0 - 2.0 * ph / 0.22);
}

// direção do olho no referencial dele: para o alvo, ou vagando (foco < 1)
vec2 olharPara(vec2 pos, float ang, float foco, float semente) {
    vec2 dv = olhar - pos;
    float dl = length(dv);
    vec2 v = dl > 1e-4 ? dv / dl : vec2(1.0, 0.0);
    if (foco < 1.0) {
        float th = ruido(geo.z * 0.9, semente) * PI;
        v = foco * v + (1.0 - foco) * vec2(cos(th), sin(th));
        float vl = length(v);
        v = vl > 1e-4 ? v / vl : vec2(1.0, 0.0);
    }
    float ca = cos(-ang), sa = sin(-ang);
    return vec2(v.x * ca - v.y * sa, v.x * sa + v.y * ca);
}

// Shoggoth: pupila em fenda vertical e íris maior; 0 nas outras figuras
float fenda_ = 0.0;

// olho amendoado com íris e pupila vazada; alvo no referencial do olho
void olho(inout float A, vec2 p, vec2 pos, float ang, float tam_, float ab, vec2 alvo,
          float alfa, float pup, float lw, float aa) {
    vec2 d = p - pos;
    float rmax = tam_ * 1.3 + lw * 2.0 + aa * 2.0;
    if (dot(d, d) > rmax * rmax) return;
    float ca = cos(ang), sa = sin(ang);
    vec2 q = vec2(ca * d.x + sa * d.y, -sa * d.x + ca * d.y);
    float w = tam_, h = tam_ * 0.48 * ab;
    float u = q.x / w;
    float dponta = length(vec2(abs(q.x) - w, q.y));
    float sd;
    if (abs(u) >= 1.0) {
        sd = dponta;
    } else {
        // as duas béziers da pálpebra, aproximadas por Y(x) = 0,9375 h (1 - u²)^0,85
        float s = 1.0 - u * u;
        float Y = 0.9375 * h * pow(s, 0.85);
        float dY = 0.9375 * h * 0.85 * pow(max(s, 1e-3), -0.15) * (-2.0 * u) / w;
        sd = (abs(q.y) - Y) / sqrt(1.0 + dY * dY);
        if (sd > 0.0) sd = min(sd, dponta);
    }
    sobre(A, traco(abs(sd), max(0.8, tam_ * 0.13) * lw, aa) * sat(alfa * 0.95));
    float dentro = cobre(sd, aa);
    sobre(A, dentro * sat(alfa * 0.10));
    if (ab > 0.25) {
        vec2 ic = vec2(alvo.x * w * 0.35, alvo.y * h * 0.35);
        float ir = dentro * cobre(length(q - ic) - tam_ * (fenda_ > 0.5 ? 0.50 : 0.42), aa) * sat(alfa * 0.85);
        sobre(A, ir);
        IR_ += ir;
        vec2 pc = vec2(alvo.x * w * 0.40, alvo.y * h * 0.40);
        float sdP = length(q - pc) - tam_ * 0.17 * pup;
        if (fenda_ > 0.5) {
            vec2 rp = vec2(tam_ * 0.07 * pup * pup, tam_ * 0.40);
            sdP = (length((q - pc) / rp) - 1.0) * rp.x;
        }
        float furo = dentro * cobre(sdP, aa);
        A *= 1.0 - furo;
        IR_ *= 1.0 - furo;
    }
}

// ── raios e ondas ──

void desenhaRaios(inout float A, vec2 p, vec2 c, float R, float lim, float lw, float aa) {
    float n = raios.x, giro = raios.y, comp = raios.z, alfa = raios.w;
    if (alfa <= 0.001 || n < 1.0) return;
    vec2 d = p - c;
    float rr = length(d);
    float r0 = R * 0.30;
    if (rr < r0 - 2.0 || rr > lim + 2.0) return;
    float passo = TAU / n;
    float k0 = floor((atan(d.y, d.x) - giro) / passo + 0.5);
    for (int j = -1; j <= 1; j++) {
        float k = mod(k0 + float(j), n);
        float a = k * passo + giro;
        float L = min(lim, R * comp * (1.0 + 0.22 * abs(ruido(geo.z * 2.0, k))));
        if (L <= r0) continue;
        float meio = r0 + (L - r0) * 0.55;
        float al = alfa * (0.6 + 0.4 * (0.5 + 0.5 * ruido(geo.z * 3.1, k * 2.0)));
        vec2 dir = vec2(cos(a), sin(a));
        sobre(A, traco(segd(p, c + dir * r0, c + dir * meio), 0.8 * lw, aa) * pa(al));
        sobre(A, traco(segd(p, c + dir * meio, c + dir * L), 0.8 * lw, aa) * pa(al * 0.4));
    }
}

void onda(inout float A, vec2 p, vec2 c, vec2 ra, float lw, float aa) {
    if (ra.y <= 0.001) return;
    sobre(A, traco(abs(length(p - c) - ra.x), 1.0 * lw, aa) * pa(ra.y));
}

// ── Ophanim ──

void asa(inout float A, vec2 p, vec4 wa, vec4 wb, float slot, float lw, float aa);

struct Anel { vec3 u; vec3 v; float r; };

Anel anel(int i) {
    vec4 u = i == 0 ? a0u : i == 1 ? a1u : i == 2 ? a2u : a3u;
    vec4 v = i == 0 ? a0v : i == 1 ? a1v : i == 2 ? a2v : a3v;
    Anel a;
    a.u = u.xyz; a.v = v.xyz; a.r = u.w;
    return a;
}

// ponto do anel no ângulo th: xy na tela, z = profundidade em [-1, 1]
vec3 anelP(Anel a, vec2 c, float th, float esc) {
    float co = cos(th), si = sin(th);
    float z = co * a.u.z + si * a.v.z;
    vec2 w = co * a.u.xy + si * a.v.xy;
    return vec3(c + w * (a.r * esc * (1.0 + z / 5.0)), z);
}

// ângulo do ponto do anel mais perto de p: chute pela inversa da elipse e
// três passos de Newton na distância (a perspectiva leve deforma a elipse)
float anelTheta(Anel a, vec2 c, vec2 p) {
    vec2 q = (p - c) / max(a.r, 1e-3);
    vec2 U = a.u.xy, V = a.v.xy;
    float det = U.x * V.y - V.x * U.y;
    vec2 ab = vec2(V.y * q.x - V.x * q.y, -U.y * q.x + U.x * q.y) * (det < 0.0 ? -1.0 : 1.0);
    float th = atan(ab.y, ab.x + 1e-9);
    for (int k = 0; k < 3; k++) {
        float co = cos(th), si = sin(th);
        float z = co * a.u.z + si * a.v.z;
        float dz = -si * a.u.z + co * a.v.z;
        vec2 w = co * U + si * V;
        vec2 dw = -si * U + co * V;
        float kk = 1.0 + z / 5.0, dk = dz / 5.0, d2k = -z / 5.0;
        vec2 P = c + a.r * kk * w;
        vec2 P1 = a.r * (dk * w + kk * dw);
        vec2 P2 = a.r * (d2k * w + 2.0 * dk * dw - kk * w);
        vec2 e = P - p;
        float g2 = max(dot(P1, P1) + dot(e, P2), dot(P1, P1) * 0.3 + 1e-6);
        th -= dot(e, P1) / g2;
    }
    return th;
}

// olhos candidatos num pixel: guardo até três para pintar de trás para frente
struct OlhoC { vec2 pos; float ang; float tam; float ab; vec2 alvo; float alfa; float z; };

#if SKIN < 2
void ofanim(inout float A, vec2 p, float aa, bool alado) {
    float R = geo.x, lim = geo.y, t = geo.z, lw = geo.w;
    float ouvir = est.x, pensar = est.y, ferr = est.z, falar = est.w;
    float mic = est2.y, d = est2.z;
    float foco = ofa.x, pupila = ofa.y, clarao = ofa.z;
    float fase = ofa2.x;
    vec2 c = centro;

    desenhaRaios(A, p, c, R, lim, lw, aa);
    onda(A, p, c, ondas0.xy, lw, aa); onda(A, p, c, ondas0.zw, lw, aa);
    onda(A, p, c, ondas1.xy, lw, aa); onda(A, p, c, ondas1.zw, lw, aa);
    onda(A, p, c, ondas2.xy, lw, aa); onda(A, p, c, ondas2.zw, lw, aa);
    onda(A, p, c, ondas3.xy, lw, aa); onda(A, p, c, ondas3.zw, lw, aa);

    // asas dos seres viventes, antes das rodas (só no alado: nAsas = 4)
    for (int i = 0; i < nAsas_(); i++) asa(A, p, asaA(i), asaB(i), float(i), lw, aa);

    // aros: traço principal e o fio de dentro, tom e largura pela profundidade
    float rmax = R * 1.25;
    bool perto = length(p - c) < rmax + 4.0;
    if (perto) {
        for (int i = 0; i < 4; i++) {
            Anel a = anel(i);
            float th = anelTheta(a, c, p);
            vec3 P = anelP(a, c, th, 1.0);
            float prof = (P.z + 1.0) * 0.5;
            float al = pa(0.25 + 0.6 * prof);
            sobre(A, traco(length(P.xy - p), 1.5 * (0.6 + 0.6 * prof) * lw, aa) * al);
            vec3 Pi = anelP(a, c, th, 0.94);
            sobre(A, traco(length(Pi.xy - p), 0.5 * (0.6 + 0.6 * prof) * lw, aa) * al);
        }
    }

    // fogo entre as rodas: sobe e desce (Ez 1:13); 24 vagas que renascem a
    // cada 1,5 s, acesas na proporção do pensar e das ferramentas
    float taxa = (16.0 * pensar + 5.0 * ferr) / 16.0;
    if (taxa > 0.002) {
        int nb = nBrasas_();
        for (int j = 0; j < nb; j++) {
            float fj = float(j);
            float T = 1.5;
            float s0 = t + hash(fj * 1.7 + 0.3) * T;
            float ciclo = floor(s0 / T);
            float idade = s0 - ciclo * T;
            float vida = 0.7 + 0.7 * hash2(vec2(fj, ciclo) + 0.17);
            if (idade > vida) continue;
            if (hash2(vec2(fj * 3.1, ciclo + 5.0)) > taxa) continue;
            float ang = TAU * hash2(vec2(fj, ciclo * 1.3 + 2.0));
            float r0 = 0.15 + 0.75 * hash2(vec2(fj * 0.7, ciclo + 9.0));
            vec2 b0 = vec2(cos(ang), sin(ang)) * r0;
            float vx = (hash2(vec2(fj, ciclo + 13.0)) - 0.5) * 0.3;
            float vy = -(0.5 + 0.6 * hash2(vec2(fj, ciclo + 17.0)));
            vec2 bp = b0 + vec2(vx * idade, vy * idade + 0.55 * idade * idade);
            vec2 px = c + bp * R;
            if (length(px - c) >= lim) continue;
            float f = idade / vida;
            float rad = max(0.6, 1.1 * lw * (1.0 - 0.5 * f));
            if (length(p - px) > rad + 2.0 * aa) continue;
            float al = (1.0 - f) * (0.55 + 0.45 * abs(ruido(t * 9.0, b0.x * 50.0)));
            sobre(A, cobre(length(p - px) - rad, aa) * pa(al));
        }
    }

    // relâmpagos entre os olhos dos aros (Ez 1:14)
    for (int r = 0; r < 2; r++) {
        vec4 sg = r == 0 ? rel0 : rel1;
        float al = r == 0 ? relInfo.x : relInfo.z;
        float sem = r == 0 ? relInfo.y : relInfo.w;
        if (al <= 0.0) continue;
        vec2 p0 = sg.xy, p1 = sg.zw;
        vec2 dd = p1 - p0;
        float dl = max(length(dd), 1e-3);
        vec2 nrm = vec2(-dd.y, dd.x) / dl;
        vec2 ant = p0;
        float dmin = 1e9;
        for (int j = 1; j <= 6; j++) {
            vec2 q = p1;
            if (j < 6) {
                float s = float(j) / 6.0;
                float o = (hash(sem * 17.0 + float(j)) * 2.0 - 1.0) * 0.14 * dl;
                q = p0 + dd * s + nrm * o;
            }
            dmin = min(dmin, segd(p, ant, q));
            ant = q;
        }
        sobre(A, traco(dmin, 3.0 * lw, aa) * pa(0.18 * al));
        sobre(A, traco(dmin, 1.2 * lw, aa) * pa(0.95 * al));
    }

    // olhos dos aros: os de trás primeiro; abrem em cascata ao despertar
    if (perto) {
        OlhoC hit[3];
        int nh = 0;
        int no = nOlhos_();
        for (int idx = 0; idx < no; idx++) {
            // anéis com 7, 8, 6 e 9 olhos: índices 0-6, 7-14, 15-20, 21-29
            int i = idx < 7 ? 0 : idx < 15 ? 1 : idx < 21 ? 2 : 3;
            int ini = i == 0 ? 0 : i == 1 ? 7 : i == 2 ? 15 : 21;
            int n = i == 0 ? 7 : i == 1 ? 8 : i == 2 ? 6 : 9;
            int kk = idx - ini;
            Anel a = anel(i);
            float th = float(kk) * TAU / float(n) + fase * 0.05 * float(i + 1);
            vec3 P = anelP(a, c, th, 1.0);
            float tm = R * 0.125 * (0.6 + 0.5 * (P.z + 1.0) / 2.0);
            vec2 dp = p - P.xy;
            float rm = tm * 1.3 + 2.0 * lw + 2.0 * aa;
            if (dot(dp, dp) > rm * rm) continue;
            float ab = pisca(float(i * 16 + kk)) * sat((d - 0.45 - 0.4 * float(idx) / 30.0) / 0.12);
            if (ab <= 0.02) continue;
            vec3 P2 = anelP(a, c, th + 0.05, 1.0);
            float ang = atan(P2.y - P.y, P2.x - P.x);
            if (nh < 3) {
                OlhoC o;
                o.pos = P.xy; o.ang = ang; o.tam = tm; o.ab = ab; o.z = P.z;
                o.alvo = olharPara(P.xy, ang, foco, float(i * 13 + kk * 7));
                o.alfa = pa(0.35 + 0.65 * (P.z + 1.0) / 2.0);
                hit[nh] = o;
                nh++;
            }
        }
        // ordena por profundidade (no máximo três)
        if (nh > 1 && hit[0].z > hit[1].z) { OlhoC x = hit[0]; hit[0] = hit[1]; hit[1] = x; }
        if (nh > 2 && hit[1].z > hit[2].z) { OlhoC x = hit[1]; hit[1] = hit[2]; hit[2] = x; }
        if (nh > 1 && hit[0].z > hit[1].z) { OlhoC x = hit[0]; hit[0] = hit[1]; hit[1] = x; }
        for (int k = 0; k < 3; k++) {
            if (k >= nh) break;
            olho(A, p, hit[k].pos, hit[k].ang, hit[k].tam, hit[k].ab, hit[k].alvo, hit[k].alfa, pupila, lw, aa);
        }
    }

    // núcleo: o olho grande
    float brilho = 0.08 + 0.10 * falar + 0.08 * pensar * (0.5 + 0.5 * sin(t * 6.0)) + 0.20 * clarao;
    sobre(A, cobre(length(p - c) - R * 0.34, aa) * pa(brilho));
    olho(A, p, c, 0.0, R * 0.32, ofa.w, nucleoDir, 1.0, pupila, lw, aa);
}
#endif

// ── asas ──

vec2 ossoP(float s, float L) {
    return cubica(vec2(0.0), vec2(0.25, -0.24) * L, vec2(0.65, -0.22) * L, vec2(1.0, -0.06) * L, s);
}

// Asa de penas em traço; wa = (raiz.x, raiz.y, elevação, L),
// wb = (lado, abertura, olhos, ocultar). Elevação 0 = horizontal para fora.
void asa(inout float A, vec2 p, vec4 wa, vec4 wb, float slot, float lw, float aa) {
    float L = wa.w;
    if (L < 0.5) return;
    float ang = wa.z, lado = wb.x, abert = wb.y;
    vec2 e1 = vec2(lado * cos(ang), -sin(ang));
    vec2 e2 = vec2(lado * sin(ang), cos(ang));
    vec2 dd = p - wa.xy;
    vec2 q = vec2(dot(dd, e1), dot(dd, e2));
    float mg = 3.0 * lw + 3.0 * aa;
    if (q.x < -0.25 * L - mg || q.x > 1.8 * L + mg || q.y < -0.5 * L - mg || q.y > 0.7 * L + mg) return;

    vec2 B[9]; vec2 C[9]; vec2 T[9]; float PH[9];
    for (int k = 0; k < 9; k++) {
        float f = float(k) / 8.0;
        vec2 b = ossoP(0.18 + 0.82 * f, L);
        float phi = (1.50 - 1.15 * pow(f, 0.8)) * (0.30 + 0.70 * abert);
        float ell = L * (0.34 + 0.36 * f) * (0.75 + 0.25 * abert);
        vec2 tp = b + ell * vec2(cos(phi), sin(phi));
        B[k] = b; T[k] = tp; PH[k] = phi;
        C[k] = (b + tp) * 0.5 + 0.10 * ell * vec2(-sin(phi), cos(phi));
    }

    if (wb.w > 0.5) {
        // a asa da frente esconde o que está atrás dela (o rosto, as chamas)
        vec2 poly[14];
        poly[0] = vec2(0.0);
        poly[1] = ossoP(0.25, L); poly[2] = ossoP(0.5, L); poly[3] = ossoP(0.75, L); poly[4] = ossoP(1.0, L);
        for (int k = 0; k < 9; k++) poly[5 + k] = T[8 - k];
        A *= 1.0 - 0.92 * cobre(sdPoly14(q, poly, 14), aa);
    }

    // osso (a bézier cúbica em 8 segmentos)
    float dmin = 1e9;
    vec2 ant = vec2(0.0);
    for (int k = 1; k <= 8; k++) {
        vec2 o = ossoP(float(k) / 8.0, L);
        dmin = min(dmin, segd(q, ant, o));
        ant = o;
    }
    sobre(A, traco(dmin, 1.5 * lw, aa) * pa(0.9));

    // penas: a cúbica do Cairo tem os dois controles no mesmo ponto; a
    // quadrática equivalente põe o controle 1,5x mais longe da corda
    dmin = 1e9;
    for (int k = 0; k < 9; k++) {
        vec2 m = (B[k] + T[k]) * 0.5;
        dmin = min(dmin, bezq(q, B[k], m + 1.5 * (C[k] - m), T[k]));
    }
    sobre(A, traco(dmin, 1.0 * lw, aa) * pa(0.55));

    // borda de fuga recortada entre as pontas das penas
    dmin = 1e9;
    for (int k = 0; k < 8; k++) {
        vec2 mu = (T[k] + T[k + 1]) * 0.5;
        dmin = min(dmin, bezq(q, T[k], mu + vec2(0.0, 0.06 * L), T[k + 1]));
    }
    sobre(A, traco(dmin, 0.8 * lw, aa) * pa(0.28));

    // coberteiras: penas curtas junto ao osso
    float phic = 1.25 * (0.4 + 0.6 * abert);
    vec2 dc = vec2(cos(phic), sin(phic)) * (L * 0.20);
    dmin = 1e9;
    for (int k = 0; k < 5; k++) {
        vec2 b = ossoP(0.12 + 0.16 * float(k), L);
        dmin = min(dmin, segd(q, b, b + dc));
    }
    sobre(A, traco(dmin, 0.8 * lw, aa) * pa(0.35));

    // olhos nas penas (Ez 10:12; Ap 4:8)
    int nOlhos = int(wb.z + 0.5);
    if (nOlhos > 0) {
        int passo = max(1, 7 / nOlhos);
        for (int j = 0; j < 3; j++) {
            if (j >= nOlhos) break;
            int k = 1 + j * passo;
            if (k >= 9) break;
            float s = 0.7;
            vec2 uv = (1.0 - s) * (1.0 - s) * B[k] + 2.0 * (1.0 - s) * s * C[k] + s * s * T[k];
            vec2 pos = wa.xy + uv.x * e1 + uv.y * e2;
            vec2 dir = e1 * cos(PH[k]) + e2 * sin(PH[k]);
            float a = atan(dir.y, dir.x);
            float ab = pisca(100.0 + slot * 10.0 + float(j)) * sat(abert * 1.4);
            olho(A, p, pos, a, L * 0.07, ab, olharPara(pos, a, 1.0, 0.0), pa(0.85), 1.0, lw, aa);
        }
    }
}

// ── criaturas em 3D (Shoggoth) ──
#if SKIN == 3

// Em 3D, por profundidade: massas, tentáculos e asas no espaço, projetados em
// perspectiva. Cada pixel junta as camadas que o cobrem, calcula a
// profundidade da superfície em cada uma, ordena e compõe de trás para a
// frente: o que está na frente esconde o traço do que está atrás.
// Coordenadas em unidades de R: x para a direita, y para baixo, z para quem olha.

const vec3 LUZ = vec3(-0.45, -0.70, 0.55);   // de cima, da esquerda, da frente

float smin(float a, float b, float k) {
    float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}

float difAng(float a, float b) { return mod(a - b + PI, TAU) - PI; }

float escala(float z) { return 4.0 / (4.0 - z); }

// o que está no fundo apaga: traço e reflexo mais fracos
float brilhoZ(float z) { return 0.40 + 0.60 * sat((z + 0.8) / 1.6); }

// difusa fraca e o reflexo molhado da pele
float sombreia(vec3 n, float bz) {
    vec3 l = normalize(LUZ);
    float dif = max(dot(n, l), 0.0);
    float esp = pow(max(reflect(-l, n).z, 0.0), 64.0);
    return min(pa((0.03 + 0.10 * dif) * bz) + pa(0.22 * esp * bz), 1.0);
}

// apaga o que está sob um olho deitado antes de pintá-lo por cima
void limpaOlho(inout float A, vec2 p, vec2 pos, float tam_, float ab, float aa) {
    vec2 eixo = vec2(tam_ * 1.12, tam_ * 0.58 * max(ab, 0.15));
    A *= 1.0 - cobre((length((p - pos) / eixo) - 1.0) * eixo.y, aa);
}

// boca de dentes no referencial q (x ao longo dela), meia largura w e meia
// altura h: devolve o vão, os dentes (duas fileiras que se encaixam) e a
// distância à borda, para o lábio
vec3 bocaDentes(vec2 q, float w, float h, float lt0, float sem, float aa) {
    if (w < 0.5 || abs(q.x) > w + 3.0 * aa || abs(q.y) > h + 3.0 * aa) return vec3(0.0, 0.0, 1e9);
    float hh = max(h, 0.4);
    float sd = (length(q / vec2(w, hh)) - 1.0) * hh;
    float vao = cobre(sd, aa);
    float tw = 2.0 * w / 7.0;
    float dente = 0.0;
    for (int r = 0; r < 2; r++) {
        float xs = q.x + w - (r == 1 ? 0.5 * tw : 0.0);
        float i = floor(xs / tw);
        if (i < 0.0 || i > (r == 1 ? 5.0 : 6.0)) continue;
        float u = xs - (i + 0.5) * tw;
        float xc = q.x - u;
        float borda = sqrt(max(1.0 - (xc / w) * (xc / w), 0.0));
        float ye = hh * borda;
        float v = r == 0 ? q.y + ye : ye - q.y;
        float lt = lt0 * (0.7 + 0.5 * hash(i + float(r) * 20.0 + sem)) * (0.4 + 0.6 * borda)
                 * (1.0 + 0.18 * est.y * sin(geo.z * 31.0 + i * 2.1 + sem));
        float sdT = max(max(-v, v - lt), abs(u) - tw * 0.45 * (1.0 - v / max(lt, 1e-3)));
        dente = max(dente, cobre(sdT, aa));
    }
    return vec3(vao, dente * vao, sd);
}

struct Camada { float z; float cob; float a; float e; float ir; };
Camada cams[20];
int ncam = 0;

// a íris acumulada desde a camada anterior vai junto com esta
void empilha(float z, float cob, float a, float e) {
    float ir = min(IR_, a);
    IR_ = 0.0;
    if (ncam >= 20 || cob <= 0.002) return;
    cams[ncam] = Camada(z, cob, a, e, ir);
    ncam++;
}

// raio relativo ao longo do tentáculo (sk de 0 a 1): 0 verme, grosso até
// perto da ponta; 1 chicote; 2 boca na ponta, que incha; 4 tentáculo de
// rosto, fino na ponta
float perfilRaio(int perfil, float sk) {
    return perfil == 2 ? 0.85 - 0.25 * sk + 0.55 * suave((sk - 0.70) / 0.30)
         : perfil == 1 ? pow(1.0 - sk, 1.2)
         : perfil == 4 ? 1.0 - 0.92 * pow(sk, 1.1)
         : 1.0 - 0.85 * pow(sk, 1.6);
}

struct Tubo {
    float sd;      // distância com sinal à superfície (px)
    float arco;    // comprimento de arco no ponto do eixo mais perto (px)
    float v;       // distância com sinal ao eixo, de lado (px)
    float z;       // profundidade do eixo ali (R)
    float raio;    // raio do tubo ali (px)
    vec2 tg;       // tangente na tela
    vec2 eixo;     // ponto do eixo mais perto
    float total;   // comprimento de arco total (px)
    vec3 ponta;    // ponta em 3D (R)
    vec2 pontaQ;   // ponta na tela
};

// Um tentáculo que parte de P com direção th0 (na tela, a partir de cima) e
// ph0 (para quem olha), comprimento L, curvatura e ondulação na fase fs;
// puxa curva a ponta (para o olhar). Perto da parede (centro xy, raio z, em
// R; raio 0 desliga) a ponta se curva para dentro.
Tubo tubo(vec2 p, vec2 c, float R, vec3 P, float th0, float ph0, float L, float grosso,
          float curva, float amp, float fs, float sem, float puxa, int perfil, vec3 parede) {
    Tubo T;
    T.sd = 1e9; T.arco = 0.0; T.v = 0.0; T.z = P.z; T.raio = 1.0;
    vec2 Q = c + P.xy * R * escala(P.z);
    T.tg = vec2(1.0, 0.0); T.eixo = Q;
    float rad = R * escala(P.z) * grosso * perfilRaio(perfil, 0.0);
    float arc = 0.0;
    for (int k = 1; k <= 14; k++) {
        float s = (float(k) - 0.5) / 14.0;
        float th = th0 + curva * s + amp * (0.25 + 0.75 * s) * sin(fs + s * 5.5 + sem) + puxa * s;
        if (parede.z > 0.0) {
            vec2 dw = P.xy - parede.xy;
            float rr = length(dw);
            if (rr > parede.z)
                th += difAng(atan(-dw.x, dw.y), th) * 0.7 * sat((rr - parede.z) / 0.3);
        }
        float ph = ph0 + 0.35 * s * cos(fs * 0.7 + s * 2.3 + sem * 1.3);
        vec3 Pn = P + vec3(sin(th) * cos(ph), -cos(th) * cos(ph), sin(ph)) * (L / 14.0);
        float scn = escala(Pn.z);
        vec2 Qn = c + Pn.xy * R * scn;
        float radn = R * scn * (grosso * perfilRaio(perfil, float(k) / 14.0) + 0.006);
        vec2 sg = Qn - Q;
        float sl = max(length(sg), 1e-4);
        float h = sat(dot(p - Q, sg) / (sl * sl));
        vec2 ax = Q + sg * h;
        float rh = mix(rad, radn, h);
        float sdk = length(p - ax) - rh;
        if (sdk < T.sd) {
            T.sd = sdk; T.arco = arc + h * sl; T.tg = sg / sl; T.eixo = ax; T.raio = rh;
            T.z = mix(P.z, Pn.z, h);
            T.v = T.tg.x * (p.y - ax.y) - T.tg.y * (p.x - ax.x);
        }
        arc += sl;
        P = Pn; Q = Qn; rad = radn;
    }
    T.total = arc; T.ponta = P; T.pontaQ = Q;
    return T;
}

// pele do tubo no pixel: profundidade da superfície, brilho pela profundidade,
// difusa, reflexo e os anéis que cruzam o tubo (passo 0 tira os anéis)
float peleTubo(Tubo T, float R, float lw, float aa, float passo, out float z, out float bz) {
    float nv = clamp(T.v / max(T.raio, 1e-3), -1.0, 1.0);
    float cz = sqrt(1.0 - nv * nv);
    z = T.z + cz * T.raio / (R * escala(T.z));
    bz = brilhoZ(z);
    float a = sombreia(vec3(vec2(-T.tg.y, T.tg.x) * nv, cz), bz);
    if (passo > 0.0) {
        float dAnel = abs(fract((T.arco + 0.35 * T.raio * cz) / passo + 0.5) - 0.5) * passo;
        sobre(a, traco(dAnel, 0.6 * lw, aa) * pa(0.16 * bz) * cz);
    }
    return a;
}

// ordena as camadas de trás para a frente e compõe
void compor(inout float A, inout float E) {
    for (int i = 1; i < 20; i++) {
        if (i >= ncam) break;
        Camada x = cams[i];
        int j = i - 1;
        while (j >= 0 && cams[j].z > x.z) { cams[j + 1] = cams[j]; j--; }
        cams[j + 1] = x;
    }
    float ir = IR_;
    for (int i = 0; i < 20; i++) {
        if (i >= ncam) break;
        A = cams[i].a + A * (1.0 - cams[i].cob);
        E = cams[i].e + E * (1.0 - cams[i].cob);
        ir = cams[i].ir + ir * (1.0 - cams[i].cob);
    }
    IR_ = ir;
}
#endif

// ── Shoggoth ──
#if SKIN == 3

void shoggoth(inout float A, inout float E, vec2 p, float aa) {
    float R = geo.x, t = geo.z, lw = geo.w;
    float d = est2.z;
    float fase = sho.x, alcance = sho.y, pulso = sho.w;
    float inclina = sho3.x, cresce = sho3.w;
    float abre = sho4.z;
    float pup = ofa.y;
    vec2 c = centro - vec2(0.0, 0.18 * R);
    fenda_ = 1.0;
    ncam = 0;

    onda(A, p, c, ondas0.xy, lw, aa); onda(A, p, c, ondas0.zw, lw, aa);
    onda(A, p, c, ondas1.xy, lw, aa); onda(A, p, c, ondas1.zw, lw, aa);
    onda(A, p, c, ondas2.xy, lw, aa); onda(A, p, c, ondas2.zw, lw, aa);
    onda(A, p, c, ondas3.xy, lw, aa); onda(A, p, c, ondas3.zw, lw, aa);

    // ── o monte: massas achatadas que se fundem; a profundidade é a da
    //    superfície da massa mais à frente no pixel ──
    int nm = int(lacos.x + 0.5);
    float sdM = 1e9, zM = -9.0, sdF = 1e9, zPerto = 0.0, sdPerto = 1e9;
    vec3 nM = vec3(0.0, -0.3, 0.95);
    vec2 csF = c;
    float rrF = 1.0, iF = 0.0;
    vec2 mascQ = c;
    float mascZ = 0.0, mascEsc = 1.0;
    for (int i = 0; i < 10; i++) {
        if (i >= nm) break;
        float fi = float(i);
        bool nucleo = i == 0;
        float fb = (fi - 1.0) / float(max(nm - 2, 1));
        vec3 C = nucleo ? vec3(0.04, 0.30, 0.0)
               : vec3(-0.70 + 1.40 * fb + 0.12 * (hash(fi * 3.1) - 0.5),
                      0.66 + 0.12 * (hash(fi * 5.7) - 0.5) - 0.08 * cos(fi * 1.9),
                      -0.50 + 0.65 * hash(fi * 7.3 + 0.4));
        C.xy += 0.03 * vec2(ruido(t * 0.4, fi * 2.0), ruido(t * 0.37, fi * 3.0));
        float r3 = (nucleo ? 0.42 : 0.15 + 0.10 * hash(fi * 9.1 + 0.2)) * (1.0 + 0.06 * pulso * sin(t * 9.0 + fi * 1.7));
        float sc = escala(C.z);
        vec2 cs = c + C.xy * R * sc;
        vec2 semi = (nucleo ? vec2(1.12, 0.95) : vec2(1.40, 0.72)) * r3 * R * sc;
        if (nucleo) {
            // a máscara fica na frente do núcleo, embaixo e um pouco à esquerda
            mascQ = cs + vec2(-0.10, 0.14) * R * sc;
            mascZ = C.z + r3 * 0.8;
            mascEsc = sc;
        }
        vec2 qn = (p - cs) / semi;
        float dn = length(qn);
        float sdi = (dn - 1.0) * semi.y;
        sdM = smin(sdM, sdi, 0.10 * R);
        if (dn < 1.0) {
            float zi = C.z + sqrt(1.0 - dn * dn) * r3 * 0.8;
            if (zi > zM) {
                zM = zi; sdF = sdi; csF = cs; rrF = r3 * R * sc; iF = fi;
                nM = normalize(vec3(qn.x * 0.7, qn.y * 1.3, sqrt(1.0 - dn * dn)));
            }
        }
        if (sdi < sdPerto) { sdPerto = sdi; zPerto = C.z; }
    }
    if (zM < -8.0) zM = zPerto;               // entre duas massas, na emenda
    if (sdM < 3.0 * lw + 3.0 * aa) {
        float cov = cobre(sdM, aa);
        float bz = brilhoZ(zM);
        float a = sombreia(nM, bz);
        // a borda da massa da frente marca onde ela passa sobre a de trás
        sobre(a, traco(abs(sdF), 0.9 * lw, aa) * pa(0.45 * bz) * step(sdF, 0.5 * lw));
        // olhos só na massa da frente: três no núcleo, em volta da máscara, e
        // um fora do centro em parte das outras (dois lado a lado viram uma cara)
        bool noNucleo = iF < 0.5;
        for (int e = 0; e < 3; e++) {
            float fe = iF * 3.0 + float(e);
            if (!noNucleo && (e > 0 || hash(fe * 8.3 + 0.1) > 0.65)) continue;
            vec2 off = noNucleo ? (e == 0 ? vec2(0.45, -0.45) : e == 1 ? vec2(-0.30, -0.62) : vec2(0.62, 0.22))
                                : vec2(sign(hash(fe * 4.1) - 0.5) * (0.35 + 0.35 * hash(fe * 3.9)), hash(fe * 6.3) * 0.5 - 0.45);
            vec2 pos = csF + off * rrF;
            float tm = rrF * (noNucleo ? 0.17 + 0.05 * float(e == 0) : 0.34 + 0.16 * hash(fe * 2.2));
            if (length(p - pos) > tm * 1.3 + 2.0 * lw + 2.0 * aa) continue;
            float ab = pisca(500.0 + fe) * sat((d - 0.55) / 0.15);
            if (ab <= 0.02) continue;
            limpaOlho(a, p, pos, tm, ab, aa);
            olho(a, p, pos, 0.0, tm, ab, olharPara(pos, 0.0, 1.0, fe), pa(bz), pup, lw, aa);
        }
        // a boca de verdade, atrás da máscara: aparece quando ela escorrega
        // e pela boca do sorriso
        if (noNucleo) {
            vec3 bd = bocaDentes(p - mascQ - vec2(0.0, 0.04 * R * mascEsc), 0.20 * R * mascEsc,
                                 (0.03 + 0.14 * abre) * R * mascEsc, 0.07 * R * mascEsc, 3.0, aa);
            a *= 1.0 - bd.x;
            sobre(a, bd.y * pa(0.95 * bz));
            sobre(a, traco(abs(bd.z), 1.0 * lw, aa) * pa(0.8 * bz));
        }
        // uma boca de lado numa das massas da base
        if (abs(iF - floor(float(nm) * 0.5)) < 0.5) {
            vec3 bd = bocaDentes(p - csF - vec2(0.15, 0.30) * rrF, 0.55 * rrF, (0.05 + 0.35 * abre) * rrF,
                                 0.20 * rrF, 11.0, aa);
            a *= 1.0 - bd.x;
            sobre(a, bd.y * pa(0.95 * bz));
            sobre(a, traco(abs(bd.z), 1.0 * lw, aa) * pa(0.8 * bz));
        }
        a *= cov;
        IR_ *= cov;
        float cont = traco(abs(sdM), 1.3 * lw, aa) * pa(0.9 * bz);
        sobre(a, cont);
        empilha(zM, max(cov, cont), a, cov * 0.92);
    }

    // ── tentáculos: saem do núcleo e da base para todo lado ──
    int nt = int(lacos.z + 0.5);
    for (int j = 0; j < 16; j++) {
        if (j >= nt) break;
        float fj = float(j);
        vec3 P;
        float th0, ph0, L, grosso, curva, amp;
        {
            float u = fj / max(float(nt) - 1.0, 1.0);
            th0 = -2.3 + 4.6 * u + 0.5 * (hash(fj * 3.7) - 0.5);
            float acima = 1.0 - min(abs(th0) / 2.4, 1.0);
            L = (0.85 + 0.75 * hash(fj * 5.3 + 0.9)) * (0.45 + 0.75 * acima);
            grosso = 0.06 + 0.11 * hash(fj * 8.9 + 0.6);
            curva = (hash(fj * 2.3 + 0.1) - 0.5) * 3.0;
            amp = 0.75;
            ph0 = (hash(fj * 6.1 + 0.5) - 0.5) * 0.7;
            P = vec3(0.55 * (hash(fj * 1.3 + 0.2) - 0.5) + 0.30 * sin(th0), 0.50 - 0.10 * cos(th0),
                     (hash(fj * 4.7 + 0.8) - 0.5) * 0.7);
        }
        L *= alcance * cresce;
        vec2 Q = c + P.xy * R * escala(P.z);
        if ((L < 0.02 || length(p - Q) > (L + 0.2) * 1.3 * R + 4.0 * aa)) continue;
        float sp = 0.7 + 0.6 * hash(fj * 1.9 + 0.4);
        // verme (grosso até perto da ponta), chicote (afina desde a raiz) ou
        // boca na ponta (incha e abre a mandíbula)
        float tipo = hash(fj * 3.3 + 0.7);
        bool bocaPonta = grosso > 0.11 && tipo < 0.55;
        bool chicote = !bocaPonta && tipo > 0.7;
        float sem = hash(fj * 7.1 + 0.3) * TAU;
        // ouvindo, a ponta se curva para quem fala
        vec2 g = olhar - Q;
        float dAng = clamp(difAng(atan(g.x, -g.y), th0), -1.2, 1.2);
        int perfil = bocaPonta ? 2 : chicote ? 1 : 0;
        // parede no centro da célula (o c subiu 0,18 R)
        Tubo T = tubo(p, c, R, P, th0, ph0, L, grosso, curva, amp, fase * sp, sem,
                      0.8 * inclina * dAng, perfil, vec3(0.0, 0.18, 1.1));
        float sdB = T.sd, arcB = T.arco, vB = T.v, radB = T.raio, arc = T.total;
        vec2 tgB = T.tg, eixoB = T.eixo;
        if (sdB > 0.6 * radB + 3.0 * lw + 3.0 * aa) continue;

        float cov = cobre(sdB, aa);
        float z, bz;
        float a = peleTubo(T, R, lw, aa, 0.18 * R, z, bz);
        vec2 ql = vec2(arcB, vB);
        float angT = atan(tgB.y, tgB.x);
        // a mandíbula na ponta: o vão sai do fim do tubo, com dentes nas bordas
        if (bocaPonta) {
            vec3 bd = bocaDentes(ql - vec2(arc, 0.0), 1.6 * radB, (0.40 + 0.55 * abre) * radB,
                                 0.50 * radB, fj * 5.0, aa);
            a *= 1.0 - bd.x;
            sobre(a, bd.y * pa(0.95 * bz));
            sobre(a, traco(abs(bd.z), 1.0 * lw, aa) * pa(0.8 * bz) * step(arcB, arc - 0.2 * radB));
        }
        // bocas de dentes no meio dos tentáculos grossos
        if (!bocaPonta && grosso > 0.10) {
            vec3 bd = bocaDentes(ql - vec2(arc * 0.40, 0.0), 1.9 * radB, (0.06 + 0.55 * abre) * radB,
                                 0.45 * radB, fj * 7.0, aa);
            a *= 1.0 - bd.x;
            sobre(a, bd.y * pa(0.95 * bz));
            sobre(a, traco(abs(bd.z), 1.0 * lw, aa) * pa(0.8 * bz));
        }
        a *= cov;
        IR_ *= cov;
        float cont = traco(abs(sdB), 1.2 * lw, aa) * pa(0.9 * bz);
        sobre(a, cont);
        // olhos grandes ao longo do corpo, deitados no tubo e saltando dele,
        // todos no cursor
        float cobOlho = 0.0;
        for (int e = 0; e < 3; e++) {
            float fe = fj * 3.0 + float(e);
            if (hash(fe * 1.7 + 0.3) > 0.72) continue;
            float tm = clamp(radB * 1.3, 0.05 * R, 0.15 * R);
            vec2 pe = vec2(arc * (0.24 + 0.27 * float(e) + 0.05 * hash(fe * 2.9)), (hash(fe * 5.1) - 0.5) * 0.3 * radB);
            if (length(ql - pe) > tm * 1.3 + 2.0 * lw + 2.0 * aa) continue;
            float ab = pisca(600.0 + fe) * sat((d - 0.55 - 0.3 * fj / 16.0) / 0.15);
            if (ab <= 0.02) continue;
            vec2 ei = vec2(tm * 1.12, tm * 0.58 * max(ab, 0.15));
            float ce = cobre((length((ql - pe) / ei) - 1.0) * ei.y, aa);
            a *= 1.0 - ce;
            IR_ *= 1.0 - ce;
            olho(a, ql, pe, 0.0, tm, ab, olharPara(eixoB, angT, 1.0, fe), pa(bz), pup, lw, aa);
            cobOlho = max(cobOlho, ce);
        }
        empilha(z, max(max(cov, cont), cobOlho), a, max(cov, cobOlho) * 0.92);
    }

    // ── a máscara sorridente no núcleo, grudada na carne ──
    float ma = sho2.w;
    if (ma > 0.01 && nm > 0) {
        vec2 m = mascQ + sho2.xy;
        float Rm = 0.27 * R * mascEsc;
        float ca = cos(sho2.z), sa = sin(sho2.z);
        vec2 dm = p - m;
        vec2 q = vec2(ca * dm.x + sa * dm.y, -sa * dm.x + ca * dm.y);
        float mg = Rm * 1.45 + 3.0 * lw + 3.0 * aa;
        if (dot(q, q) < mg * mg) {
            // disforme: contorno torto, maçã do rosto afundada de um lado e o
            // queixo caído, mais comprido que largo
            float tq = atan(q.y, q.x);
            float queixo = pow(max(sin(tq), 0.0), 3.0);
            float rq = Rm * (1.0 + 0.07 * sin(3.0 * tq + 0.7) + 0.05 * sin(5.0 * tq + 2.1)
                             + 0.22 * queixo * (0.8 + 0.2 * cos(tq * 2.0 + 0.6)) - 0.08 * exp(-pow((tq + 2.6) / 0.35, 2.0)));
            float disco = cobre((length(q / vec2(0.86, 1.0)) - rq) * 0.9, aa);
            // olhos vazados tortos: o esquerdo estreito e alto, o direito
            // grande, caído e inclinado
            vec2 oE = vec2(-0.33, -0.26) * Rm, oD = vec2(0.30, -0.14) * Rm;
            vec2 rE = vec2(0.10, 0.17) * Rm, rD = vec2(0.15, 0.22) * Rm;
            vec2 qd = q - oD;
            float cD = cos(0.45), sD = sin(0.45);
            qd = vec2(cD * qd.x + sD * qd.y, -sD * qd.x + cD * qd.y);
            float furo = max(cobre((length((q - oE) / rE) - 1.0) * rE.x, aa),
                             cobre((length(qd / rD) - 1.0) * rD.x, aa));
            // sorriso largo demais e torto: sobe mais de um lado, com o traço
            // engrossando e afinando
            vec2 sv = q - vec2(0.05, -0.02) * Rm;
            float th = atan(sv.y, sv.x);
            float rs = 0.60 * Rm * (1.0 + 0.07 * sin(4.0 * th + 1.0));
            float a0 = 0.06 * PI, a1 = 0.86 * PI;
            vec2 e0 = rs * vec2(cos(a0), sin(a0)), e1 = rs * vec2(cos(a1), sin(a1));
            float dArc = (th > a0 && th < a1) ? abs(length(sv) - rs) : min(length(sv - e0), length(sv - e1));
            furo = max(furo, cobre(dArc - (0.035 + 0.03 * sin(th * 3.0 + 0.5)) * Rm, aa));
            // falando, o sorriso abre num D e mostra os dentes da boca de trás
            if (sho.z > 0.01) {
                float yc = rs * mix(0.92, 0.35, sho.z);
                furo = max(furo, cobre(max(length(sv) - rs, yc - sv.y), aa));
            }
            // pelos furos dos olhos, os olhos acesos da coisa de trás seguem o cursor
            float iris = 0.0;
            for (int ld = 0; ld < 2; ld++) {
                vec2 oc = ld == 0 ? oE : oD;
                float k = ld == 0 ? 0.8 : 1.2;
                vec2 pos = m + vec2(ca * oc.x - sa * oc.y, sa * oc.x + ca * oc.y);
                vec2 pc = oc + olharPara(pos, sho2.z, 1.0, 0.0) * vec2(0.03, 0.07) * Rm * k;
                vec2 ri = vec2(0.10, 0.10 * max(pisca(300.0 + float(ld)), 0.05)) * Rm * k;
                vec2 rf = vec2(0.022 * pup * pup, 0.085) * Rm * k;
                float ir = cobre((length((q - pc) / ri) - 1.0) * ri.y, aa);
                iris = max(iris, ir * (1.0 - cobre((length((q - pc) / rf) - 1.0) * rf.x, aa)));
            }
            iris *= disco * furo;
            // a rachadura que desce da borda até o olho direito
            float dr = min(min(segd(q, vec2(0.22, -0.98) * Rm, vec2(0.12, -0.72) * Rm),
                               segd(q, vec2(0.12, -0.72) * Rm, vec2(0.25, -0.55) * Rm)),
                           min(segd(q, vec2(0.25, -0.55) * Rm, vec2(0.17, -0.38) * Rm),
                               segd(q, vec2(0.12, -0.72) * Rm, vec2(0.0, -0.63) * Rm)));
            float rach = traco(dr, 0.9 * lw, aa);
            float face = disco * (1.0 - furo);
            float a = face * (1.0 - rach) * pa(0.92);
            sobre(a, iris * pa(0.95));
            IR_ = (IR_ + iris * pa(0.95)) * ma;
            empilha(mascZ + 0.25, max(face, iris) * ma, a * ma, face * rach * 0.9 * ma);
        }
    }

    compor(A, E);
}
#endif

#ifndef SKIN
#define SKIN 0
#endif

void main() {
    vec2 p = qt_TexCoord0 * tam;
    float aa = max(fwidth(p.x), 1e-3);
    float A = 0.0, E = 0.0;
#if SKIN == 3
    shoggoth(A, E, p, aa);
#else
    ofanim(A, p, aa, SKIN == 1);
#endif
    fragColor = vec4(A, E, min(IR_, A), max(A, E)) * qt_Opacity;
}
