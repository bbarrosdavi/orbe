#version 440
// Anel de energia: o rotoscope do energy-circle-loader deformado pela voz.
//
// Os 62 quadros moram num atlas 5x5 de células 256x256, um quadro por canal
// de cor (quadro f: canal f%3, célula f/3). Sem canal alfa de propósito: o
// Qt Quick pré-multiplica textura com alfa, e o quarto quadro multiplicaria
// os outros três. A deformação polar do hermes_voice_orb.py (36 fatias, cada
// uma com escala radial própria) vira um campo contínuo entre as fatias; o
// glow é o mesmo quadro lido num mipmap mais baixo, que já vem borrado.
//
// A composição segue a ordem do cairo: glow em ADD, quadro em OVER e, por
// chama, halo em ADD seguido do preenchimento em OVER. O halo de uma chama
// clareia a chama anterior onde as duas se cruzam, como no GTK; por isso a
// saída guarda alfa e intensidade separados.
//
// Saída: r = alfa final, g = intensidade da cor / 2 (passa de 1 onde há ADD
// sobre área já opaca), b = cobertura só do quadro (fonte do glitch). A cor
// é do pos.frag.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 tam;
    vec2 centro;
    vec4 geo;        // escala do quadro (scb), rotação, quadro atual, escala do glow (sg)
    vec4 extra;      // glow_k, campo plano (0/1), escala do orbe, R_LIM em px
    vec4 gl;         // rajada: fatia inicial, nº de fatias, torção (rad), —
    vec4 campo0; vec4 campo1; vec4 campo2; vec4 campo3; vec4 campo4;
    vec4 campo5; vec4 campo6; vec4 campo7; vec4 campo8;   // 36 escalas por fatia
    vec4 lingua0; vec4 lingua1; vec4 lingua2; vec4 lingua3; vec4 lingua4;
    vec4 lingua5; vec4 lingua6; vec4 lingua7; vec4 lingua8; vec4 lingua9;   // ângulo, rb, ponta, largura
    vec4 gota0; vec4 gota1; vec4 gota2; vec4 gota3; vec4 gota4; vec4 gota5; vec4 gota6;  // x, y, e, —
    vec4 tempo;      // t, alfa da entrada/saída, —, —
};
layout(binding = 1) uniform sampler2D atlas;
#ifdef RELOGIO
// no relógio o laço das línguas vai até a última ativa (+1, da CPU): com um
// limite que o compilador não conhece, ele não desenrola o laço nem predica as
// dez línguas em todo pixel (no Adreno 504 isso custava 6x o anel parado)
uniform float nLingua;
#endif

const float TAU = 6.283185307179586;
const vec2 F_C = vec2(128.0, 134.0);   // centro do anel no quadro 256x256
const float N_W = 36.0;

float sat(float v) { return clamp(v, 0.0, 1.0); }

float campo(int i) {
    int j = i / 4, k = i - 4 * (i / 4);
    vec4 c = j == 0 ? campo0 : j == 1 ? campo1 : j == 2 ? campo2 : j == 3 ? campo3 : j == 4 ? campo4
           : j == 5 ? campo5 : j == 6 ? campo6 : j == 7 ? campo7 : campo8;
    return k == 0 ? c.x : k == 1 ? c.y : k == 2 ? c.z : c.w;
}

vec4 lingua(int j) {
    return j == 0 ? lingua0 : j == 1 ? lingua1 : j == 2 ? lingua2 : j == 3 ? lingua3 : j == 4 ? lingua4
         : j == 5 ? lingua5 : j == 6 ? lingua6 : j == 7 ? lingua7 : j == 8 ? lingua8 : lingua9;
}

vec4 gota(int j) {
    return j == 0 ? gota0 : j == 1 ? gota1 : j == 2 ? gota2 : j == 3 ? gota3 : j == 4 ? gota4 : j == 5 ? gota5 : gota6;
}

// lê o quadro f no ponto q (px do quadro 256x256); lod > 0 = glow
float quadro(float f, vec2 q, float lod) {
    if (q.x < 0.5 || q.y < 0.5 || q.x > 255.5 || q.y > 255.5) return 0.0;
    int fi = int(f + 0.5);
    int cel = fi / 3, ch = fi - 3 * (fi / 3);
    vec2 o = vec2(float(cel - 5 * (cel / 5)), float(cel / 5)) * 256.0;
    vec3 v = textureLod(atlas, (o + q) / 1280.0, lod).rgb;
    return ch == 0 ? v.r : ch == 1 ? v.g : v.b;
}

// ADD do cairo: a intensidade soma sem teto, o alfa satura em 1
void adiciona(inout float A, inout float I, float v) {
    I += v;
    A = min(1.0, A + v);
}

// OVER do cairo com a mesma cor
void cobre(inout float A, inout float I, float v) {
    I = v + I * (1.0 - v);
    A = v + A * (1.0 - v);
}

vec2 gira(vec2 v, float a) {
    float c = cos(a), s = sin(a);
    return vec2(c * v.x - s * v.y, s * v.x + c * v.y);
}

