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
    vec4 img;        // gravura: abertura das asas (1 = como desenhadas), batida (fração da dobra), escala extra, —
                     // olho: giro da coroa de raios, —, escala extra, pupila (1 = como desenhada)
    vec4 img2;       // olho: —, quanto encara (0 = como desenhado), quanto as pálpebras fecham (0 a 1), —
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
// Olho: recorte de 505 x 609 px, uma célula; os raios cortados um a um
const vec2 TAM = vec2(505.0, 609.0);
const float CELULA = 0.0;
const vec2 ATLAS = TAM;
const vec2 OLHO = vec2(260.0, 284.5);    // o centro do globo, no centro do item
const float RIMG = 270.0;
const vec2 PUP = vec2(285.5, 279.6);     // a pupila desenhada
const float RP = 42.5;
const vec2 AB = vec2(250.0, 292.0);      // a abertura das pálpebras (elipse, um pouco por dentro)
const vec2 AR = vec2(92.0, 57.0);
const float PALPEBRA = 24.0;             // a faixa da pálpebra de cima que estica para fechar
const int NR = 48;      // raios: cadeias raiz, meio, ponta
const vec2 JUNTA[144] = vec2[144](
    vec2(240.0, 425.0), vec2(217.0, 474.0), vec2(218.0, 543.0),
    vec2(288.0, 131.0), vec2(307.0, 89.0), vec2(314.0, 31.0),
    vec2(374.0, 222.0), vec2(415.0, 192.0), vec2(470.0, 162.0),
    vec2(130.0, 279.0), vec2(85.0, 287.0), vec2(33.0, 301.0),
    vec2(133.0, 313.0), vec2(90.0, 335.0), vec2(38.0, 357.0),
    vec2(183.0, 180.0), vec2(168.0, 138.0), vec2(137.0, 96.0),
    vec2(338.0, 399.0), vec2(352.0, 438.0), vec2(381.0, 480.0),
    vec2(252.0, 155.0), vec2(245.0, 123.0), vec2(241.0, 78.0),
    vec2(115.0, 209.0), vec2(85.0, 190.0), vec2(44.0, 163.0),
    vec2(156.0, 362.0), vec2(131.0, 392.0), vec2(96.0, 425.0),
    vec2(392.0, 271.0), vec2(426.0, 258.0), vec2(468.0, 249.0),
    vec2(227.0, 159.0), vec2(224.0, 125.0), vec2(209.0, 87.0),
    vec2(144.0, 341.0), vec2(113.0, 359.0), vec2(71.0, 374.0),
    vec2(161.0, 395.0), vec2(145.0, 402.0), vec2(130.0, 436.0),
    vec2(384.0, 336.0), vec2(415.0, 350.0), vec2(455.0, 363.0),
    vec2(321.0, 408.0), vec2(322.0, 439.0), vec2(340.0, 475.0),
    vec2(207.0, 166.0), vec2(201.0, 135.0), vec2(179.0, 110.0),
    vec2(156.0, 362.0), vec2(125.0, 371.0), vec2(93.0, 394.0),
    vec2(337.0, 388.0), vec2(350.0, 414.0), vec2(368.0, 441.0),
    vec2(204.0, 402.0), vec2(189.0, 425.0), vec2(174.0, 443.0),
    vec2(346.0, 187.0), vec2(359.0, 165.0), vec2(383.0, 139.0),
    vec2(229.0, 411.0), vec2(215.0, 427.0), vec2(206.0, 444.0),
    vec2(385.0, 248.0), vec2(412.0, 242.0), vec2(434.0, 226.0),
    vec2(407.0, 310.0), vec2(431.0, 321.0), vec2(463.0, 325.0),
    vec2(156.0, 165.0), vec2(134.0, 153.0), vec2(120.0, 127.0),
    vec2(319.0, 156.0), vec2(331.0, 143.0), vec2(345.0, 114.0),
    vec2(206.0, 134.0), vec2(199.0, 113.0), vec2(196.0, 84.0),
    vec2(353.0, 375.0), vec2(364.0, 399.0), vec2(390.0, 418.0),
    vec2(118.0, 118.0), vec2(96.0, 104.0), vec2(74.0, 80.0),
    vec2(407.0, 210.0), vec2(425.0, 208.0), vec2(452.0, 200.0),
    vec2(186.0, 404.0), vec2(170.0, 423.0), vec2(150.0, 446.0),
    vec2(119.0, 266.0), vec2(101.0, 270.0), vec2(81.0, 254.0),
    vec2(425.0, 244.0), vec2(445.0, 238.0), vec2(469.0, 229.0),
    vec2(119.0, 266.0), vec2(106.0, 254.0), vec2(82.0, 247.0),
    vec2(399.0, 350.0), vec2(414.0, 364.0), vec2(436.0, 378.0),
    vec2(111.0, 273.0), vec2(90.0, 276.0), vec2(75.0, 275.0),
    vec2(266.0, 130.0), vec2(265.0, 111.0), vec2(267.0, 88.0),
    vec2(144.0, 341.0), vec2(124.0, 344.0), vec2(103.0, 346.0),
    vec2(372.0, 359.0), vec2(391.0, 370.0), vec2(410.0, 371.0),
    vec2(134.0, 254.0), vec2(116.0, 247.0), vec2(109.0, 230.0),
    vec2(393.0, 294.0), vec2(412.0, 292.0), vec2(433.0, 292.0),
    vec2(152.0, 385.0), vec2(160.0, 400.0), vec2(156.0, 421.0),
    vec2(111.0, 180.0), vec2(99.0, 166.0), vec2(83.0, 153.0),
    vec2(158.0, 204.0), vec2(142.0, 194.0), vec2(122.0, 192.0),
    vec2(63.0, 315.0), vec2(80.0, 316.0), vec2(99.0, 311.0),
    vec2(344.0, 154.0), vec2(355.0, 142.0), vec2(361.0, 124.0),
    vec2(171.0, 173.0), vec2(161.0, 163.0), vec2(157.0, 147.0),
    vec2(368.0, 170.0), vec2(381.0, 168.0), vec2(391.0, 152.0));
