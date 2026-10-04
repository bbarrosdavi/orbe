#version 440
// Segundo passe das figuras e do anel: lê a máscara desenhada no primeiro
// passe (camada do item) e pinta a cor, a aberração cromática, as faixas
// arrancadas, os cacos e as linhas de varredura, sempre recortadas da figura
// e nunca do fundo. Atrás de tudo, a sombra opcional: degradê radial que
// some até zero na borda, sem degrau (o blur do niri é binário).
//
// Máscara dos avatares: canal r = cobertura do traço; g = massa escura (só o
// Shoggoth), pintada no tom do fundo do tema por baixo do traço. Máscara do anel: r = alfa,
// g = intensidade / 2 (ADD sobre área opaca passa de 1), b = só o quadro.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 tam;
    vec2 centro;
    vec4 cor;        // rgb, alfa da entrada/saída
    vec4 corA;       // aberração: cópia deslocada para a esquerda (rgb, alfa)
    vec4 corB;       // aberração: cópia deslocada para a direita
    vec4 glt;        // separação (px), rajada (0/1), semente, escala k
    vec4 geo2;       // R, lim, deslocamento das linhas de varredura, linhas ligadas
    vec4 sombra;     // raio, alfa no centro, -, ligada
    vec4 corSombra;  // rgb
    vec4 modo;       // 0 avatar | 1 anel; escala de tamanho do orbe
    vec4 banda0; vec4 banda1; vec4 banda2; vec4 banda3;   // anel: y0, altura, desloc., ligada
};
layout(binding = 1) uniform sampler2D source;

const float TAU = 6.283185307179586;

float sat(float v) { return clamp(v, 0.0, 1.0); }

float hash(float n) {
    n = fract(n * 0.1031);
    n *= n + 33.33;
    n *= n + n;
    return fract(n);
}

float aa_;   // px lógicos por px físico
float scan_; // fator das linhas de varredura nesta linha

vec2 masc(vec2 pos) {
    if (pos.x < 0.0 || pos.y < 0.0 || pos.x > tam.x || pos.y > tam.y) return vec2(0.0);
    return texture(source, pos / tam).rg;
}

vec3 masc3(vec2 pos) {
    if (pos.x < 0.0 || pos.y < 0.0 || pos.x > tam.x || pos.y > tam.y) return vec3(0.0);
    return texture(source, pos / tam).rgb;
}

// cobertura de uma faixa [a, b] no pixel de centro y (filtro de caixa)
float faixa(float y, float a, float b) {
    return sat((min(y + 0.5 * aa_, b) - max(y - 0.5 * aa_, a)) / aa_);
}

