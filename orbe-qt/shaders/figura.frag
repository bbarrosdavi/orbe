#version 440
// Figuras do orbe (Ophanim, Ophanim com asas, Seraphim) desenhadas inteiras na
// GPU por distância: cada traço do desenho em Cairo (hermes_voice_avatares.py)
// vira uma função de distância, e a cobertura sai da distância e da largura do
// traço. A saída é a máscara branca da figura no canal vermelho; a cor, a
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
    vec4 est2;       // voz, mic, desperto, skin (0 ofanim, 1 alado, 2 serafim)
    vec4 ofa;        // foco, pupila, clarão, abertura do olho central
    vec4 ofa2;       // fase, desperto suavizado, nº de asas, —
    vec4 raios;      // quantidade, giro, comprimento, alfa
    vec4 a0u; vec4 a0v; vec4 a1u; vec4 a1v;   // anéis: u.xyz + raio, v.xyz
    vec4 a2u; vec4 a2v; vec4 a3u; vec4 a3v;
    vec4 ondas0; vec4 ondas1; vec4 ondas2; vec4 ondas3;   // (raio, alfa) x 2
    vec4 rel0; vec4 rel1; vec4 relInfo;   // relâmpagos: p0, p1; (alfa, semente) x 2
    vec4 w0a; vec4 w0b; vec4 w1a; vec4 w1b; vec4 w2a; vec4 w2b;   // asas: raiz, ângulo, L;
    vec4 w3a; vec4 w3b; vec4 w4a; vec4 w4b; vec4 w5a; vec4 w5b;   //   lado, abertura, olhos, ocultar
    vec4 sera;       // fogo, trisagion, abertura do rosto, brasa
    vec4 sera2;      // ângulo da brasa, arranjo dos olhos (0 a 4), —, —
    vec4 lacos;      // nº de olhos (30), vagas de brasa (24), vagas de fumaça (10), asas
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

void sobre(inout float A, float a) { A = a + A * (1.0 - a); }

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
        sobre(A, dentro * cobre(length(q - ic) - tam_ * 0.42, aa) * sat(alfa * 0.85));
        vec2 pc = vec2(alvo.x * w * 0.40, alvo.y * h * 0.40);
        A *= 1.0 - dentro * cobre(length(q - pc) - tam_ * 0.17 * pup, aa);
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

#if SKIN != 2
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

// ── Seraphim ──
#if SKIN == 2

void chamas(inout float A, vec2 p, vec2 c, float R, float fogo, float lw, float aa) {
    float t = geo.z;
    float base = c.y + 0.38 * R;
    float topo = base - 1.1 * R * max(fogo, 0.4) - 4.0;
    if (p.y < base + 4.0 && p.y > topo && abs(p.x - c.x) < 0.75 * R) {
        for (int j = 0; j < 11; j++) {
            float off = (float(j) - 5.0) / 5.0;
            float x0 = c.x + off * 0.16 * R;
            float h = R * (0.72 + 0.30 * (0.5 + 0.5 * ruido(t * 3.0, float(j) * 3.1))) * fogo * (1.0 - 0.45 * off * off);
            float sway = ruido(t * 2.3, float(j) * 1.9) * 0.10 * R + off * 0.22 * R;
            float wb = R * (0.06 + 0.03 * (1.0 - abs(off)));
            float tx = x0 + sway, ty = base - h;
            float m = 2.0 * lw + 2.0 * aa;
            if (p.x < min(x0 - wb, tx) - m || p.x > max(x0 + wb, tx) + m || p.y < ty - m || p.y > base + m) continue;
            vec2 a0 = vec2(x0 - wb, base), a1 = vec2(x0 - wb, base - h * 0.45);
            vec2 a2 = vec2(tx - wb * 0.2 + sway * 0.3, ty + h * 0.35), pt = vec2(tx, ty);
            vec2 b1 = vec2(tx + wb * 0.2 + sway * 0.3, ty + h * 0.35), b2 = vec2(x0 + wb, base - h * 0.45);
            vec2 b3 = vec2(x0 + wb, base);
            vec2 poly[14];
            for (int k = 0; k < 7; k++) poly[k] = cubica(a0, a1, a2, pt, float(k) / 6.0);
            for (int k = 1; k < 7; k++) poly[6 + k] = cubica(pt, b1, b2, b3, float(k) / 6.0);
            float sd = sdPoly14(p, poly, 13);
            sobre(A, cobre(sd, aa) * pa(0.07));
            sobre(A, traco(abs(sd), 0.9 * lw, aa) * pa(0.35 + 0.25 * (1.0 - abs(off))));
        }
    }
    sobre(A, cobre(length(p - c) - R * 0.34, aa) * pa(0.14 + 0.30 * sera.y));
}