const vec4 CAIXA_M[48] = vec4[48](
    vec4(142.0, 356.0, 313.0, 615.0), vec4(228.0, -30.0, 375.0, 195.0), vec4(307.0, 99.0, 535.0, 292.0), vec4(-24.0, 219.0, 192.0, 361.0), vec4(-24.0, 251.0, 198.0, 421.0), vec4(82.0, 42.0, 243.0, 240.0), vec4(282.0, 344.0, 435.0, 535.0), vec4(190.0, 33.0, 301.0, 204.0), vec4(-5.0, 114.0, 167.0, 262.0), vec4(45.0, 308.0, 211.0, 478.0), vec4(344.0, 203.0, 515.0, 322.0), vec4(165.0, 44.0, 278.0, 206.0), vec4(25.0, 290.0, 196.0, 422.0), vec4(94.0, 350.0, 198.0, 471.0), vec4(337.0, 288.0, 500.0, 410.0), vec4(276.0, 367.0, 382.0, 518.0), vec4(141.0, 70.0, 251.0, 209.0), vec4(50.0, 319.0, 182.0, 437.0), vec4(300.0, 352.0, 406.0, 478.0), vec4(143.0, 369.0, 238.0, 478.0), vec4(304.0, 100.0, 422.0, 230.0), vec4(182.0, 384.0, 260.0, 471.0), vec4(350.0, 190.0, 467.0, 286.0), vec4(369.0, 272.0, 499.0, 363.0), vec4(85.0, 93.0, 190.0, 200.0), vec4(288.0, 85.0, 375.0, 194.0), vec4(164.0, 54.0, 237.0, 166.0), vec4(316.0, 338.0, 427.0, 456.0), vec4(40.0, 45.0, 153.0, 154.0), vec4(380.0, 173.0, 480.0, 241.0), vec4(118.0, 372.0, 220.0, 480.0), vec4(54.0, 228.0, 148.0, 299.0), vec4(397.0, 201.0, 498.0, 273.0), vec4(57.0, 222.0, 143.0, 287.0), vec4(371.0, 321.0, 466.0, 409.0), vec4(46.0, 246.0, 134.0, 303.0), vec4(237.0, 63.0, 298.0, 159.0), vec4(78.0, 310.0, 176.0, 379.0), vec4(344.0, 329.0, 437.0, 403.0), vec4(86.0, 205.0, 163.0, 283.0), vec4(368.0, 262.0, 460.0, 326.0), vec4(126.0, 362.0, 190.0, 446.0), vec4(59.0, 129.0, 137.0, 206.0), vec4(99.0, 166.0, 186.0, 232.0), vec4(40.0, 288.0, 122.0, 343.0), vec4(318.0, 102.0, 386.0, 179.0), vec4(133.0, 123.0, 196.0, 197.0), vec4(345.0, 128.0, 415.0, 202.0));
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
const float RIMG = 255.0;
const int NL = 27;      // membros: cadeias base, joelho ou cotovelo, tornozelo ou punho, ponta
const int NB = 8;       // corpos: giram em volta do pescoço (PIVO), levando os membros que saem deles
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
    vec4(253.0, -40.0, 379.0, 115.0), vec4(154.0, -55.0, 314.0, 172.0), vec4(94.0, -51.0, 278.0, 180.0), vec4(223.0, -3.0, 325.0, 125.0), vec4(82.0, 22.0, 161.0, 104.0), vec4(280.0, 5.0, 403.0, 143.0), vec4(327.0, 22.0, 482.0, 165.0), vec4(320.0, 64.0, 385.0, 130.0), vec4(378.0, 66.0, 496.0, 177.0), vec4(90.0, 85.0, 190.0, 183.0), vec4(-39.0, 49.0, 195.0, 245.0), vec4(378.0, 103.0, 513.0, 197.0), vec4(-68.0, 103.0, 184.0, 289.0), vec4(399.0, 152.0, 525.0, 259.0), vec4(-53.0, 155.0, 144.0, 307.0), vec4(391.0, 209.0, 560.0, 354.0), vec4(-47.0, 230.0, 131.0, 390.0), vec4(-5.0, 256.0, 134.0, 398.0), vec4(377.0, 273.0, 554.0, 433.0), vec4(54.0, 287.0, 194.0, 431.0), vec4(24.0, 322.0, 130.0, 450.0), vec4(102.0, 374.0, 205.0, 490.0), vec4(336.0, 391.0, 414.0, 492.0), vec4(306.0, 382.0, 401.0, 513.0), vec4(131.0, 388.0, 237.0, 521.0), vec4(187.0, 412.0, 264.0, 511.0), vec4(223.0, 347.0, 380.0, 544.0));
