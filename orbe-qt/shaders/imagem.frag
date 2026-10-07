#version 440
// Skins de imagem: a figura é a própria ilustração, recortada em camadas num
// atlas (uma célula por camada; R = traço, G = silhueta), e o shader só move
// as camadas: cada asa gira em volta da raiz e as íris andam para o olhar.
// Na pose desenhada (asas abertas, olhos no lugar, escala 1) a saída é o
// recorte, pixel a pixel. Formato de saída igual ao do figura.frag: r = traço,
// g = massa escura por baixo dele, que o pos.frag pinta no tom do fundo.
//
// Olho e Humana: peças recortadas, como num Live2D. B do atlas é o id da
// peça de cada pixel (0 = o miolo, que não sai do lugar). Cada peça é uma
// cadeia articulada (os membros: base, joelho ou cotovelo, tornozelo ou punho,
// ponta; os raios: raiz, meio, ponta) ou um corpo que gira em volta do
// pescoço, levando os membros que saem dele. Para cada pixel, a peça é lida
// no lugar de repouso pela transformação inversa da cadeia, e só vale onde o
// id do atlas é o dela: é corte, não deformação da imagem. Os ângulos de cada
// junta vêm das molas da Figura (m0..m47), com a física lá.
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
    vec4 img;        // gravura: base das asas do meio, cotovelo delas, escala extra, base das de cima (rad)
                     // olho: giro da coroa de raios, —, escala extra, pupila (1 = como desenhada)
    vec4 img2;       // olho: —, quanto encara (0 = como desenhado), quanto as pálpebras fecham (0 a 1), —
                     // gravura: joelho das asas de cima, joelho das de baixo, base das de baixo, — (rad)
    // as juntas das peças: na Humana, mi = (base, joelho, tornozelo, —) do membro i
    // e m(NL+b).x o giro do corpo b; no Olho, mi = (raiz, meio, quanto estica, —) do raio i
    vec4 m0;
    vec4 m1;
    vec4 m2;
    vec4 m3;
    vec4 m4;
    vec4 m5;
    vec4 m6;
    vec4 m7;
    vec4 m8;
    vec4 m9;
    vec4 m10;
    vec4 m11;
    vec4 m12;
    vec4 m13;
    vec4 m14;
    vec4 m15;
    vec4 m16;
    vec4 m17;
    vec4 m18;
    vec4 m19;
    vec4 m20;
    vec4 m21;
    vec4 m22;
    vec4 m23;
    vec4 m24;
    vec4 m25;
    vec4 m26;
    vec4 m27;
    vec4 m28;
    vec4 m29;
    vec4 m30;
    vec4 m31;
    vec4 m32;
    vec4 m33;
    vec4 m34;
    vec4 m35;
    vec4 m36;
    vec4 m37;
    vec4 m38;
    vec4 m39;
    vec4 m40;
    vec4 m41;
    vec4 m42;
    vec4 m43;
    vec4 m44;
    vec4 m45;
    vec4 m46;
    vec4 m47;
};
layout(binding = 1) uniform sampler2D arte;
#if IMG >= 2 && defined(RELOGIO)
// no relógio, as transformações das peças num vetor de uniforms, que a Adreno
// 504 indexa direto; montadas num vetor local no main (vec4 M[48] = ..., o
// caminho do Qt, que não passa vetor de uniforms) elas iam para a memória a
// cada pixel, uns 115 ms por quadro só nisso
uniform vec4 Mu[48];
// e os senos e cossenos delas, feitos uma vez por quadro no app: o giro do corpo
// pai de cada membro (27 por pixel, antes até do teste da caixa) e as juntas
// das cadeias custavam um terço do quadro em sin/cos. Mc[i], membro i: (cos,
// sin) de A0 e de A1; Mc[NL + b], corpo b: (cos, sin) do giro; Md[i], membro
// i: (cos, sin) de A2 (A0 = a.x, A1 = A0 + a.y, A2 = A1 + a.z, como na cadeia)
uniform vec4 Mc[48];
uniform vec4 Md[48];
#endif

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
    vec4(-6.0, -5.0, 197.0, 208.0), vec4(194.0, -5.0, 392.0, 207.0),
    vec4(-6.0, 90.0, 147.0, 449.0), vec4(244.0, 119.0, 388.0, 396.0),
    vec4(58.0, 231.0, 197.0, 441.0), vec4(194.0, 230.0, 317.0, 446.0),
    vec4(99.0, 48.0, 291.0, 401.0));