float segd(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = sat(dot(pa, ba) / max(dot(ba, ba), 1e-8));
    return length(pa - ba * h);
}

// catmull-rom fechada pelos 4 pontos, como polígono de 16 lados
float sdLingua(vec2 p, vec2 P[4], out float dbord) {
    vec2 v[16];
    for (int i = 0; i < 4; i++) {
        vec2 p0 = P[(i + 3) - 4 * ((i + 3) / 4)], p1 = P[i];
        vec2 p2 = P[(i + 1) - 4 * ((i + 1) / 4)], p3 = P[(i + 2) - 4 * ((i + 2) / 4)];
        vec2 c1 = p1 + (p2 - p0) / 6.0, c2 = p2 - (p3 - p1) / 6.0;
        for (int k = 0; k < 4; k++) {
            float s = float(k) / 4.0, u = 1.0 - s;
            v[i * 4 + k] = u * u * u * p1 + 3.0 * u * u * s * c1 + 3.0 * u * s * s * c2 + s * s * s * p2;
        }
    }
    float d = 1e9, sg = 1.0;
    int j = 15;
    for (int i = 0; i < 16; i++) {
        vec2 e = v[j] - v[i], w = p - v[i];
        vec2 b = w - e * sat(dot(w, e) / max(dot(e, e), 1e-8));
        d = min(d, dot(b, b));
        bvec3 cond = bvec3(p.y >= v[i].y, p.y < v[j].y, e.x * w.y > e.y * w.x);
        if (all(cond) || all(not(cond))) sg *= -1.0;
        j = i;
    }
    dbord = sqrt(d);
    return sg * dbord;
}

void main() {
    vec2 p = qt_TexCoord0 * tam;
    float aa = max(fwidth(p.x), 1e-3);
    float scb = geo.x, rot = geo.y, f = geo.z, sg = geo.w;
    float glowk = extra.x, esc = extra.z;
    float t = tempo.x, env = tempo.y;
    // no referencial do anel (girando com ele)
    vec2 l = gira(p - centro, -rot);
    float A = 0.0, I = 0.0;   // alfa e intensidade, compostos na ordem do cairo

    // glow num blit só: borrado por natureza, segue apenas o bounce global
    adiciona(A, I, 0.30 * glowk * quadro(f, l / (scb * sg) + F_C, 2.6));

    // warp polar: escala radial por fatia, interpolada entre os centros
    float phi = atan(l.y, l.x);
    if (phi < 0.0) phi += TAU;
    float s;
    if (extra.y > 0.5) {
        s = campo(0);
    } else {
        float x = phi / TAU * N_W - 0.5;
        float x0 = floor(x);
        float fr = x - x0;
        int i0 = int(mod(x0, N_W)), i1 = int(mod(x0 + 1.0, N_W));
        s = mix(campo(i0), campo(i1), fr);
    }
    vec2 lq = l;
    if (gl.y > 0.0) {
        // torção do setor rasgado: gira o desenho dentro da cunha
        float fat = floor(phi / TAU * N_W);
        float ini = mod(fat - gl.x, N_W);
        if (ini < gl.y) lq = gira(l, -gl.z);
    }
    float fq = env * quadro(f, lq / (scb * s) + F_C, 0.0);
    cobre(A, I, fq);

    // línguas de chama na borda, nos ângulos das molas
#ifdef RELOGIO
    for (int j = 0; j < int(nLingua); j++) {
#else
    for (int j = 0; j < 10; j++) {
#endif
        vec4 L = lingua(j);
        if (L.z <= 0.0) continue;
        float a = L.x, rb = L.y, tip = L.z, wj = L.w;
        float lean = 0.10 * sin(t * 2.3 + float(j));
        vec2 dir = vec2(cos(a), sin(a));
        // corte rápido: longe do eixo da língua
        float ext = tip + 6.0 * esc;
        if (dot(l, dir) < rb * 0.6 || length(l) > ext) continue;
        vec2 P[4];
        P[0] = vec2(cos(a - wj * 0.85), sin(a - wj * 0.85)) * rb * 0.98;
        P[1] = vec2(cos(a + lean), sin(a + lean)) * tip;
        P[2] = vec2(cos(a + wj * 0.85), sin(a + wj * 0.85)) * rb * 0.98;
        P[3] = dir * rb * 0.90;
        float db;
        float sd = sdLingua(l, P, db);
        adiciona(A, I, 0.16 * glowk * sat((2.5 * esc - db) / aa + 0.5));   // halo de 5 px
        cobre(A, I, env * sat(0.5 - sd / aa));
    }

    // gotas
    for (int j = 0; j < 7; j++) {
        vec4 g = gota(j);
        float e = g.z;
        if (e <= 0.04) continue;
        float dl = length(l - g.xy);
        float r = (1.5 + 3.0 * e) * esc;
        adiciona(A, I, 0.12 * e * env * sat((2.0 * r - dl) / aa + 0.5));
        cobre(A, I, 0.9 * e * env * sat((r - dl) / aa + 0.5));
    }

    fragColor = vec4(A, min(I, 2.0) * 0.5, fq, A) * qt_Opacity;
}