const int PAI[27] = int[27](-1, 6, 5, -1, 5, 2, 2, 2, 3, 5, -1, 3, 4, -1, 4, 1, 4, 7, 1, -1, 7, 0, -1, -1, 0, -1, -1);
const vec2 PIVO[8] = vec2[8](vec2(238.0, 225.0), vec2(289.0, 218.0), vec2(279.0, 151.0), vec2(304.0, 183.0), vec2(163.0, 213.0), vec2(216.0, 157.0), vec2(247.0, 142.0), vec2(208.0, 215.0));
const vec4 CAIXA_C[8] = vec4[8](
    vec4(139.0, 193.0, 314.0, 461.0), vec4(258.0, 170.0, 496.0, 363.0), vec4(257.0, 68.0, 405.0, 190.0), vec4(283.0, 112.0, 442.0, 220.0), vec4(28.0, 183.0, 186.0, 315.0), vec4(109.0, 30.0, 253.0, 180.0), vec4(229.0, 63.0, 279.0, 157.0), vec4(24.0, 178.0, 244.0, 405.0));
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
#endif

#if IMG == 2
// o centro da pupila com o olhar: não passa das pálpebras (fica na elipse
// encolhida do raio dela)
vec2 centroPupila(vec2 desl) {
    vec2 ar = AR - RP - 1.5;
    vec2 oa = (PUP - AB) / ar, da = desl / ar;
    float A = dot(da, da), B = dot(oa, da), C = dot(oa, oa) - 1.0;
    float tt = A > 1e-6 ? clamp((-B + sqrt(max(B * B - A * C, 0.0))) / A, 0.0, 1.0) : 1.0;
    return PUP + desl * tt;
}

