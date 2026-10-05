#version 440
// Skins de imagem: a figura é a própria ilustração, recortada em camadas num
// atlas (uma célula por camada; R = traço, G = silhueta), e o shader só move
// as camadas: cada asa gira em volta da raiz e as íris andam para o olhar.
// Na pose desenhada (asas abertas, olhos no lugar, escala 1) a saída é o
// recorte, pixel a pixel. Formato de saída igual ao do figura.frag: r = traço,
// g = massa escura por baixo dele, que o pos.frag pinta no tom do fundo.
//
// Uma variante por imagem (-DIMG=n no build.sh).

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 tam;        // tamanho do item, px lógicos
    vec2 centro;     // onde fica o ponto OLHO da imagem
    vec2 olhar;      // para onde os olhos olham
    vec4 geo;        // R (já com o desdobrar), lim, t, peso
    vec4 img;        // gravura: abertura das asas (1 = como desenhadas), batida (fração da dobra), escala extra, —
};
layout(binding = 1) uniform sampler2D arte;

#if IMG == 1
// Seraphim (gravura): recorte de 392 x 444 px, células de 408 px no atlas
const vec2 TAM = vec2(392.0, 444.0);
const float CELULA = 408.0;
const vec2 ATLAS = vec2(2856.0, 444.0);
const vec2 OLHO = vec2(192.0, 220.0);    // vai no centro do item
const float RIMG = 222.0;                // R da figura, em px da imagem
#ifdef RELOGIO
// onde cada camada tem desenho no recorte (x0, y0, x1, y1, em px da imagem),
// com 6 px de folga para o filtro: fora da caixa a leitura dá zero e a camada
// não muda o pixel
const vec4 CAIXA[7] = vec4[7](
    vec4(-6.0, -5.0, 197.0, 206.0), vec4(196.0, -5.0, 392.0, 206.0),
    vec4(-6.0, 90.0, 151.0, 449.0), vec4(240.0, 119.0, 388.0, 396.0),
    vec4(58.0, 231.0, 197.0, 441.0), vec4(196.0, 230.0, 317.0, 446.0),
    vec4(99.0, 48.0, 291.0, 401.0));
#endif
#endif

const float TAU = 6.283185307179586;
const float PI = 3.141592653589793;