void main() {
    vec2 p = qt_TexCoord0 * tam;
    aa_ = max(fwidth(p.x), 1e-3);
    vec3 c = vec3(0.0);
    float a = 0.0;
    float env = cor.w;

    if (modo.x < 0.5) {
        // ── avatares ──
        scan_ = 1.0;
        if (geo2.w > 0.5) {
            // linhas de 1 px a cada 3, descendo: tiram 30% da figura onde passam
            float dd = mod(p.y - geo2.z, 3.0);
            float ov = faixa(dd, 0.0, 1.0) + faixa(dd, 3.0, 4.0);
            scan_ = 1.0 - 0.30 * sat(ov);
        }
        float sep = glt.x;
        if (corA.w > 0.0) {
            float mA = masc(p + vec2(sep, 0.0)).r * scan_;
            float mB = masc(p - vec2(sep, 0.0)).r * scan_;
            c += corA.rgb * corA.w * env * mA; a += corA.w * env * mA;
            c += corB.rgb * corB.w * env * mB; a += corB.w * env * mB;
        }
        float m0 = masc(p).r * scan_;
        c += cor.rgb * env * m0;
        a += env * m0;

        if (glt.y > 0.5) {
            float k = glt.w, s = glt.z;
            float R = geo2.x, lim = geo2.y;
            // faixas horizontais da figura arrancadas do lugar
            int nb = 3 + int(hash(s * 1.3) * 4.99);
            vec3 claro = min(cor.rgb + 0.3, vec3(1.0));
            for (int i = 0; i < 7; i++) {
                if (i >= nb) break;
                float fi = float(i) * 7.0 + s;
                float y0 = centro.y + (hash(fi + 0.1) * 2.0 - 1.0) * lim;
                float fh = (3.0 + 15.0 * hash(fi + 0.2)) * max(0.5, k);
                float cb = faixa(p.y, y0, y0 + fh);
                if (cb <= 0.0) continue;
                float sx = (hash(fi + 0.3) * 72.0 - 36.0) * k;
                float mb = masc(p - vec2(sx, 0.0)).r * scan_ * cb;
                c += claro * 0.9 * env * mb; a += 0.9 * env * mb;
            }
            // cacos soltos, só perto da figura
            int nc = 4 + int(hash(s * 2.9) * 8.99);
            for (int i = 0; i < 12; i++) {
                if (i >= nc) break;
                float fi = float(i) * 11.0 + s + 500.0;
                float ang = TAU * hash(fi + 0.1);
                float rr = (0.2 + 0.8 * hash(fi + 0.2)) * min(lim, R * 1.3);
                vec2 o = centro + vec2(cos(ang), sin(ang)) * rr;
                vec2 sz = vec2((4.0 + 24.0 * hash(fi + 0.3)) * max(0.5, k), 1.0 + hash(fi + 0.4));
                float cv = faixa(p.x, o.x, o.x + sz.x) * faixa(p.y, o.y, o.y + sz.y);
                float al = (0.2 + 0.4 * hash(fi + 0.5)) * env * cv;
                c += cor.rgb * al; a += al;
            }
        }
        // massa escura por baixo de tudo que é traço
        float e0 = masc(p).g * env;
        a = min(a, 1.0);
        c += corSombra.rgb * e0 * (1.0 - a);
        a += e0 * (1.0 - a);
    } else {
        // ── anel de energia ──
        // a entrada/saída já veio composta no primeiro passe
        vec3 m0 = masc3(p);
        c = cor.rgb * (2.0 * m0.g);
        a = m0.r;
        float k = glt.w;
        if (glt.x != 0.0 && k > 0.0) {
            // aberração: ciano de um lado, magenta do outro, em ADD
            float mA = masc3(p + vec2(glt.x * k, 0.0)).b;
            float mB = masc3(p - vec2(glt.x * k, 0.0)).b;
            c += corA.rgb * corA.w * k * env * mA; a += corA.w * k * env * mA;
            c += corB.rgb * corB.w * k * env * mB; a += corB.w * k * env * mB;
        }
        if (k > 0.0) {
            for (int i = 0; i < 4; i++) {
                vec4 b = i == 0 ? banda0 : i == 1 ? banda1 : i == 2 ? banda2 : banda3;
                if (b.w < 0.5) continue;
                float y0 = centro.y + b.x * modo.y;
                float cb = faixa(p.y, y0, y0 + b.y * modo.y);
                if (cb <= 0.0) continue;
                float mb = masc3(p - vec2(b.z * k * modo.y, 0.0)).b * cb;
                c += cor.rgb * 0.85 * k * env * mb; a += 0.85 * k * env * mb;
            }
        }
    }

    a = min(a, 1.0);
    c = min(c, vec3(1.0));

    if (sombra.w > 0.5 && sombra.x > 1.0) {
        // (1 - r²)²: cheia no meio, chega a zero na borda com inclinação zero
        float r = length(p - centro) / sombra.x;
        float k = max(1.0 - r * r, 0.0);
        float ga = sombra.y * k * k * env;
        c += corSombra.rgb * ga * (1.0 - a);
        a += ga * (1.0 - a);
    }

    fragColor = vec4(c, a) * qt_Opacity;
}