// a pupila (o disco preto) anda para pm; o branco do olho entre ela e as
// pálpebras estica junto, e a borda da abertura fica no lugar. Com pm = PUP
// devolve q
vec2 pupila(vec2 q, vec2 pm) {
    vec2 e = (q - AB) / AR;
    if (dot(e, e) >= 1.0) return q;
    vec2 v = q - pm;
    float r = length(v);
    vec2 u = r > 1e-4 ? v / r : vec2(1.0, 0.0);
    vec2 om = (pm - AB) / AR, du = u / AR;
    float A2 = dot(du, du), B2 = dot(om, du), C2 = dot(om, om) - 1.0;
    float lam = (-B2 + sqrt(max(B2 * B2 - A2 * C2, 0.0))) / A2;
    if (r <= RP) return PUP + v;
    float al = clamp((r - RP) / max(lam - RP, 1e-3), 0.0, 1.0);
    return mix(PUP + u * RP, pm + u * lam, al);
}

// as pálpebras fecham c (0 aberto, 1 fechado): a de cima estica a faixa dela
// até a nova borda, e o que ainda se vê do olho se espreme contra a de baixo.
// Com c = 0 devolve q; em aberto, o y do olho que se vê (-1 = coberto)
vec2 palpebras(vec2 q, float c, out bool coberto) {
    coberto = false;
    if (c <= 0.001) return q;
    float dx = (q.x - AB.x) / AR.x;
    if (abs(dx) >= 1.0) return q;
    float h = AR.y * sqrt(1.0 - dx * dx);
    float eu = AB.y - h, el = AB.y + h;
    float topo = eu - PALPEBRA;
    float novo = eu + c * (el - eu) * 0.97;
    if (q.y < topo || q.y > el) return q;
    if (q.y <= novo) {
        coberto = true;
        return vec2(q.x, topo + (q.y - topo) / max(novo - topo, 1e-3) * (eu - topo));
    }
    return vec2(q.x, eu + (q.y - novo) / max(el - novo, 1e-3) * (el - eu));
}

