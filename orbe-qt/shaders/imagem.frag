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
                     // entidade: brilho do halo, posição e força da onda no crescente, escala extra
    vec4 img2;       // entidade: fase e força da luz nos filetes, fase e força do redemoinho
    vec4 img3;       // entidade: força da cintilação, —, —, —
};
layout(binding = 1) uniform sampler2D arte;

#if IMG == 1
// Seraphim (gravura): recorte de 392 x 444 px, células de 408 px no atlas
const vec2 TAM = vec2(392.0, 444.0);
const float CELULA = 408.0;
const vec2 ATLAS = vec2(2856.0, 444.0);
const vec2 OLHO = vec2(192.0, 220.0);    // vai no centro do item
const float RIMG = 222.0;                // R da figura, em px da imagem
#elif IMG == 2
// Entidade: recorte de 1179 x 1440 px. Célula 0 = traço e silhueta; célula 1 =
// peso do halo, filetes de luz e as estrelas grandes (as que ainda aparecem no
// tamanho do orbe, cada uma um disco de 5 px)
const vec2 TAM = vec2(1179.0, 1440.0);
const float CELULA = 1195.0;
const vec2 ATLAS = vec2(2390.0, 1440.0);
const vec2 OLHO = vec2(590.0, 720.0);
const float RIMG = 720.0;
const vec2 ANEL = vec2(597.0, 323.0);       // centro do halo
const vec2 VORT = vec2(578.0, 1178.0);      // a boca na barriga: elipse com o
const vec2 VORT_R = vec2(150.0, 105.0);     //   eixo maior inclinado 56°
const float VORT_A = 0.977;
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

// leitura do atlas. Reduzida: 4 amostras dentro do pixel, cada uma com metade
// da pegada (filtro mais justo que o trilinear do mipmap, perto de uma redução
// Lanczos da imagem), e um realce leve do traço contra a média da vizinhança
// (um nível de mipmap mais grosso). Forte demais, o realce estoura a hachura
// densa em branco; 0.4 fica só um pouco mais nítido que o Lanczos. A 1:1 as 4
// amostras caem no centro do texel e o realce zera: a cópia segue exata
const float REALCE = 0.4;
vec4 ler(vec2 uv, float realce) {
    vec2 dx = dFdx(uv) * 0.25, dy = dFdy(uv) * 0.25;
    vec2 ox = dx * kRed, oy = dy * kRed;
    vec4 v = 0.5 * (0.5 * (textureGrad(arte, uv - ox - oy, 2.0 * dx, 2.0 * dy) + textureGrad(arte, uv + ox - oy, 2.0 * dx, 2.0 * dy))
                  + 0.5 * (textureGrad(arte, uv - ox + oy, 2.0 * dx, 2.0 * dy) + textureGrad(arte, uv + ox + oy, 2.0 * dx, 2.0 * dy)));
    float vb = texture(arte, uv, 1.5).r;
    v.r = sat01(v.r + REALCE * realce * kRed * (v.r - vb));
    return v;
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
// desvio), para as derivadas do ler() valerem
void camada(float cel, vec2 q) {
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
#if IMG == 1
    float s = geo.x / RIMG * (1.0 + img.z);
#else
    float s = geo.x / RIMG * (1.0 + img.w);
#endif
    vec2 q = (p - centro) / s + OLHO;
    kRed = 1.0 - smoothstep(0.35, 0.8, s);
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
#elif IMG == 2
    // a boca na barriga gira como redemoinho: dois giros defasados que se
    // revezam (a torção não acumula), parados na borda da elipse
    vec2 eLoc = girar(q - VORT, -VORT_A) / VORT_R;
    float wv = (1.0 - smoothstep(0.35, 1.0, length(eLoc))) * img2.w;
    float f1 = fract(img2.z), f2 = fract(img2.z + 0.5);
    // parado, o ponto fica exatamente em q (girar 56° e voltar não é exato em float)
    float anda = step(1e-5, wv);
    vec2 q1 = q + (VORT + girar(girar(eLoc, -1.2 * f1 * wv) * VORT_R, VORT_A) - q) * anda;
    vec2 q2 = q + (VORT + girar(girar(eLoc, -1.2 * f2 * wv) * VORT_R, VORT_A) - q) * anda;
    vec2 rg = mix(celula(0.0, q2).rg, celula(0.0, q1).rg, 1.0 - abs(2.0 * f1 - 1.0));
    vec3 m = celula(1.0, q).rgb;               // halo, filetes, estrelas grandes
    float r = rg.r, gg = rg.g;
    // halo: brilho pelo estado e uma onda de luz correndo pelo crescente
    vec2 da = q - ANEL;
    float dist = length(da);
    float dif = mod(atan(da.y, da.x) - img.y + PI, TAU) - PI;
    float onda = exp(-dif * dif / 0.18) * smoothstep(180.0, 220.0, dist) * (1.0 - smoothstep(330.0, 360.0, dist));
    r *= mix(1.0, img.x, m.r);
    r += (1.0 - r) * onda * img.z * 0.55 * m.r * gg;   // só no anel e no rosto, não no céu do vão
    // luz escorrendo pelos filetes
    r *= 1.0 - m.g * img2.y * (0.5 + 0.5 * sin((q.y - img2.x) * TAU / 70.0));
    // estrelas cintilando; pequenas, as grandes viram um ponto de 1 px
    float h = hash2(floor(q / 14.0));
    float cint = 1.0 - img3.x * 0.6 * (0.5 + 0.5 * sin(geo.z * (1.5 + 2.0 * h) + h * TAU));
    r *= mix(1.0, cint, sat01(m.b * 4.0));
    r = max(r, m.b * cint * (1.0 - smoothstep(0.2, 0.5, s)));
    accB = r;
    accA = max(gg, r);
#endif

    float A = min(accB, accA);
    float E = accA > A ? min((accA - A) / max(1.0 - A, 1e-4), 1.0) : 0.0;
    fragColor = vec4(A, E, 0.0, max(A, E)) * qt_Opacity;
}