#endif
// As articulações (em px da imagem, centro do texel i em i). Asas do meio: a
// base (raiz, junto do olho do centro) e o cotovelo (a ponta de cima, onde
// estão dobradas); o peso do cotovelo de cada pixel (0 no contorno em C e no
// sovaco, 1 longe deles) está gravado no B do atlas. Asas de cima e de baixo:
// a base e o joelho (o olho delas), uma dobradiça perpendicular ao eixo
// raiz-joelho com o olho rígido. Nas bases, o giro cresce a partir da raiz
// (leque), para a junção não abrir fresta.
#endif

#if IMG == 2
// Olho (Paranoia): recorte de 535 x 609 px, uma célula. B: 0 o globo (com o
// branco do olho preenchido por baixo da íris), 1 a coroa de raios inteira
// (todas as camadas, sem o céu), 250 o disco preto da íris, guardado num
// canto vazio do recorte para andar sem rastro
const vec2 TAM = vec2(535.0, 609.0);
const float CELULA = 0.0;
const vec2 ATLAS = TAM;
const vec2 OLHO = vec2(290.0, 284.5);    // o centro do globo, no centro do item
const float RIMG = 270.0;
const vec2 PUP = vec2(315.5, 279.6);     // o disco preto desenhado
const float RP = 42.5;
const float RI = 44.5;                   // o disco com a borda escura dele
const vec2 DISCO = vec2(47.5, 561.5);    // onde o disco está guardado
const vec2 AB = vec2(280.0, 292.0);      // a abertura das pálpebras (elipse, um pouco por dentro)
const vec2 AR = vec2(92.0, 57.0);
const float RAIZ = 118.0;                // onde os raios saem do globo
#ifdef RELOGIO
const vec4 CAIXA[1] = vec4[1](vec4(-6.0, -6.0, 541.0, 615.0));
#endif
#endif

#if IMG == 3
// Humana: recorte de 517 x 492 px (o JPG a 60%), uma célula
const vec2 TAM = vec2(517.0, 492.0);
const float CELULA = 0.0;
const vec2 ATLAS = TAM;
const vec2 OLHO = vec2(258.5, 246.0);    // o meio da figura, no centro do item
const float RIMG = 255.0;
const int NL = 27;      // membros: cadeias base, joelho ou cotovelo, tornozelo ou punho, ponta
const int NB = 8;       // corpos: giram em volta do pescoço (PIVO), levando os membros que saem deles
const int NH = 19;      // cabeças (rosto e cabelo): olham para o cursor, girando em volta do queixo
const vec2 JUNTA[108] = vec2[108](
    vec2(312.0, 62.0), vec2(314.0, 40.0), vec2(328.0, 15.0), vec2(328.0, 7.0),
    vec2(240.0, 98.0), vec2(228.0, 57.0), vec2(226.0, 27.0), vec2(226.0, 15.0),
    vec2(201.0, 105.0), vec2(187.0, 76.0), vec2(172.0, 35.0), vec2(166.0, 24.0),
    vec2(280.0, 80.0), vec2(267.0, 56.0), vec2(266.0, 44.0), vec2(266.0, 38.0),
    vec2(131.0, 69.0), vec2(122.0, 65.0), vec2(111.0, 53.0), vec2(109.0, 50.0),
    vec2(328.0, 94.0), vec2(346.0, 76.0), vec2(355.0, 58.0), vec2(358.0, 52.0),
    vec2(382.0, 109.0), vec2(398.0, 93.0), vec2(425.0, 80.0), vec2(430.0, 74.0),
    vec2(352.0, 107.0), vec2(352.0, 96.0), vec2(352.0, 88.0), vec2(352.0, 85.0),
    vec2(423.0, 140.0), vec2(439.0, 126.0), vec2(451.0, 112.0), vec2(456.0, 107.0),
    vec2(149.0, 142.0), vec2(133.0, 126.0), vec2(127.0, 124.0), vec2(123.0, 122.0),
    vec2(116.0, 166.0), vec2(86.0, 148.0), vec2(48.0, 129.0), vec2(36.0, 123.0),
    vec2(423.0, 140.0), vec2(453.0, 149.0), vec2(463.0, 152.0), vec2(469.0, 152.0),
    vec2(101.0, 206.0), vec2(46.0, 183.0), vec2(24.0, 184.0), vec2(11.0, 189.0),
    vec2(445.0, 212.0), vec2(461.0, 196.0), vec2(479.0, 196.0), vec2(485.0, 194.0),
    vec2(77.0, 234.0), vec2(28.0, 230.0), vec2(15.0, 239.0), vec2(6.0, 246.0),
    vec2(448.0, 270.0), vec2(464.0, 284.0), vec2(496.0, 294.0), vec2(504.0, 298.0),
    vec2(71.0, 293.0), vec2(32.0, 320.0), vec2(21.0, 325.0), vec2(12.0, 330.0),
    vec2(80.0, 305.0), vec2(52.0, 333.0), vec2(47.0, 342.0), vec2(42.0, 348.0),
    vec2(440.0, 336.0), vec2(473.0, 369.0), vec2(487.0, 371.0), vec2(497.0, 373.0),
    vec2(136.0, 344.0), vec2(110.0, 370.0), vec2(109.0, 378.0), vec2(111.0, 384.0),
    vec2(80.0, 360.0), vec2(77.0, 382.0), vec2(69.0, 400.0), vec2(66.0, 406.0),
    vec2(162.0, 418.0), vec2(147.0, 434.0), vec2(148.0, 447.0), vec2(146.0, 452.0),
    vec2(365.0, 427.0), vec2(374.0, 437.0), vec2(378.0, 455.0), vec2(381.0, 459.0),
    vec2(363.0, 427.0), vec2(353.0, 442.0), vec2(356.0, 465.0), vec2(359.0, 471.0),
    vec2(180.0, 429.0), vec2(187.0, 443.0), vec2(180.0, 469.0), vec2(179.0, 476.0),
    vec2(225.0, 441.0), vec2(225.0, 460.0), vec2(224.0, 472.0), vec2(223.0, 477.0),
    vec2(294.0, 413.0), vec2(308.0, 464.0), vec2(307.0, 475.0), vec2(302.0, 485.0));