float hash2(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float sat01(float v) { return clamp(v, 0.0, 1.0); }

float accB = 0.0;   // traço acumulado (pré-multiplicado)
float accA = 0.0;   // cobertura acumulada
float kRed = 0.0;   // quanto a figura está reduzida (0 a 1:1, 1 no tamanho do orbe)
#ifdef RELOGIO
float lod0 = 0.0;   // o nível do mipmap da figura, o mesmo em todo pixel (ver main)
#endif

// leitura do atlas. Reduzida: 4 amostras dentro do pixel, cada uma com metade
// da pegada (filtro mais justo que o trilinear do mipmap, perto de uma redução
// Lanczos da imagem), e um realce leve do traço contra a média da vizinhança
// (um nível de mipmap mais grosso). Forte demais, o realce estoura a hachura
// densa em branco; 0.4 fica só um pouco mais nítido que o Lanczos. A 1:1 as 4
// amostras caem no centro do texel e o realce zera: a cópia segue exata
const float REALCE = 0.4;
vec4 ler(vec2 uv, float realce) {
#ifdef RELOGIO
    // No relógio, uma leitura trilinear um pouco mais fina que a pegada (viés
    // -0,5), com o mesmo realce: as 4 com textureGrad custavam mais que o
    // Ophanim na GPU dele, e a máscara descia de resolução, o que borra mais
    // que o filtro. O nível vem de lod0, não das derivadas, para a camada
    // que não cobre o pixel poder ser pulada (camada).
    vec4 v = textureLod(arte, uv, lod0 - 0.5);
    if (realce > 0.0) {
        float vb = textureLod(arte, uv, lod0 + 1.5).r;
        v.r = sat01(v.r + REALCE * realce * kRed * (v.r - vb));
    }
    return v;
#else
    vec2 dx = dFdx(uv) * 0.25, dy = dFdy(uv) * 0.25;
    vec2 ox = dx * kRed, oy = dy * kRed;
    vec4 v = 0.5 * (0.5 * (textureGrad(arte, uv - ox - oy, 2.0 * dx, 2.0 * dy) + textureGrad(arte, uv + ox - oy, 2.0 * dx, 2.0 * dy))
                  + 0.5 * (textureGrad(arte, uv - ox + oy, 2.0 * dx, 2.0 * dy) + textureGrad(arte, uv + ox + oy, 2.0 * dx, 2.0 * dy)));
    float vb = texture(arte, uv, 1.5).r;
    v.r = sat01(v.r + REALCE * realce * kRed * (v.r - vb));
    return v;
#endif
}

vec2 girar(vec2 v, float a) {
    float c = cos(a), s = sin(a);
    return vec2(c * v.x - s * v.y, s * v.x + c * v.y);
}

// leva a íris até desl: o miolo anda inteiro e a borda do olho fica no lugar
vec2 iris(vec2 q, vec2 e, vec2 raio, vec2 desl) {
    float d = length((q - e) / raio);
    return q - desl * (1.0 - smoothstep(0.55, 1.0, d));
}

// uma camada por cima das anteriores; a amostra é sempre lida (fora de
// desvio), para as derivadas do ler() valerem. No relógio a leitura não usa
// derivadas (lod0), e a camada sem desenho no pixel é pulada
void camada(float cel, vec2 q) {
#ifdef RELOGIO
    vec4 cx = CAIXA[int(cel)];
    if (q.x < cx.x || q.y < cx.y || q.x > cx.z || q.y > cx.w) return;
#endif
    vec2 qc = clamp(q, vec2(0.5), TAM - 0.5);
    vec2 rg = ler((qc + vec2(cel * CELULA, 0.0)) / ATLAS, 1.0).rg;
    rg *= step(0.0, q.x) * step(0.0, q.y) * step(q.x, TAM.x) * step(q.y, TAM.y);
    accB = rg.r + accB * (1.0 - rg.g);
    accA = rg.g + accA * (1.0 - rg.g);
}

// leitura de uma célula no ponto q da imagem (zero fora do recorte); só a
// célula 0 é traço, as outras são pesos e não ganham realce
vec4 celula(float cel, vec2 q) {
    vec2 qc = clamp(q, vec2(0.5), TAM - 0.5);
    vec4 v = ler((qc + vec2(cel * CELULA, 0.0)) / ATLAS, 1.0 - step(0.5, cel));
    return v * step(0.0, q.x) * step(0.0, q.y) * step(q.x, TAM.x) * step(q.y, TAM.y);
}

// asa girada de ang em volta da raiz, com o olho dela seguindo o olhar
void asa(float cel, vec2 q, vec2 raiz, float ang, vec2 olho, vec2 raio, vec2 desl) {
    vec2 ql = raiz + girar(q - raiz, -ang);
    camada(cel, iris(ql, olho, raio, desl));
}

void main() {
    vec2 p = qt_TexCoord0 * tam;
    float s = geo.x / RIMG * (1.0 + img.z);
    vec2 q = (p - centro) / s + OLHO;
    kRed = 1.0 - smoothstep(0.35, 0.8, s);
#ifdef RELOGIO
    // a pegada de um pixel no atlas é a mesma na figura toda (o giro das asas
    // não a muda): o nível que o trilinear acharia pelas derivadas, uma vez só
    lod0 = log2(max(length(dFdx(q)), length(dFdy(q))) * float(textureSize(arte, 0).x) / ATLAS.x);
#endif
    // direção do olhar, saturada: longe, a íris vai até a borda
    vec2 g = olhar - centro;
    vec2 dg = g / (length(g) + geo.x * 0.6);
    float dobra = 1.0 - img.x + img.y;    // fração da dobra aplicada a cada asa

#if IMG == 1
    // de trás para a frente: asas do meio, de cima, de baixo; o núcleo por cima
    // (as raízes das asas passam por baixo da estrela)
    asa(2.0, q, vec2(145.0, 214.0), -0.25 * dobra, vec2(74.0, 151.0), vec2(11.0, 6.0), dg * vec2(3.0, 0.8));
    asa(3.0, q, vec2(246.0, 214.0), 0.25 * dobra, vec2(308.0, 150.0), vec2(11.0, 6.0), dg * vec2(3.0, 0.8));
    asa(0.0, q, vec2(175.0, 184.0), 0.35 * dobra, vec2(162.0, 118.0), vec2(9.0, 9.0), dg * 3.0);
    asa(1.0, q, vec2(216.0, 184.0), -0.35 * dobra, vec2(219.0, 117.0), vec2(9.0, 9.0), dg * 3.0);
    asa(4.0, q, vec2(175.0, 254.0), -0.35 * dobra, vec2(157.0, 313.0), vec2(8.0, 9.0), dg * 2.5);
    asa(5.0, q, vec2(216.0, 254.0), 0.35 * dobra, vec2(225.0, 313.0), vec2(8.0, 9.0), dg * 2.5);
    camada(6.0, iris(q, vec2(192.5, 220.5), vec2(32.0, 17.5), dg * vec2(9.0, 1.5)));
#endif

    float A = min(accB, accA);
    float E = accA > A ? min((accA - A) / max(1.0 - A, 1e-4), 1.0) : 0.0;
    fragColor = vec4(A, E, 0.0, max(A, E)) * qt_Opacity;
}
