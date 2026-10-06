#version 440
// Skins de imagem: a figura é a própria ilustração, recortada em camadas num
// atlas (uma célula por camada; R = traço, G = silhueta), e o shader só move
// as camadas: cada asa gira em volta da raiz e as íris andam para o olhar.
// Na pose desenhada (asas abertas, olhos no lugar, escala 1) a saída é o
// recorte, pixel a pixel. Formato de saída igual ao do figura.frag: r = traço,
// g = massa escura por baixo dele, que o pos.frag pinta no tom do fundo.
//
// Olho e Humana: uma célula só, deformada em volta de um polo (o olho, o
// miolo de cabeças). B do atlas diz quanto cada pixel se deforma (0 no miolo,
// 1 nas pontas dos raios e dos membros), tirado das camadas segmentadas: o
// miolo fica rígido e o que é ponta estica, gira e treme. O campo são 16
// molas em volta do polo, uma por setor, que a voz chuta a cada sílaba.
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
                     // olho e humana: giro da figura inteira, torção das pontas, escala extra, pupila (1 = como desenhada)
    vec4 img2;       // olho e humana: tremor das pontas, quanto o olho encara (0 = como desenhado), —, —
    vec4 campo0;     // as 16 molas em volta do polo: quanto cada setor estica, em fração do raio
    vec4 campo1;
    vec4 campo2;
    vec4 campo3;
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

#if IMG == 2
// Olho: recorte de 505 x 609 px, uma célula
const vec2 TAM = vec2(505.0, 609.0);
const float CELULA = 0.0;
const vec2 ATLAS = TAM;
const vec2 OLHO = vec2(260.0, 284.5);    // o centro do globo, no centro do item
const vec2 POLO = OLHO;                  // o halo se deforma em volta do olho
const float RIMG = 270.0;
const vec2 PUP = vec2(285.5, 279.6);     // a pupila desenhada
const float RP = 42.5;
const vec2 AB = vec2(250.0, 292.0);      // a abertura das pálpebras (elipse, um pouco por dentro)
const vec2 AR = vec2(92.0, 57.0);
#ifdef RELOGIO
const vec4 CAIXA[1] = vec4[1](vec4(-6.0, -6.0, 511.0, 615.0));
#endif
#endif

#if IMG == 3
// Humana: recorte de 517 x 492 px (o JPG a 60%), uma célula
const vec2 TAM = vec2(517.0, 492.0);
const float CELULA = 0.0;
const vec2 ATLAS = TAM;
const vec2 OLHO = vec2(258.5, 246.0);    // o meio da figura, no centro do item
const vec2 POLO = vec2(246.7, 190.3);    // o miolo de cabeças: os corpos saem dele
const float RIMG = 255.0;
#ifdef RELOGIO
const vec4 CAIXA[1] = vec4[1](vec4(-6.0, -6.0, 523.0, 498.0));
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

#if IMG >= 2
// quanto o pixel se deforma (B do atlas), num nível fixo e grosso: o campo é
// suave, e a leitura sem derivadas não mexe no filtro da leitura do traço
float flexivel(vec2 q) {
    return textureLod(arte, clamp(q, vec2(0.5), TAM - 0.5) / ATLAS, 2.0).b;
}

// as 16 molas, interpoladas em volta do polo (Catmull-Rom, fechada)
float campo(float a) {
    float c[16] = float[16](campo0.x, campo0.y, campo0.z, campo0.w, campo1.x, campo1.y, campo1.z, campo1.w,
                            campo2.x, campo2.y, campo2.z, campo2.w, campo3.x, campo3.y, campo3.z, campo3.w);
    float x = fract(a / TAU) * 16.0;
    int i = int(x);
    float f = x - float(i);
    float p0 = c[(i + 15) % 16], p1 = c[i % 16], p2 = c[(i + 1) % 16], p3 = c[(i + 2) % 16];
    return p1 + 0.5 * f * (p2 - p0 + f * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3 + f * (3.0 * (p1 - p2) + p3 - p0)));
}

// de onde vem o pixel q: a figura gira inteira (giro), e as pontas se torcem,
// tremem e esticam pelas molas, na medida do B; o miolo (B = 0) não sai do lugar
vec2 deformar(vec2 q) {
    vec2 d = girar(q - POLO, -img.x);
    float w = flexivel(POLO + d);
    float r = max(length(d), 1e-3);
    float a = atan(d.y, d.x);
    float t = geo.z;
    a -= w * (img.y * r / RIMG + img2.x * sin(a * 7.0 + t * 37.0) * sin(a * 3.0 - t * 23.0));
    float rs = r / (1.0 + w * campo(a));
    return POLO + rs * vec2(cos(a), sin(a));
}
#endif

#if IMG == 2
// a pupila anda para o olhar e dilata; o branco do olho entre ela e as
// pálpebras estica junto, e a borda da abertura fica no lugar. Na pose
// desenhada (desl = 0, dil = 1) devolve q
vec2 pupila(vec2 q, vec2 desl, float dil) {
    vec2 e = (q - AB) / AR;
    if (dot(e, e) >= 1.0) return q;
    // a pupila não passa das pálpebras: o centro fica na elipse encolhida do raio dela
    vec2 o = (PUP - AB), dd = desl;
    vec2 ar = AR - RP - 1.5;
    vec2 oa = o / ar, da = dd / ar;
    float A = dot(da, da), B = dot(oa, da), C = dot(oa, oa) - 1.0;
    float tt = A > 1e-6 ? clamp((-B + sqrt(max(B * B - A * C, 0.0))) / A, 0.0, 1.0) : 1.0;
    vec2 pm = PUP + dd * tt;
    vec2 v = q - pm;
    float r = length(v);
    vec2 u = r > 1e-4 ? v / r : vec2(1.0, 0.0);
    // até a borda da abertura, na direção u
    vec2 om = (pm - AB) / AR, du = u / AR;
    float A2 = dot(du, du), B2 = dot(om, du), C2 = dot(om, om) - 1.0;
    float lam = (-B2 + sqrt(max(B2 * B2 - A2 * C2, 0.0))) / A2;
    // dilatada, a pupila também não passa da borda mais próxima
    float lmin = 1e9;
    for (int k = 0; k < 8; k++) {
        vec2 uk = vec2(cos(float(k) * 0.785398), sin(float(k) * 0.785398)) / AR;
        float Ak = dot(uk, uk), Bk = dot(om, uk);
        lmin = min(lmin, (-Bk + sqrt(max(Bk * Bk - Ak * C2, 0.0))) / Ak);
    }
    float rp = min(RP * dil, max(RP, lmin - 1.5));
    if (r <= rp) return PUP + u * (r * RP / rp);
    float al = clamp((r - rp) / max(lam - rp, 1e-3), 0.0, 1.0);
    return mix(PUP + u * RP, pm + u * lam, al);
}
#endif

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

#if IMG == 2
    // o olhar desloca a pupila (mais para os lados: a abertura é larga e baixa),
    // e encarar a leva ao meio da abertura, olhando para quem fala
    vec2 qs = pupila(deformar(q), dg * vec2(40.0, 14.0) + img2.y * (AB - PUP), img.w);
    camada(0.0, qs);
#endif
#if IMG == 3
    camada(0.0, deformar(q));
#endif

    float A = min(accB, accA);
    float E = accA > A ? min((accA - A) / max(1.0 - A, 1e-4), 1.0) : 0.0;
    fragColor = vec4(A, E, 0.0, max(A, E)) * qt_Opacity;
}