const vec4 CAIXA_M[27] = vec4[27](
    vec4(245.0, -43.0, 382.0, 105.0), vec4(151.0, -58.0, 309.0, 161.0), vec4(91.0, -54.0, 268.0, 170.0), vec4(220.0, -6.0, 322.0, 113.0), vec4(79.0, 20.0, 152.0, 91.0), vec4(291.0, 3.0, 406.0, 132.0), vec4(339.0, 20.0, 485.0, 153.0), vec4(352.0, 107.0, 352.0, 107.0), vec4(390.0, 64.0, 499.0, 174.0), vec4(87.0, 87.0, 173.0, 166.0), vec4(-41.0, 46.0, 183.0, 234.0), vec4(389.0, 103.0, 516.0, 199.0), vec4(-70.0, 101.0, 172.0, 279.0), vec4(412.0, 149.0, 528.0, 246.0), vec4(-56.0, 152.0, 133.0, 310.0), vec4(402.0, 223.0, 563.0, 357.0), vec4(-49.0, 243.0, 122.0, 392.0), vec4(-8.0, 264.0, 122.0, 400.0), vec4(389.0, 285.0, 557.0, 435.0), vec4(70.0, 308.0, 173.0, 434.0), vec4(22.0, 326.0, 126.0, 452.0), vec4(100.0, 390.0, 192.0, 492.0), vec4(337.0, 401.0, 417.0, 495.0), vec4(303.0, 393.0, 404.0, 516.0), vec4(134.0, 394.0, 238.0, 524.0), vec4(187.0, 416.0, 264.0, 514.0), vec4(230.0, 359.0, 383.0, 547.0));
const int PAI[27] = int[27](6, -1, 5, 6, 5, 2, 2, 2, 3, 5, -1, 3, 4, -1, -1, 1, 4, 4, 1, -1, 7, 0, -1, -1, 0, -1, -1);
const vec2 PIVO[8] = vec2[8](vec2(238.0, 225.0), vec2(289.0, 218.0), vec2(279.0, 151.0), vec2(304.0, 183.0), vec2(163.0, 213.0), vec2(216.0, 157.0), vec2(277.0, 99.0), vec2(208.0, 215.0));
const vec4 CAIXA_C[8] = vec4[8](
    vec4(143.0, 194.0, 310.0, 457.0), vec4(259.0, 171.0, 497.0, 357.0), vec4(257.0, 66.0, 408.0, 190.0), vec4(282.0, 104.0, 454.0, 221.0), vec4(20.0, 182.0, 187.0, 321.0), vec4(114.0, 38.0, 252.0, 179.0), vec4(262.0, 46.0, 321.0, 112.0), vec4(42.0, 181.0, 241.0, 386.0));