void serafim(inout float A, vec2 p, float aa) {
    float R = geo.x, lim = geo.y, t = geo.z, lw = geo.w;
    float pensar = est.y;
    vec2 c = centro;

    desenhaRaios(A, p, c, R, lim, lw, aa);
    // ondas da voz, as mesmas do Ophanim, atrás de tudo
    onda(A, p, c, ondas0.xy, lw, aa); onda(A, p, c, ondas0.zw, lw, aa);
    onda(A, p, c, ondas1.xy, lw, aa); onda(A, p, c, ondas1.zw, lw, aa);
    onda(A, p, c, ondas2.xy, lw, aa); onda(A, p, c, ondas2.zw, lw, aa);
    onda(A, p, c, ondas3.xy, lw, aa); onda(A, p, c, ondas3.zw, lw, aa);
    // com duas voava: atrás do corpo
    int na = nAsas_();
    for (int i = 0; i < na; i++) { if (i >= 2) break; asa(A, p, asaA(i), asaB(i), float(i), lw, aa); }
    chamas(A, p, c, R, sera.x, lw, aa);

    // olhos (sera2.y): 0 só o de cima, 1 só o do meio, 2 os dois,
    // 3 só o do meio na vertical, 4 os dois com o do meio na vertical
    int modoOlhos = int(sera2.y + 0.5);
    bool olhoCima = modoOlhos == 0 || modoOlhos == 2 || modoOlhos == 4;
    bool olhoMeio = modoOlhos != 0;
    float angMeio = modoOlhos >= 3 ? 0.5 * PI : 0.0;

    // o rosto (olho de cima): só aparece quando as asas da frente se abrem para ouvir
    float abre = sera.z;
    if (olhoCima && abre > 0.05) {
        vec2 e = c + vec2(0.0, -0.20 * R);
        vec2 dv = olhar - e;
        float dl = length(dv);
        olho(A, p, e, 0.0, R * 0.21, abre * pisca(77.0), dl > 1e-4 ? dv / dl : vec2(1.0, 0.0),
             1.0, 1.0 + 0.5 * est2.y, lw, aa);
    }

    // com duas cobria os pés e com duas o rosto: na frente, escondendo
    for (int i = 2; i < na; i++) asa(A, p, asaA(i), asaB(i), float(i), lw, aa);

    // olho do meio, sempre à vista: na frente das asas, com o fundo limpo atrás
    if (olhoMeio) {
        // o vertical é maior e fica no centro exato; o horizontal desce um
        // pouco para dar respiro ao de cima
        float tam_ = R * (angMeio > 0.0 ? 0.30 : 0.22);
        float de = ofa2.y;
        vec2 m = c + vec2(0.0, (angMeio > 0.0 ? 0.0 : 0.07) * R);
        float ca = cos(angMeio), sa = sin(angMeio);
        vec2 dm = p - m;
        vec2 dq = vec2(ca * dm.x + sa * dm.y, -sa * dm.x + ca * dm.y) / vec2(tam_ * 1.08, tam_ * 0.52);
        A *= 1.0 - cobre((length(dq) - 1.0) * tam_ * 0.52, aa) * de;
        olho(A, p, m, angMeio, tam_, pisca(78.0) * de, olharPara(m, angMeio, 1.0, 0.0),
             1.0, 1.0 + 0.5 * est2.y, lw, aa);
    }

    // "a casa se encheu de fumaça" (Is 6:4): 10 vagas que renascem a cada 2,9 s
    float taxa = 3.5 * pensar / (10.0 / 2.9);
    if (taxa > 0.002) {
        int nf = nFumaca_();
        for (int j = 0; j < nf; j++) {
            float fj = float(j);
            float T = 2.9;
            float s0 = t + hash(fj * 2.3 + 0.9) * T;
            float ciclo = floor(s0 / T);
            float idade = s0 - ciclo * T;
            float vida = 2.0 + 0.8 * hash2(vec2(fj, ciclo) + 0.4);
            if (idade > vida) continue;
            if (hash2(vec2(fj * 5.3, ciclo + 3.0)) > taxa) continue;
            float x0 = -0.35 + 0.7 * hash2(vec2(fj, ciclo + 7.0));
            float sem = 50.0 * hash2(vec2(fj, ciclo + 11.0));
            float f = idade / vida;
            vec2 pp = vec2(c.x + x0 * R + ruido(t * 0.7, sem) * 0.25 * R * f, c.y - 0.55 * R - f * 0.9 * R);
            if (length(pp - c) + 0.15 * R >= lim) continue;
            float s = 0.15 * R * (1.0 + f);
            if (length(p - pp) > s * 1.4 + 3.0 * lw) continue;
            vec2 k0 = vec2(pp.x - s, pp.y), k1 = vec2(pp.x - s * 0.3, pp.y - s * 0.8);
            vec2 k2 = vec2(pp.x + s * 0.3, pp.y + s * 0.8), k3 = vec2(pp.x + s, pp.y);
            float dmin = 1e9;
            vec2 ant = k0;
            for (int k = 1; k <= 6; k++) {
                vec2 o = cubica(k0, k1, k2, k3, float(k) / 6.0);
                dmin = min(dmin, segd(p, ant, o));
                ant = o;
            }
            sobre(A, traco(dmin, (0.8 + 2.5 * f) * lw, aa) * pa(0.20 * sin(PI * f)));
        }
    }

    // a brasa tirada do altar (Is 6:6), circulando nas ferramentas
    float brasa = sera.w;
    if (brasa > 0.03) {
        for (int j = 0; j < 7; j++) {
            float a = sera2.x - float(j) * 0.12;
            vec2 b = c + vec2(cos(a) * 1.05 * R, sin(a) * 0.55 * R);
            float dl = length(p - b);
            if (j == 0) sobre(A, cobre(dl - 0.11 * R, aa) * pa(0.22 * brasa));
            sobre(A, cobre(dl - max(0.6, 0.05 * R * (1.0 - float(j) / 8.0)), aa) * pa(brasa * (1.0 - float(j) / 7.0)));
        }
    }
}
#endif

#ifndef SKIN
#define SKIN 0
#endif

void main() {
    vec2 p = qt_TexCoord0 * tam;
    float aa = max(fwidth(p.x), 1e-3);
    float A = 0.0;
#if SKIN == 2
    serafim(A, p, aa);
#else
    ofanim(A, p, aa, SKIN == 1);
#endif
    fragColor = vec4(A, 0.0, 0.0, A) * qt_Opacity;
}