// a íris desenhada no disco preto: fios claros em volta da pupila (que dilata
// com dil) e o brilho; q no espaço do olho, pm o centro da pupila
void iris(vec2 q, vec2 pm, float dil, float t) {
    vec2 v = q - pm;
    float r = length(v);
    if (r > RP) return;
    float a = atan(v.y, v.x);
    float rp = RP * 0.42 * dil;
    // os fios da íris, como na hachura da gravura: raios com um pouco de ruído
    float fio = 0.5 + 0.5 * sin(a * 46.0 + 3.0 * sin(a * 7.0 + r * 0.15));
    fio = smoothstep(0.55, 0.95, fio) * (0.55 + 0.45 * hash2(vec2(floor(a * 46.0 / TAU * 6.0), 3.0)));
    float anel = smoothstep(rp, rp + 2.5, r) * (1.0 - smoothstep(RP * 0.80, RP * 0.97, r));
    float tr = 0.42 * fio * anel + 0.10 * anel;
    // a borda da pupila e o brilho
    tr += 0.25 * (1.0 - smoothstep(0.0, 1.6, abs(r - rp))) * step(rp, r + 1.6);
    float b = 1.0 - smoothstep(RP * 0.10, RP * 0.15, length(v - vec2(-0.32, -0.38) * RP));
    tr = sat01(tr + b);
    accB = tr + accB * (1.0 - tr);
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
    vec4 M[48] = vec4[48](m0, m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12, m13, m14, m15, m16, m17, m18, m19, m20, m21, m22, m23, m24, m25, m26, m27, m28, m29, m30, m31, m32, m33, m34, m35, m36, m37, m38, m39, m40, m41, m42, m43, m44, m45, m46, m47);
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
    // os raios, por trás do globo: a coroa gira inteira (img.x) em volta do
    // olho, e cada raio dobra na raiz e no meio e estica pelo comprimento
    vec2 qr = OLHO + girar(q - OLHO, -img.x);
    for (int i = 0; i < NR; i++) {
        if (!dentro(qr, CAIXA_M[i])) continue;
        vec2 R0 = JUNTA[3 * i], R1 = JUNTA[3 * i + 1], R2 = JUNTA[3 * i + 2];
        vec2 qe = R0 + (qr - R0) / (1.0 + M[i].z);
        vec2 p = cadeia(qe, R0, R1, R2, R2, vec3(M[i].xy, 0.0), 2);
        if (pecaEm(p) == i + 1) pintar(p);
    }
    // o globo: as pálpebras, a pupila que anda para o olhar (encarar a leva ao
    // meio da abertura, olhando para quem fala) e a íris desenhada nela
    bool coberto;
    vec2 qo = palpebras(q, img2.z, coberto);
    vec2 pm = centroPupila(dg * vec2(40.0, 14.0) + img2.y * (AB - PUP));
    vec2 qp = coberto ? qo : pupila(qo, pm);
    if (pecaEm(qp) == 0) {
        pintar(qp);
        if (!coberto && dot((qo - AB) / AR, (qo - AB) / AR) < 1.0) iris(qo, pm, img.w, geo.z);
    }
#endif
#if IMG == 3
    // o miolo no lugar; onde um corpo saiu, a massa dele fica como sombra
    int pq = pecaEm(q);
    if (pq == 0) pintar(q);
    else if (pq > NL) {
        // só se o corpo saiu mesmo de cima deste pixel (parado, ele se cobre)
        int bq = pq - NL - 1;
        if (distance(PIVO[bq] + girar(q - PIVO[bq], -M[NL + bq].x), q) > 0.35) sombra(q);
    }
    // os corpos, cada um girando em volta do pescoço
    for (int b = 0; b < NB; b++) {
        if (!dentro(q, CAIXA_C[b])) continue;
        vec2 p = PIVO[b] + girar(q - PIVO[b], -M[NL + b].x);
        if (pecaEm(p) == NL + 1 + b) pintar(p);
    }
    // os membros, por cima: primeiro o giro do corpo de onde saem, depois a cadeia
    for (int i = 0; i < NL; i++) {
        int pai = PAI[i];
        vec2 qb = pai >= 0 ? PIVO[pai] + girar(q - PIVO[pai], -M[NL + pai].x) : q;
        if (!dentro(qb, CAIXA_M[i])) continue;
        vec2 p = cadeia(qb, JUNTA[4 * i], JUNTA[4 * i + 1], JUNTA[4 * i + 2], JUNTA[4 * i + 3], M[i].xyz, 3);
        if (pecaEm(p) == i + 1) pintar(p);
    }
#endif

    float A = min(accB, accA);
    float E = accA > A ? min((accA - A) / max(1.0 - A, 1e-4), 1.0) : 0.0;
    fragColor = vec4(A, E, 0.0, max(A, E)) * qt_Opacity;
}