const vec2 QUEIXO[19] = vec2[19](vec2(247.5, 199.0), vec2(228.2, 166.0), vec2(207.5, 211.0), vec2(281.0, 168.0), vec2(201.6, 187.0), vec2(270.4, 228.0), vec2(222.7, 228.0), vec2(245.3, 163.0), vec2(246.0, 233.0), vec2(287.8, 215.0), vec2(231.6, 197.0), vec2(293.4, 173.0), vec2(266.2, 201.0), vec2(231.5, 177.0), vec2(282.8, 189.0), vec2(268.5, 177.0), vec2(216.8, 183.0), vec2(250.8, 178.0), vec2(265.1, 163.0));
const vec4 CAIXA_H[19] = vec4[19](
    vec4(229.0, 168.0, 267.0, 208.0), vec4(212.0, 142.0, 245.0, 175.0), vec4(185.0, 175.0, 232.0, 220.0), vec4(266.0, 146.0, 297.0, 177.0), vec4(187.0, 165.0, 217.0, 196.0), vec4(251.0, 190.0, 290.0, 237.0), vec4(203.0, 188.0, 243.0, 237.0), vec4(228.0, 137.0, 265.0, 172.0), vec4(221.0, 191.0, 269.0, 242.0), vec4(272.0, 186.0, 306.0, 224.0), vec4(216.0, 168.0, 249.0, 206.0), vec4(280.0, 154.0, 308.0, 182.0), vec4(248.0, 168.0, 286.0, 210.0), vec4(216.0, 155.0, 249.0, 186.0), vec4(268.0, 162.0, 299.0, 198.0), vec4(252.0, 154.0, 286.0, 186.0), vec4(202.0, 159.0, 232.0, 192.0), vec4(230.0, 148.0, 271.0, 187.0), vec4(248.0, 137.0, 285.0, 172.0));
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

#if IMG == 1
// a mesma camada, só onde m (sempre lida, pelas derivadas do ler())
void camadaM(float cel, vec2 q, float m) {
#ifdef RELOGIO
    vec4 cx = CAIXA[int(cel)];
    if (m <= 0.0 || q.x < cx.x || q.y < cx.y || q.x > cx.z || q.y > cx.w) return;
#endif
    vec2 qc = clamp(q, vec2(0.5), TAM - 0.5);
    vec2 rg = ler((qc + vec2(cel * CELULA, 0.0)) / ATLAS, 1.0).rg * m;
    rg *= step(0.0, q.x) * step(0.0, q.y) * step(q.x, TAM.x) * step(q.y, TAM.y);
    accB = rg.r + accB * (1.0 - rg.g);
    accA = rg.g + accA * (1.0 - rg.g);
}

