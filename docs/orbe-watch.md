# Orbe Watch

<p align="center">
<img src="img/ciclo.gif" width="288" alt="O orbe no relógio passando por em espera, ouvindo, pensando e falando">
</p>

O **Orbe Watch** é o [Orbe](../README.md) no pulso: o mesmo desenho, feito na
GPU de um relógio Wear OS com os shaders do desktop, e um menu no estilo do
aplicativo de configuração.

Ele **não é um agente**. Como o Orbe do computador, o relógio é só a **ponte de
fala**: segurando o orbe, a sua voz vai para o agente (Claude Code, qualquer
agente ACP, o Hermes), as linhas do raciocínio aparecem abaixo da figura e a
resposta volta em voz. Quem pensa e responde é o agente.

![O orbe em espera, ouvindo, pensando e falando](img/estados.png)

## Índice

1. [Como funciona](#como-funciona)
2. [Requisitos](#requisitos)
3. [Começando](#começando)
4. [A tela do orbe](#a-tela-do-orbe)
5. [O menu](#o-menu)
6. [Avatares](#avatares)
7. [Conversando com um agente](#conversando-com-um-agente)
8. [Rede](#rede)
9. [Segurança](#segurança)
10. [Protocolo da ponte](#protocolo-da-ponte)
11. [Por dentro do app](#por-dentro-do-app)
12. [No TicWatch Pro 5](#no-ticwatch-pro-5)
13. [Compilar, testar e depurar](#compilar-testar-e-depurar)
14. [Problemas comuns](#problemas-comuns)
15. [Limites conhecidos](#limites-conhecidos)
16. [Créditos](#créditos)

---

## Como funciona

```
      relógio (Wear OS)                          computador
┌──────────────────────────┐   WebSocket   ┌───────────────────────────────┐
│ orbe desenhado na GPU    │◄── linhas ────│ ponte do relógio              │
│ microfone  ──────────────┼── PCM 16 kHz ►│ (hermes_voice_relogio.py)     │
│ alto-falante ◄───────────┼── PCM voz ────│                               │
│ toque / segurar ─────────┼── touch ─────►│ servida por um de dois:       │
└──────────────────────────┘               │  • o daemon do Orbe (Linux)   │
                                           │  • o orbe de pulso, sem       │
                                           │    desktop (qualquer SO)      │
                                           └──────────────┬────────────────┘
                                                          │ fala → texto (Groq Whisper)
                                                          ▼
                                                 agente (ACP ou Claude Code)
                                                          │ raciocínio + resposta
                                                          ▼
                                                  voz (TTS) → de volta ao relógio
```

A ponte fala o mesmo protocolo de linhas do orbe do desktop (`show`, `state`,
`level`, `mic`, `line`, `hold`, `hide`, `clear`). O relógio só desenha o que
recebe e devolve o toque e a fala. Por isso o orbe do pulso é igual ao do
computador, estado por estado.

A ponte pode ser servida de dois jeitos:

- **Pelo daemon** (`hermes_voice_daemon.py`), no Linux com o desktop. O orbe do
  relógio acompanha o do computador. A sessão aberta pelo relógio é dele: fala
  com o Claude (veja [Sessão aberta pelo relógio](#sessão-aberta-pelo-relógio)),
  ouve só o microfone do relógio e toca a resposta onde o relógio pediu. A
  ponte vem desligada por padrão.
- **Pelo orbe de pulso** (`hermes_voice_pulso.py`), sem o desktop e fora do
  Linux. Python puro, sem PipeWire nem Wayland, testado no Windows. O
  microfone e o alto-falante são os do relógio.

## Requisitos

**No relógio**

- Wear OS 3 ou mais novo (Android 11, API 30) com OpenGL ES 3.0.
- Depuração por adb ligada, para instalar o app (nas opções do desenvolvedor,
  "Depuração por Wi-Fi").

**No computador**

- Python 3.11 ou mais novo com `websockets` e `requests`:
  `pip install websockets requests`.
- Para o orbe de pulso: as chaves `GROQ_API_KEY` (transcrição) e
  `GEMINI_API_KEY` (voz) no ambiente, em `~/.hermes/.env` ou num arquivo
  passado com `--env`.
- Para compilar o app: JDK 17 e o Android SDK (`ANDROID_HOME` ou
  `orbe-wear/local.properties`). O Gradle é o do wrapper (9.3.1).

## Começando

São três passos: ligar a ponte, instalar o app e parear.

### 1. Ligar a ponte

Sem o desktop (o caminho mais curto, serve em qualquer sistema):

```sh
pip install websockets requests

# a sessão do Claude Code que estiver aberta com o canal do orbe
./claude-orbe                       # no Windows: claude-orbe.cmd
./hermes_voice_pulso.py --agente claude

# ou um agente ACP qualquer, numa pasta
./hermes_voice_pulso.py --comando "npx -y @zed-industries/claude-agent-acp" --pasta ~/projeto
```

Ao subir, o orbe de pulso mostra o endereço e o **token** do pareamento. O
mesmo par aparece com `./hermes_voice_relogio.py`.

Com o daemon, no Linux: ligue o grupo **Relógio** na aba Ativação do app de
configuração, ou rode:

```sh
./hermes_voice_relogio.py --ligar     # liga a ponte e mostra o endereço e o token
systemctl --user restart hermes-voice
```

A ponte abre a porta **8777** para a rede local (libere-a no firewall, se
houver um) e só conversa com quem tem o token. Desligada, o daemon não abre
porta nenhuma.

### 2. Instalar o app

```sh
cd orbe-wear
./gradlew :app:assembleRelease
adb install app/build/outputs/apk/release/app-release.apk
```

O APK de release sai assinado com a chave de debug, para instalar direto com o
adb. Para distribuir, assine com a sua.

### 3. Parear

Sem digitar no pulso, pelo adb:

```sh
adb shell am start -n io.hermes.orbe/.MainActivity --es servidor 192.168.0.10 --es token abcd2345
```

Ou no menu do relógio: **Conexão → Servidor** e **Conexão → Token** abrem o
teclado do relógio (ou o ditado, ou o teclado do celular pareado). O servidor
aceita:

| Você digita | O app usa |
|---|---|
| `192.168.0.10` | `ws://192.168.0.10:8777/` |
| `192.168.0.10:9000` | `ws://192.168.0.10:9000/` |
| `[fd7a::1]:8777` | IPv6 entre colchetes |
| `wss://orbe.exemplo.com` | TLS, porta 443 do proxy |

Pareado, o estado mostra **conectado** e o orbe aparece quando a sessão abre.
Sem a ponte no ar, o app tenta de novo sozinho, com intervalos crescentes.

Para ver o relógio funcionando sem agente nenhum, `./hermes_voice_relogio.py
--demo` serve o ciclo da prévia (espera, escuta, raciocínio, fala).

## A tela do orbe

A tela inicial é o orbe no mostrador inteiro, com as linhas do raciocínio
abaixo dele. A pequena alça no pé da tela é a do menu, que fica embaixo. O
orbe fica sempre no mostrador, e a sessão aberta mantém a tela acesa.

| Estado | O que o orbe mostra |
|---|---|
| **Em espera** | A figura em repouso. Quando o dedo encosta, os olhos vão para ele. |
| **Ouvindo** | A figura reage ao nível do seu microfone. |
| **Pensando** | A figura muda de postura e as linhas do raciocínio do agente entram embaixo: a mais nova inteira, as antigas esmaecendo. |
| **Falando** | A figura acompanha o nível e o tom da voz da resposta. |

### Toque

O toque vale como no orbe do desktop:

| Gesto | Efeito |
|---|---|
| **Segurar** (mais de 350 ms) | Segurar para falar: a fala vai para o agente enquanto o dedo estiver na tela. Soltar encerra a fala. O relógio vibra ao segurar e ao soltar. |
| **Toque curto** | Abre a sessão, ou interrompe a resposta e volta a ouvir. |
| **Dois toques curtos** | Travam a sessão aberta (um ponto aparece acima da figura). |
| **Arrastar para o lado** | Gira o orbe, como a face de um cubo, até a skin seguinte (ou a anterior). Depois da última skin, a primeira volta na cor seguinte: a do tema, ciano, verde, âmbar e violeta. Como escolher um avatar no menu, desliga o "Seguir o orbe do PC". |
| **Arrastar para cima**, ou girar a coroa | Abre o menu. |

O microfone já começa a guardar um segundo de áudio quando o dedo encosta,
para a primeira sílaba não se perder entre o toque e o "segurar". Com a
sessão aberta, a tela do relógio não apaga no meio da conversa.

### Rodapé de estado

Quando não há texto na tela, o rodapé mostra o estado da ponte. Tocar nele
abre o menu.

| Texto | Significado |
|---|---|
| *(vazio)* | Conectado. |
| `sem servidor` | Falta o servidor ou o token. |
| `conectando…` | Procurando a ponte. |
| `token recusado` | O token não confere. Veja [Problemas comuns](#problemas-comuns). |
| `muitas tentativas` | A ponte trancou a origem depois de 5 provas erradas. |
| `sem resposta`, `conexão caiu`, `desconectado` | A rede ou a ponte saiu do ar. O app reconecta sozinho. |
| `prévia: …` | A prévia do menu está rodando. |

## O menu

Arraste a tela para cima, ou gire a coroa. O menu tem o visual do aplicativo
de configuração do Orbe: fundo de vidro escuro, cartões e as cores do tema do
computador.

### Conexão

![Conexão: servidor, token e estado](img/ajustes-conexao.png)

- **Servidor**: o endereço da ponte.
- **Token**: o par do servidor. Aparece só como pontos.
- **Estado**: `conectado`, `conectando…` ou o motivo da falha.

### Sessão de voz

![Sessão de voz](img/ajustes-sessao.png)

- **Aberta / Fechar**: mostra se a sessão de voz está aberta no computador, com
  o estado dela (por exemplo, `parado`), e a abre ou fecha, como o atalho de
  teclado do orbe.
- **Travar a sessão**: faz dois toques no orbe travarem a sessão.

### Avatar do orbe

![Avatares e tamanho](img/ajustes-avatar.png)

Seis avatares, em miniaturas vivas. Escolher um troca o orbe do relógio. O
controle **Tamanho** vai de 60% a 130% do mostrador e mostra a figura no
tamanho escolhido.

### Aparência, voz e prévia

![Glitch, texto, voz e prévia](img/ajustes-voz.png)

| Opção | O que faz |
|---|---|
| **Glitch** | Aberração cromática, faixas arrancadas e linhas de varredura. |
| **Texto do raciocínio** | Mostra as linhas do agente abaixo do orbe. |
| **Seguir o orbe do PC** | O avatar e o glitch vêm do computador. Desligado, valem os escolhidos no relógio. |
| **Microfone do relógio** | Segurando o orbe, a fala vem do relógio e não do computador. O app pede a permissão de microfone uma vez, quando a ponte aceita fala. |
| **Voz no relógio** | A resposta em voz toca no relógio. Desligada, ela sai no computador (pelo daemon) ou vem em texto (orbe de pulso). |
| **Voz também no PC** | Com a ponte do daemon e a voz no relógio ligada, a resposta toca nos dois. |
| **Vibrar** | Vibra ao segurar e ao soltar o orbe. |
| **Pré-visualizar** | O orbe passa por todos os estados, sem ponte nem agente, para ver o avatar escolhido. |

## Avatares

Os mesmos seis do Orbe do computador, desenhados pelos mesmos shaders:

![Os seis avatares](img/skins.png)

Falando, com as linhas do agente embaixo:

![Os seis avatares falando](img/skins-falando.png)

| Avatar | Como é feito |
|---|---|
| **Ophanim** | Anéis de olhos, desenhados por `figura.frag`. |
| **Ophanim com asas** | O mesmo, com asas. |
| **Shoggoth** | Tentáculos e olhos, também por `figura.frag`. |
| **Seraphim (gravura)** | Imagem de gravura animada por `imagem.frag`. |
| **Entidade** | Imagem animada por `imagem.frag`. |
| **Anel de energia** | Atlas de quadros animado por `anel.frag`. |

## Conversando com um agente

O orbe de pulso (`hermes_voice_pulso.py`) faz o caminho inteiro sem o desktop:
a fala do relógio vai para o Groq Whisper, o texto vai para o agente, o
raciocínio volta em linhas e a resposta volta em voz, tocada no relógio.

**Claude Code, por canal.** `claude-orbe` (ou `claude-orbe.cmd` no Windows)
abre uma sessão normal do Claude Code ligada ao orbe por um canal MCP. O que
você diz no relógio chega à sessão como uma mensagem, a resposta sai pelo
`reply` do canal e as permissões são pedidas na própria sessão. Depois,
`./hermes_voice_pulso.py --agente claude`.

**Qualquer agente ACP.** `--comando "<comando do agente>" --pasta <pasta>`
(por exemplo o Claude pelo adaptador da Zed, `npx -y
@zed-industries/claude-agent-acp`). Por ACP, o orbe **aprova sozinho** o que o
agente pedir, como o daemon faz: escolha a `--pasta` com isso em mente.

**O agente do `config.json`.** Sem argumentos, vale o agente configurado para
o daemon.

Com o terminal do orbe de pulso aberto, uma linha digitada vale por uma fala:
é a forma mais rápida de conferir o agente e a voz sem falar. As chamadas de
ferramenta do agente também aparecem como linhas de raciocínio no relógio. A
resposta tem um teto de duração por agente (120 s para Hermes, OpenCode e
Gemini, 600 s para os demais).

Opções do orbe de pulso:

| Opção | Efeito |
|---|---|
| `--agente NOME` | `hermes`, `opencode`, `gemini`, `claude` (pelo canal) ou `comando`. |
| `--comando CMD` | Agente ACP por linha de comando. |
| `--pasta DIR` | Pasta em que o agente ACP trabalha (padrão: a do usuário). |
| `--perfil NOME` | Perfil do Hermes. |
| `--env ARQ` | Arquivo `.env` com as chaves, além de `~/.hermes/.env`. Pode repetir. Nunca é impresso. |
| `--porta N` | Porta da ponte (padrão: a do `config.json`, 8777). |
| `--debug` | Log detalhado. |

## Sessão aberta pelo relógio

Com a ponte servida pelo daemon, tocar ou segurar o orbe do relógio abre a
sessão de voz do computador, e ela passa a ser do relógio até fechar:

- **O agente é o Claude**, qualquer que seja o do `config.json` (que continua
  valendo para o atalho e a palavra de ativação). Sem uma sessão do Claude
  aberta com o canal do orbe, o daemon abre uma num terminal no computador:
  `<relogio.terminal> -e claude-orbe --dangerously-skip-permissions` (o
  padrão é o Ghostty), na pasta de `relogio.claude_pasta` (vazio = a pasta do
  usuário). As ferramentas são aprovadas sozinhas, como o orbe faz por ACP, e
  o detalhe do que ele faz fica na janela. A janela abre num escopo próprio do
  systemd, então reiniciar o serviço do orbe não a fecha; fechar a janela
  encerra o Claude, e o próximo uso do relógio abre outra.
- **O orbe do computador abre junto**, com as íris dos olhos em vermelho
  (Ophanim, Ophanim com asas e Shoggoth; as skins de imagem e o anel não têm
  olho separado).
- **O microfone do computador sai da conversa**: a fala vem só do relógio.
- **A voz toca onde o relógio pediu**: no relógio, no computador ou nos dois
  (chaves "Voz no relógio" e "Voz também no PC").

Na primeira vez, o Claude pede na janela uma confirmação do modo sem
permissões, que só o dono da máquina pode dar. Enquanto ela não vem, o
relógio mostra "O Claude não abriu o canal: veja o terminal no PC".

## Rede

O relógio precisa alcançar o computador. Três situações comuns:

- **Mesma rede Wi-Fi.** Digite o IP que a ponte mostrou.
- **Redes separadas** (o relógio no Wi-Fi do modem e o computador atrás de
  outro roteador, por exemplo). O computador alcança o relógio, mas o relógio
  não alcança o computador. Leve a porta pelo próprio adb e aponte o app para
  o próprio relógio:

  ```sh
  adb -s <serial-do-relogio> reverse tcp:8777 tcp:8777
  # no app: servidor 127.0.0.1:8777
  ```

  Isso vale enquanto o adb estiver conectado. A porta da depuração por Wi-Fi
  do relógio muda a cada ativação, e a conexão pode cair quando a tela
  apaga por muito tempo.
- **Fora de casa.** Use uma VPN (Tailscale, WireGuard) ou um proxy com TLS.

## Segurança

- **O token não passa pela rede.** Ao conectar, a ponte manda um sal novo, e o
  relógio responde com `PBKDF2-HMAC-SHA256(token, sal, 60 000 iterações)`.
  Quem só escuta a rede vê uma prova que serve para aquela conexão e que é
  cara de adivinhar. O token tem 8 caracteres de um alfabeto sem `l`, `1`, `0`
  e `o`, para digitar no pulso.
- **Tentativas limitadas.** Cinco provas erradas trancam a origem
  (`muitas tentativas`).
- **O resto vai em claro.** Depois da prova, o raciocínio e a voz trafegam sem
  criptografia. Em redes que não são de confiança, ponha a ponte atrás de um
  proxy com TLS (o relógio aceita `wss://`) ou numa VPN.
- **A ponte vem desligada** no daemon, e o orbe de pulso só abre a porta
  enquanto roda.
- **As chaves ficam no computador.** O relógio nunca vê `GROQ_API_KEY` nem
  `GEMINI_API_KEY`.
- O app declara `usesCleartextTraffic` porque a ponte local fala `ws://`. O
  backup do Android e a extração de dados do app estão desligados.

## Protocolo da ponte

Um WebSocket. Mensagens de texto são uma linha cada; as binárias são PCM
`s16le` mono.

| Sentido | Mensagem | Quando |
|---|---|---|
| ponte → relógio | `desafio <sal em hex>` | Ao conectar. |
| relógio → ponte | `ola {"prova": "...", "nome": "...", "voz": true, "voz_pc": false}` | A prova do token. `voz` pede a resposta em áudio no relógio; `voz_pc`, também no PC. |
| ponte → relógio | `ola {"v": 1, "orbe": {...}, "tema": {...}, "microfone": true, "voz": true, "voz_pc": true}` | Pareado: a aparência e o que a ponte aceita (`voz_pc`: o PC também tem voz, só no daemon). |
| ponte → relógio | `show idle`, `state thinking`, `level 0.42 0.60`, `mic 0.3`, `line <texto>`, `hold 1`, `hide`, `clear` | As linhas do orbe, as mesmas do desktop. |
| ponte → relógio | `config {"orbe": {...}, "tema": {...}}` | O avatar, o glitch ou o tema mudaram no computador. |
| relógio → ponte | `touch down`, `touch up` | O dedo no orbe. |
| relógio → ponte | `toggle`, `trigger`, `dismiss`, `hold`, `release` | Os comandos do `orb_control`. |
| relógio → ponte | *(binário)* | A fala, em quadros de 30 ms a 16 kHz, enquanto o dedo segura o orbe. |
| ponte → relógio | `voz 24000`, *(binário)*, `voz fim`, `voz corta` | A resposta em voz (taxa do áudio, o áudio, o fim, calar já). No orbe de pulso, e no daemon quando a sessão é do relógio. |
| relógio → ponte | `voz acabou` | O relógio tocou até o fim. |

Códigos de fechamento: `4401` token recusado, `4429` muitas tentativas,
`1013` cliente lento demais. A ponte guarda o estado do orbe e o reenvia a
quem conecta no meio de uma conversa. As linhas de nível (`level`, `mic`) são
descartadas para um relógio lento, para a imagem não atrasar.

## Por dentro do app

O app é Kotlin com Jetpack Compose para Wear OS (pacote `io.hermes.orbe`). O
orbe não usa Compose: é OpenGL ES 3.0 direto, como o Qt Quick do desktop.

```
orbe-wear/app/src/main/java/io/hermes/orbe/
├── MainActivity.kt       entrada: extras do adb, permissão, teclado do relógio
├── OrbeViewModel.kt      toque, áudio, ponte, prévia
├── dados/
│   ├── Ponte.kt          WebSocket (OkHttp), reconexão, desafio-resposta
│   ├── Protocolo.kt      prova PBKDF2, "ola", URL do servidor
│   ├── Ajustes.kt        preferências (DataStore)
│   ├── Microfone.kt      AudioRecord, 16 kHz
│   └── AltoFalante.kt    AudioTrack em fila; mede nível e tom do PCM
├── gl/
│   ├── Motor.kt          um contexto EGL e uma thread para todos os orbes
│   ├── Oficina.kt        programas, cache de binários, texturas
│   ├── Sombreador.kt     converte os .frag do desktop para GLSL ES 3.00
│   └── OrbeView.kt       a superfície (TextureView) de cada orbe
├── orbe/
│   ├── Figura.kt  Anel.kt   portes de Figura.qml e Anel.qml
│   ├── Cena.kt              o estado do orbe (OrbeConteudo.qml), mini-cenas
│   ├── Skin.kt              os seis avatares
│   └── Quebra.kt            quebra de linha do raciocínio
└── ui/                      Compose: tema, componentes, tela do orbe, menu
```

**Uma fonte só para a arte.** O build copia os shaders `.frag`, os atlas e as
imagens de `orbe-qt` para os assets do app. Nada é duplicado no git: o orbe do
relógio muda quando o do desktop muda.

**Shaders do desktop, no relógio.** Os `.frag` do Qt estão em GLSL 440. No
carregamento, `Sombreador` os converte para GLSL ES 3.00: o cabeçalho passa a
`#version 300 es` com `precision`, o bloco `std140` do Qt vira uniformes
soltos, os `layout` de entrada e de textura saem e as variantes que o
`build.sh` passa por `-D` (`SKIN`, `IMG`) viram `#define`. Os testes de
unidade confirmam a conversão, e os shaders convertidos foram validados com o
compilador de referência da Khronos.

**Dois passes por quadro.** O orbe é desenhado em um passe de máscara (a figura
inteira num framebuffer) e outro de pós-processamento (`pos.frag`: cor,
aberração, glitch). A máscara é a parte cara.

**Um contexto para todos.** O menu mostra várias miniaturas vivas. Todas
compartilham um contexto EGL e uma thread de render. Fora da tela, uma
miniatura não é desenhada; com o menu rolando, elas esperam paradas, e em
repouso saem duas por quadro, em rodízio.

**Cache de programas.** A primeira compilação de um shader pesado leva
segundos num relógio. O binário do programa é guardado e carregado nas
aberturas seguintes. Se a GPU recusar o próprio binário (o que o emulador
faz), o cache é desligado para aquela GPU.

**Qualidade adaptativa.** A resolução da máscara do orbe grande se ajusta à
GPU do relógio, avatar por avatar, e o que se aprendeu é lembrado entre as
aberturas. O critério são os quadros que perdem a vez, não o custo medido,
porque a GPU baixa a frequência quando sobra tempo e o custo engana. Com a
maioria dos quadros atrasada por duas janelas de 2 s, a máscara desce até onde
os quadros cabem (piso de 37,5%); depois de meio minuto sem atraso, sobe um
degrau.

**Áudio.** O microfone é um `AudioRecord` a 16 kHz mono, com um segundo de
pré-rolagem. A resposta chega em PCM e toca por um `AudioTrack` em fila, com
corte imediato quando você fala por cima. O nível e o tom que movem a figura
são medidos do próprio áudio, em janelas de 40 ms.

## No TicWatch Pro 5

![O app num TicWatch Pro 5 de verdade](img/ticwatch.png)

Capturas do app num TicWatch Pro 5 Enduro (Wear OS, tela de 466 px, Adreno 702).
As demais imagens deste documento vêm do emulador do Wear OS. O emulador usa a
GPU do computador e esconde o custo real do desenho.

| Medida | Resultado |
|---|---|
| Compilar o shader do Ophanim | 2,2 s na primeira vez; de 15 a 150 ms com o cache |
| Ophanim, máscara a 100% | cerca de 150 ms por quadro |
| Ophanim com a qualidade adaptativa | máscara a cerca de 38%, de 25 a 30 quadros por segundo |
| Anel de energia | máscara a 100%, de 25 a 30 quadros por segundo |
| Rolagem do menu | mediana de quadro de 24 ms, com engasgos ocasionais |

O Ophanim fica um pouco mais suave que no computador, pelo ajuste de
resolução. O anel roda inteiro.

## Compilar, testar e depurar

```sh
cd orbe-wear
./gradlew :app:assembleRelease          # APK em app/build/outputs/apk/release/
./gradlew :app:assembleDebug
./gradlew :app:testDebugUnitTest        # 20 testes de unidade
./gradlew :app:lintRelease
```

Os testes cobrem a conversão dos shaders (`SombreadorTest`), o estado e a
animação do orbe (`OrbeCenaTest`) e a quebra de linha do raciocínio
(`QuebraTest`). Os testes de shader leem os `.frag` de `orbe-qt` e gravam os
convertidos em `app/build/shaders-es`, onde dá para conferi-los ou passá-los
por um compilador GLSL ES.

**Diagnóstico de desempenho no relógio:**

```sh
adb shell setprop log.tag.Orbe VERBOSE      # liga
adb logcat -s Orbe
adb shell setprop log.tag.Orbe INFO         # desliga
```

A cada 2 s o log mostra os quadros por segundo, a fração de quadros
atrasados, a resolução da máscara e o custo do passe. O modo VERBOSE põe uma
espera da GPU por quadro para medir: desligue depois.

Para travar a qualidade da máscara numa medição:

```sh
adb shell am start -n io.hermes.orbe/.MainActivity --ef qualidade 0.5
```

**Emulador.** Um AVD do Wear OS redondo serve. O computador aparece para o
emulador como `10.0.2.2`, então o servidor é `10.0.2.2:8777`.

**Testar a ponte sem relógio e sem agente:**

```sh
./hermes_voice_relogio.py --demo --porta 8777
```

## Problemas comuns

<p>
<img src="img/rodape-recusado.png" width="200" align="right" alt="Rodapé do app com a mensagem token recusado">
</p>

**`token recusado`.** O token do relógio não é o da ponte. Rode
`./hermes_voice_relogio.py` para ver o atual, ou `--novo-token` para trocar, e
digite de novo (o alfabeto não tem `l`, `1`, `0` nem `o`). Se o relógio tentou
errado cinco vezes, a ponte o trancou: reinicie a ponte.

**`sem resposta` ou `conectando…` sem fim.** O relógio não alcança o
computador. Confira o IP, o firewall (porta 8777) e se estão na mesma rede. Em
redes separadas, use o `adb reverse` da seção [Rede](#rede).

**O orbe não ouve.** Confira, no menu, **Microfone do relógio** ligado e a
permissão de microfone concedida ao app. Sem a permissão, segurar o orbe não
envia fala.

**Não sai voz no relógio.** **Voz no relógio** só existe com a ponte servida
pelo orbe de pulso, e as chaves de transcrição e voz precisam estar
disponíveis (`--env`).

**Rolagem do menu engasga.** As miniaturas vivas dividem a GPU com a rolagem.
Elas já esperam paradas enquanto a tela rola, mas num relógio de GPU modesta
ainda há engasgos ocasionais.

**O adb do relógio caiu.** A depuração por Wi-Fi do relógio pode cair com a
tela apagada, e a porta muda a cada ativação. Ligue de novo, veja a porta nova
nas opções do desenvolvedor e reconecte (`adb connect <ip>:<porta>`). O
`adb reverse` precisa ser refeito.

## Limites conhecidos

- A ponte servida pelo **daemon** foi testada com um relógio simulado (prova
  do token, voz, `voz_pc`, origem da sessão) e com o worker de voz de verdade,
  mas ainda não de ponta a ponta com o relógio e o Claude aberto por ele.
- A voz e o microfone com um agente de verdade foram testados no emulador. No
  TicWatch Pro 5 foram conferidos o desenho, o pareamento e o desempenho.
- Por ACP, o agente tem as permissões aprovadas automaticamente.
- O tráfego depois do pareamento não é criptografado sem TLS ou VPN.
- Só Wear OS. macOS não foi testado.
- Menu com engasgos ocasionais em GPUs modestas.

## Créditos

O Orbe, o protocolo do orbe, os shaders e a arte são de Davi Bezerra
([bbarrosdavi/orbe](https://github.com/bbarrosdavi/orbe)). O Orbe Watch os leva
para o pulso sem copiá-los: o build usa os de `orbe-qt`.