float suave01(float t) {
    t = clamp(t, 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

// o peso do cotovelo gravado no B da célula, no ponto p da imagem
float pesoCotovelo(float cel, vec2 p) {
    vec2 qc = clamp(p + 0.5, vec2(0.5), TAM - 0.5);
    return textureLod(arte, (qc + vec2(cel * CELULA, 0.0)) / ATLAS, 0.0).b;
}

// asa do meio: o ponto de repouso que, girado na base (leque a partir da raiz
// r) e no cotovelo e (peso do atlas), cai em p. Ponto fixo amortecido, 10
// passos (o protótipo aprovado; sem amortecer, oscila)
vec2 repousoMeio(vec2 p, vec2 r, vec2 e, float lado, float cel, float base, float cot) {
    vec2 s = p;
    for (int k = 0; k < 10; k++) {
        float wb = suave01((length(s - r) - 25.0) / 35.0);
        vec2 qb = r + girar(p - r, -base * lado * wb);
        vec2 n = e + girar(qb - e, -cot * lado * pesoCotovelo(cel, s));
        s += 0.7 * (n - s);
    }
    return s;
}

// asa de cima ou de baixo: base em leque a partir da raiz r e dobradiça no
// joelho j (o olho, rígido)
vec2 repousoVert(vec2 p, vec2 r, vec2 j, float sent, float base, float joe) {
    vec2 u = normalize(j - r);
    vec2 s = p;
    for (int k = 0; k < 10; k++) {
        float wb = suave01((length(s - r) - 20.0) / 30.0);
        vec2 qb = r + girar(p - r, -base * sent * wb);
        float w = suave01(dot(s - j, u) / 30.0) * clamp((length(s - j) - 8.0) / 7.0, 0.0, 1.0);
        vec2 n = j + girar(qb - j, -joe * sent * w);
        s += 0.7 * (n - s);
    }
    return s;
}

// o espinho da estrela que cruza a asa do meio (yc, x da ponta fina, x junto
// da estrela): meia altura em x
float meiaEspinho(float x, vec3 E) {
    float f = clamp((x - E.y) / (E.z - E.y), 0.0, 1.0);
    return f > 0.0 ? 0.8 + 2.2 * f : 0.0;
}

// o espinho fica parado: onde a leitura da asa em movimento cai nele, espelha
// para a hachura vizinha
vec2 espelhaEspinho(vec2 s, vec3 E) {
    float hw = meiaEspinho(s.x, E);
    float d = s.y - E.x;
    float novo = E.x + (d >= -1e-6 ? 1.0 : -1.0) * (2.0 * hw - abs(d));
    return vec2(s.x, abs(d) < hw ? novo : s.y);
}
#endif

#if IMG >= 2
// o gradiente do recorte por pixel, tirado uma vez fora dos desvios (as peças
// giram, o que não muda o tamanho da pegada): as leituras dentro dos laços
// não podem usar derivadas implícitas
vec2 gX = vec2(0.0), gY = vec2(0.0);

vec4 lerPeca(vec2 uv) {
#ifdef RELOGIO
    return ler(uv, 1.0);
#else
    vec2 dx = gX * 0.25, dy = gY * 0.25;
    vec2 ox = dx * kRed, oy = dy * kRed;
    vec4 v = 0.5 * (0.5 * (textureGrad(arte, uv - ox - oy, 2.0 * dx, 2.0 * dy) + textureGrad(arte, uv + ox - oy, 2.0 * dx, 2.0 * dy))
                  + 0.5 * (textureGrad(arte, uv - ox + oy, 2.0 * dx, 2.0 * dy) + textureGrad(arte, uv + ox + oy, 2.0 * dx, 2.0 * dy)));
    float vb = textureGrad(arte, uv, gX * 2.83, gY * 2.83).r;
    v.r = sat01(v.r + REALCE * kRed * (v.r - vb));
    return v;
#endif
}

// o id da peça no ponto p do recorte (B do atlas): lido no centro do texel,
// no nível 0 (gradiente zero), o filtro devolve o texel exato
int pecaEm(vec2 p) {
    vec2 t = clamp(floor(p), vec2(0.0), TAM - 1.0) + 0.5;
    return int(textureGrad(arte, t / ATLAS, vec2(0.0), vec2(0.0)).b * 255.0 + 0.5);
}

// a peça lida em p, por cima do que já foi pintado
void pintar(vec2 p) {
    vec2 qc = clamp(p, vec2(0.5), TAM - 0.5);
    vec2 rg = lerPeca(qc / ATLAS).rg;
    rg *= step(0.0, p.x) * step(0.0, p.y) * step(p.x, TAM.x) * step(p.y, TAM.y);
    accB = rg.r + accB * (1.0 - rg.g);
    accA = rg.g + accA * (1.0 - rg.g);
}

// só a massa escura em p, sem o traço: o lugar que uma peça deixou ao se mexer
void sombra(vec2 p) {
    float g = lerPeca(clamp(p, vec2(0.5), TAM - 0.5) / ATLAS).g;
    accB = accB * (1.0 - g);
    accA = g + accA * (1.0 - g);
}

float axial(vec2 p, vec2 a, vec2 b) {
    vec2 d = b - a;
    return dot(p - a, d) / max(dot(d, d), 1e-3);
}

// de onde vem o pixel q numa cadeia de n ossos (n = 2 ou 3) com as juntas
// R[0..n] em repouso e os ângulos a (cada um relativo ao osso de antes): o
// osso de cada pixel é o mais de fora em que ele cai depois da junta; no lado
// de fora de uma dobra, o osso de dentro continua (sem fresta)
vec2 cadeia(vec2 q, vec2 R0, vec2 R1, vec2 R2, vec2 R3, vec3 a, int n) {
    float A0 = a.x, A1 = a.x + a.y, A2 = A1 + a.z;
    vec2 D1 = R0 + girar(R1 - R0, A0);
    vec2 D2 = D1 + girar(R2 - R1, A1);
    if (n >= 3) {
        vec2 p2 = R2 + girar(q - D2, -A2);
        if (axial(p2, R2, R3) >= 0.0) return p2;
    }
    vec2 p1 = R1 + girar(q - D1, -A1);
    if (axial(p1, R1, R2) >= 0.0) return p1;
    return R0 + girar(q - R0, -A0);
}

bool dentro(vec2 q, vec4 c) {
    return q.x >= c.x && q.y >= c.y && q.x <= c.z && q.y <= c.w;
}

#if IMG == 3
// girar v por -ângulo, com (cos, sin) do ângulo: o desfazer de um giro sem trigonometria
vec2 desgirarCS(vec2 v, vec2 cs) {
    return vec2(cs.x * v.x + cs.y * v.y, cs.x * v.y - cs.y * v.x);
}
vec2 girarCS(vec2 v, vec2 cs) {
    return vec2(cs.x * v.x - cs.y * v.y, cs.y * v.x + cs.x * v.y);
}

// q visto no corpo b em repouso (desfeito o giro dele em volta do pescoço)
vec2 noCorpo(vec2 q, int b, float ang) {
#ifdef RELOGIO
    return PIVO[b] + desgirarCS(q - PIVO[b], Mc[NL + b].xy);
#else
    return PIVO[b] + girar(q - PIVO[b], -ang);
#endif
}

// a cadeia do membro i (a = os ângulos dele); no relógio, com os (cos, sin) do app
vec2 cadeiaMembro(vec2 qb, int i, vec3 a) {
    vec2 R0 = JUNTA[4 * i], R1 = JUNTA[4 * i + 1], R2 = JUNTA[4 * i + 2], R3 = JUNTA[4 * i + 3];
#ifdef RELOGIO
    vec2 c0 = Mc[i].xy, c1 = Mc[i].zw, c2 = Md[i].xy;
    vec2 D1 = R0 + girarCS(R1 - R0, c0);
    vec2 D2 = D1 + girarCS(R2 - R1, c1);
    vec2 p2 = R2 + desgirarCS(qb - D2, c2);
    if (axial(p2, R2, R3) >= 0.0) return p2;
    vec2 p1 = R1 + desgirarCS(qb - D1, c1);
    if (axial(p1, R1, R2) >= 0.0) return p1;
    return R0 + desgirarCS(qb - R0, c0);
#else
    return cadeia(qb, R0, R1, R2, R3, a, 3);
#endif
}
#endif
#endif

#if IMG == 2
// o centro da íris com o olhar: não passa das pálpebras (fica na elipse
// encolhida do raio dela)
vec2 centroIris(vec2 desl) {
    vec2 ar = AR - RP - 1.5;
    vec2 oa = (PUP - AB) / ar, da = desl / ar;
    float A = dot(da, da), B = dot(oa, da), C = dot(oa, oa) - 1.0;
    float tt = A > 1e-6 ? clamp((-B + sqrt(max(B * B - A * C, 0.0))) / A, 0.0, 1.0) : 1.0;
    return PUP + desl * tt;
}

// a fase de cada raio, tirada do ângulo: vizinhos parecidos, não iguais
float faseRaio(float a) {
    return 3.0 * sin(a * 3.0 + 1.3) + 2.0 * sin(a * 7.0 + 0.4) + 1.3 * sin(a * 13.0 + 2.1);
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
#if IMG >= 2
    gX = dFdx(q) / ATLAS;
    gY = dFdy(q) / ATLAS;
#ifdef RELOGIO
#define M Mu
#else
    vec4 M[48] = vec4[48](m0, m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12, m13, m14, m15, m16, m17, m18, m19, m20, m21, m22, m23, m24, m25, m26, m27, m28, m29, m30, m31, m32, m33, m34, m35, m36, m37, m38, m39, m40, m41, m42, m43, m44, m45, m46, m47);
#endif
#endif
    // direção do olhar, saturada: longe, a íris vai até a borda
    vec2 g = olhar - centro;
    vec2 dg = g / (length(g) + geo.x * 0.6);
#if IMG == 1
    // de trás para a frente: as asas de cima, as do meio (na frente delas: o
    // contorno em C é das do meio), as de baixo; o núcleo por cima. p: o
    // ponto no espaço do texel (o centro do texel i em i)
    vec2 pp = q - 0.5;
    vec2 s0 = repousoVert(pp, vec2(175.0, 184.0), vec2(162.0, 118.0), 1.0, img.w, img2.x) + 0.5;
    camada(0.0, iris(s0, vec2(162.0, 118.0), vec2(9.0, 9.0), dg * 3.0));
    vec2 s1 = repousoVert(pp, vec2(216.0, 184.0), vec2(219.0, 117.0), -1.0, img.w, img2.x) + 0.5;
    camada(1.0, iris(s1, vec2(219.0, 117.0), vec2(9.0, 9.0), dg * 3.0));
    const vec3 ESP_E = vec3(220.3, 25.0, 100.0);
    const vec3 ESP_D = vec3(220.3, 367.0, 292.0);
    vec2 s2 = espelhaEspinho(repousoMeio(pp, vec2(145.0, 214.0), vec2(110.0, 124.0), 1.0, 2.0, img.x, img.y), ESP_E) + 0.5;
    camada(2.0, iris(s2, vec2(74.0, 151.0), vec2(11.0, 6.0), dg * vec2(3.0, 0.8)));
    camadaM(2.0, q, step(abs(pp.y - ESP_E.x), meiaEspinho(pp.x, ESP_E) - 1e-6));
    vec2 s3 = espelhaEspinho(repousoMeio(pp, vec2(246.0, 214.0), vec2(279.0, 128.0), -1.0, 3.0, img.x, img.y), ESP_D) + 0.5;
    camada(3.0, iris(s3, vec2(308.0, 150.0), vec2(11.0, 6.0), dg * vec2(3.0, 0.8)));
    camadaM(3.0, q, step(abs(pp.y - ESP_D.x), meiaEspinho(pp.x, ESP_D) - 1e-6));
    vec2 s4 = repousoVert(pp, vec2(175.0, 254.0), vec2(157.0, 313.0), -1.0, img2.z, img2.y) + 0.5;
    camada(4.0, iris(s4, vec2(157.0, 313.0), vec2(8.0, 9.0), dg * 2.5));
    vec2 s5 = repousoVert(pp, vec2(216.0, 254.0), vec2(225.0, 313.0), 1.0, img2.z, img2.y) + 0.5;
    camada(5.0, iris(s5, vec2(225.0, 313.0), vec2(8.0, 9.0), dg * 2.5));
    camada(6.0, iris(q, vec2(192.5, 220.5), vec2(32.0, 17.5), dg * vec2(9.0, 1.5)));
#endif

#if IMG == 2
    // a coroa fluindo, presa ao olho: uma ondulação de lado que corre do olho
    // para fora (zero na raiz) e uma onda de brilho junto, em todas as camadas
    // de raios de uma vez. img.x é a amplitude na ponta (px), img.y a fase do
    // fluxo, img2.x o brilho
    vec2 d = q - OLHO;
    float r = max(length(d), 1e-3);
    float a = atan(d.y, d.x);
    float fr = faseRaio(a);
    float w = smoothstep(RAIZ, RAIZ + 70.0, r) * (0.45 + 0.55 * smoothstep(RAIZ, RAIZ + 200.0, r));
    float lado = w * img.x * sin(r * 0.05 - img.y + fr);
    float ar = a - lado / r;
    vec2 pr = OLHO + r * vec2(cos(ar), sin(ar));
    if (pecaEm(pr) == 1) {
        float B0 = accB;
        pintar(pr);
        float brilho = 1.0 + img2.x * w * (0.5 + 0.5 * sin(r * 0.045 - img.y * 1.6 + fr * 0.7));
        accB = min(accA, B0 + (accB - B0) * brilho);
    }
    // o globo, bem aberto e parado
    if (pecaEm(q) == 0) pintar(q);
    // a íris (o disco preto) anda para o olhar por cima do branco preenchido,
    // recortada pela abertura das pálpebras; encarar a leva ao meio
    vec2 pm = centroIris(dg * vec2(40.0, 14.0) + img2.y * (AB - PUP));
    vec2 v = q - pm;
    vec2 e = (q - AB) / AR;
    if (dot(v, v) < RI * RI && dot(e, e) < 1.0) pintar(DISCO + v);
#endif
#if IMG == 3
    // o miolo no lugar; onde um corpo saiu, a massa dele fica como sombra
    // as cabeças olham para o cursor: giram em volta do queixo e andam um pouco para ele
#ifdef RELOGIO
    // no relógio as cabeças ficam paradas (pedido do Davi): pintadas no lugar
    // junto do miolo, sem o laço delas
    vec2 olharH = vec2(0.0);
    float girarH = 0.0;
#else
    vec2 olharH = dg * vec2(5.5, 4.0);
    float girarH = dg.x * 0.28;
#endif
    // O desvio só escolhe o modo (0 nada, 1 pinta, 2 só a sombra) e a escrita vem
    // depois, sem desvio: o compilador da Adreno 504 (relógio) perdia o que
    // pintar() e sombra() escreviam no acumulado de dentro deste if/else, e o
    // miolo e as sombras sumiam. O acumulado ainda está zerado aqui: pintar dá
    // (r, g), a sombra dá (0, g)
    int pq = pecaEm(q);
    float modo = 0.0;
    if (pq == 0) modo = 1.0;
    else if (pq > NL && pq <= NL + NB) {
        // só se o corpo saiu mesmo de cima deste pixel (parado, ele se cobre)
        int bq = pq - NL - 1;
        if (distance(noCorpo(q, bq, M[NL + bq].x), q) > 0.35) modo = 2.0;
    } else if (pq > NL + NB) {
        modo = length(olharH) > 0.35 || abs(girarH) > 0.004 ? 2.0 : 1.0;
    }
    vec2 rg0 = lerPeca(clamp(q, vec2(0.5), TAM - 0.5) / ATLAS).rg;
    rg0 *= step(0.0, q.x) * step(0.0, q.y) * step(q.x, TAM.x) * step(q.y, TAM.y);
    accB = modo == 1.0 ? rg0.r : 0.0;
    accA = modo > 0.5 ? rg0.g : 0.0;
    // SEM_CORPOS, SEM_CABECAS e SEM_MEMBROS só existem na bancada do relógio
    // (medir o custo de cada laço na GPU dele); o app não os define
#ifndef SEM_CORPOS
    // os corpos, cada um girando em volta do pescoço
    for (int b = 0; b < NB; b++) {
        if (!dentro(q, CAIXA_C[b])) continue;
        vec2 p = noCorpo(q, b, M[NL + b].x);
        if (pecaEm(p) == NL + 1 + b) pintar(p);
    }
#endif
#if !defined(SEM_CABECAS) && !defined(RELOGIO)
    // as cabeças, por cima dos corpos
    if (length(olharH) > 0.35 || abs(girarH) > 0.004) {
        // o giro é o mesmo para todas: seno e cosseno uma vez, fora do laço
        vec2 csH = vec2(cos(girarH), sin(girarH));
        for (int h = 0; h < NH; h++) {
            vec2 ph = QUEIXO[h] + desgirarCS(q - QUEIXO[h] - olharH, csH);
            if (!dentro(ph, CAIXA_H[h])) continue;
            if (pecaEm(ph) == NL + NB + 1 + h) pintar(ph);
        }
    }
#endif
#ifndef SEM_MEMBROS
    // os membros, por cima: primeiro o giro do corpo de onde saem, depois a cadeia
    for (int i = 0; i < NL; i++) {
        int pai = PAI[i];
        vec2 qb = pai >= 0 ? noCorpo(q, pai, M[NL + pai].x) : q;
        if (!dentro(qb, CAIXA_M[i])) continue;
        vec2 p = cadeiaMembro(qb, i, M[i].xyz);
        if (pecaEm(p) == i + 1) pintar(p);
    }
#endif
#endif

#ifdef POSITIVO
    // positivo (as cores da gravura): o papel sai como traço claro e a tinta
    // como a massa escura por baixo
    float A = clamp(accA - accB, 0.0, 1.0);
#else
    float A = min(accB, accA);
#endif
    float E = accA > A ? min((accA - A) / max(1.0 - A, 1e-4), 1.0) : 0.0;
    fragColor = vec4(A, E, 0.0, max(A, E)) * qt_Opacity;
}
