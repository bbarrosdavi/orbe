# Orbe

Assistente de voz para agentes de IA no Wayland e no macOS. Você fala, o agente responde
em voz, e um orbe animado no canto da tela mostra o estado da conversa
(ouvindo, pensando, respondendo) e as linhas do raciocínio do agente.

Funciona com qualquer agente que fale ACP (Agent Client Protocol), como
Hermes Agent, OpenCode e Gemini CLI, e com o Claude Code por um canal MCP.

> **Orbe Watch.** O Orbe também vive no pulso: um app Wear OS com o mesmo
> desenho e a mesma estética, que serve de ponte de fala para os agentes.
> Documentação completa, com imagens, no repositório [orbe-watch](https://github.com/bbarrosdavi/orbe-watch).

<p align="center">
<a href="https://github.com/bbarrosdavi/orbe-watch"><img src="https://raw.githubusercontent.com/bbarrosdavi/orbe-watch/main/docs/img/ciclo.gif" width="240" alt="O orbe no relógio"></a>
</p>

<table align="center">
<tr>
<td align="center"><img src="imagens/orbe-ofanim.gif" width="400" alt="Ophanim"><br>Ophanim</td>
<td align="center"><img src="imagens/orbe-ofanim-alado.gif" width="400" alt="Ophanim com asas"><br>Ophanim com asas</td>
</tr>
<tr>
<td align="center" colspan="2"><img src="imagens/orbe-anel.gif" width="400" alt="Anel de energia"><br>Anel de energia</td>
</tr>
</table>

Cada avatar passa por ouvindo, pensando (com as linhas do raciocínio ao lado)
e respondendo, gravado na área de trabalho.

## O que ele faz

- **Ativação** por atalho de teclado, toque no orbe ou palavra de ativação
  local (openWakeWord, sherpa-onnx com frase livre ou microWakeWord). O
  toque vale com o dedo, em telas touchscreen, e com o clique do cursor.
- **Transcrição** pelo Groq Whisper; **síntese** por Gemini, xAI ou Piper
  (local).
- **Conversa por voz**: falar por cima interrompe (opcional), "tchau"
  dispensa o orbe, "fica" trava a sessão aberta e "pode soltar" destrava.
  Dois toques (ou cliques) no orbe também travam.
- **Avatares desenhados na GPU**: Ophanim, Ophanim com asas, Seraphim
  (gravura) e anel de energia, cada um com o seu tamanho, com glitch, sombra
  opcional e o texto do raciocínio ao lado ou abaixo do orbe.
- **App de configuração** com prévia ao vivo que passa por todos os estados.
- **No pulso**: um app para Wear OS desenha o mesmo orbe no relógio, mostra o
  raciocínio e deixa tocar e segurar para falar pelo microfone dele. Sem o
  desktop, o relógio fala com o agente e toca a resposta
  ([Relógio](#relógio-wear-os)).

<p align="center">
<img src="imagens/menu-agente.gif" width="260" alt="App: aba Agente">
<img src="imagens/menu-ativacao.gif" width="260" alt="App: aba Ativação">
<img src="imagens/menu-voz.gif" width="260" alt="App: aba Voz">
<img src="imagens/menu-conversa.gif" width="260" alt="App: aba Conversa">
<img src="imagens/menu-aparencia.gif" width="260" alt="App: aba Aparência">
</p>

## Requisitos

- Linux com um compositor Wayland que tenha layer-shell. Testado no niri 26.04.
- [Quickshell](https://quickshell.org) 0.3 ou mais novo (comando `qs`), que
  desenha o orbe.
- PipeWire (`pw-record`, `wpctl`).
- PySide6 no Python do sistema, para o app.
- Python 3.11 ou 3.12 para o daemon (o worker de voz usa `audioop`, que saiu
  no 3.13) com `numpy scipy sounddevice webrtcvad requests onnxruntime
  websockets pyyaml`. Opcionais: `openwakeword` e `sherpa-onnx` (palavra de
  ativação) e `piper-tts` (voz local).
- Uma chave do [Groq](https://console.groq.com) para a transcrição.
- `qt6-shadertools`, só se for alterar os shaders (os `.qsb` já vêm
  compilados).

No Arch:

```sh
sudo pacman -S quickshell pyside6 pipewire uv
```

## Instalação

```sh
git clone https://github.com/bbarrosdavi/orbe-desktop.git ~/.local/share/orbe
cd ~/.local/share/orbe

# Python do daemon (pule se já usa o venv do Hermes Agent); o uv baixa o 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv numpy scipy sounddevice webrtcvad requests onnxruntime websockets pyyaml

ORBE_PY="$PWD/.venv/bin/python" ./install.sh
```

O `install.sh` cria o serviço do usuário (`hermes-voice.service`), o atalho
"Orbe" no lançador de aplicativos e, se o Hermes estiver instalado, as skills
que deixam o agente segurar e dispensar a sessão. Sem `ORBE_PY`, ele usa o venv
do Hermes Agent, se existir, ou o `python3` do PATH.

Depois:

1. Ponha a chave do Groq em `~/.hermes/.env`:
   ```sh
   mkdir -p ~/.hermes && echo 'GROQ_API_KEY=gsk_...' >> ~/.hermes/.env
   ```
   Para síntese pelo Gemini, acrescente `GEMINI_API_KEY=...` no mesmo arquivo.
2. Abra o app **Orbe** e escolha o agente, a ativação e a voz. O botão
   "Pré-visualizar" mostra o orbe passando por todos os estados.
3. Ligue o serviço:
   ```sh
   systemctl --user enable --now hermes-voice
   ```

### Atalho de teclado

O atalho chama `orb_control.py toggle`. No niri, em qualquer arquivo de binds:

```kdl
Mod+A hotkey-overlay-title="Voice Assistant (Orb)" { spawn "/caminho/do/orbe/orb_control.py" "toggle"; }
```

O app troca a tecla desse bind se ele estiver em `~/.config/niri/dms/binds.kdl`.
Em outros compositores, ligue qualquer tecla a `orb_control.py toggle`.

### Claude Code

Abra o Claude com `./claude-orbe` no lugar de `claude` e escolha "Claude Code"
como agente do orbe em uso, na aba Agente do app (cada skin tem o seu agente,
o mesmo no PC e no relógio). O orbe passa a falar com aquela sessão e, se você
ligar "Falar as etapas" (aba Conversa do app ou aba Voz do relógio), fala também
as etapas enquanto ela trabalha: a descrição de cada ferramenta, a linha que o
terminal mostra com o ponto, traduzida para o português ou como veio. No Windows, o
lançador é o `claude-orbe.cmd` (ver [Relógio](#relógio-wear-os)).

As sessões abertas à mão, com `claude`, o relógio alcança por um hook do
usuário: `./hermes_voice_sessao.py --instalar` o põe no
`~/.claude/settings.json`. No relógio, cada sessão aberta é uma instância dos
orbes do Claude, que se passa com dois dedos, na sua cor e com a pasta e o
estado embaixo, e o orbe fala só a resposta ao pedido de voz (ver [Sessões do
Claude Code](https://github.com/bbarrosdavi/orbe-watch#sessões-do-claude-code)). Pelo hook, o pedido
aparece no terminal só como "Pedido do orbe de voz"; pelo canal, o `claude-orbe`
cola a fala inteira no prompt e dá Enter, como se fosse digitada, com o código
do pedido no fim. Com algo já digitado no prompt ou um diálogo aberto, ele não
cola, e o pedido vai como mensagem de canal, que o Claude Code mostra numa
linha cortada em 60 caracteres (o Claude recebe o texto inteiro). Para o `claude`
digitado à mão já abrir com o canal, há uma função para o `~/.bashrc` no mesmo
trecho.

### Num terminal ou em segundo plano

Cada agente roda num de dois jeitos, escolhido na aba Agente do app ("Onde
cada agente roda", `agente.modos` no `config.json`):

- **Num terminal** (o padrão do Claude Code, do OpenCode e do Gemini CLI): sem
  sessão aberta, o orbe abre uma janela de `agente.terminal` (o Ghostty, de
  padrão) com o agente, na pasta de `agente.claude_pasta`. O pedido de voz
  aparece no chat da janela, como digitado, e o detalhe do trabalho fica nela.
  O Claude vem pelo `claude-orbe`; os outros pelo `hermes_voice_terminal.py`,
  que roda o agente num pseudo-terminal e lê a resposta pelo que cada um
  oferece: no OpenCode, a API do servidor da TUI (`--port`), que também põe o
  pedido no prompt; no Gemini CLI, hooks; no Hermes, o espelho de eventos da
  TUI (`HERMES_TUI_SIDECAR_URL`). No Gemini e no Hermes o pedido é colado no
  prompt e entra com Enter, com as mesmas travas do `claude-orbe`: só com o
  prompt vazio e sem diálogo aberto. Interromper só solta a espera; o agente
  segue o que estiver fazendo na janela. O modelo escolhido no app vale só
  por ACP: na janela, vale o do agente.
- **Em segundo plano** (o padrão do Hermes): sem janela. Os ACP rodam como
  antes; o Claude abre com `claude --bg --dangerously-skip-permissions` e ouve
  o orbe pelo hook de sessão (`hermes_voice_sessao.py --instalar`), e o
  Encerrar o para com `claude stop`, guardando a conversa.

Os hooks do Gemini ficam no `~/.gemini/settings.json`, postos na primeira
janela do Gemini aberta pelo orbe (com cópia em `settings.json.orbe-bak`).
Fora de uma janela do orbe eles saem sem fazer nada; para tirar:
`./hermes_voice_terminal.py --remover-gemini`. Desde a 0.62, o Gemini só roda
hooks em pasta confiada (`~/.gemini/trustedFolders.json`): fora delas, o orbe
diz que o Gemini não confia na pasta.

No relógio, cada janela aberta é uma instância dos orbes daquele agente, como
as sessões do Claude; no PC, o atalho fala com a janela mais recente do agente
da skin em uso, ou abre uma.

### Cancelamento de eco (opcional)

Para interromper o agente falando por cima sem que ele ouça a própria voz:

```sh
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp pipewire-hermes-aec.conf ~/.config/pipewire/pipewire.conf.d/99-hermes-echo-cancel.conf
systemctl --user restart pipewire
sed -e "s|@ORBE@|$PWD|g" hermes-aec.service.unit > ~/.config/systemd/user/hermes-aec.service
systemctl --user daemon-reload && systemctl --user enable --now hermes-aec
```

## Relógio (Wear OS)

<p align="center">
<img src="https://raw.githubusercontent.com/bbarrosdavi/orbe-watch/main/docs/img/relogio.png" width="760" alt="O Orbe no relógio: ouvindo, pensando com as linhas do raciocínio, e o menu">
</p>

O app do relógio mora no repositório [orbe-watch](https://github.com/bbarrosdavi/orbe-watch), com a
documentação completa e as telas do app.

O `orbe-watch` é o orbe no pulso: o mesmo desenho, feito na GPU do relógio com os
shaders do `orbe-qt` (o build leva os `.frag` e os atlas; nada é copiado no
git), e um menu no estilo do app. Como o orbe do desktop, ele é só a ponte de
fala: quem responde é o agente. O relógio conversa por um WebSocket na rede
local (`hermes_voice_relogio.py`), servido de um de dois jeitos:

- **pelo daemon**, no Linux com o desktop: o orbe do relógio acompanha o do
  computador, e a resposta em voz sai no computador;
- **pelo orbe de pulso** (`hermes_voice_pulso.py`), sem o desktop e fora do
  Linux: o microfone e o alto-falante são os do relógio.

Nos dois, o toque vale como no desktop (um toque abre a sessão ou interrompe,
dois travam, segurar é segurar para falar, com a fala captada pelo relógio),
as linhas do raciocínio aparecem abaixo da figura, e o avatar, o glitch e as
cores seguem os do computador, ou o relógio escolhe os dele.

### Pelo daemon

Ligue a ponte na aba Ativação do app (grupo Relógio), ou pela linha de
comando:

```sh
./hermes_voice_relogio.py --ligar      # liga a ponte e mostra o endereço e o token
systemctl --user restart hermes-voice
```

Ligada, a ponte abre a porta 8777 para a rede local (libere-a no firewall, se
houver um) e só conversa com quem tem o token. Desligada, que é o padrão, o
daemon não abre porta nenhuma.

### Sem o desktop

O orbe de pulso faz só o caminho do relógio: a fala vai para o Groq Whisper, o
texto vai para o agente, o raciocínio volta em linhas e a resposta volta em
voz, tocada no relógio. É Python puro, sem PipeWire nem Wayland, e foi testado
no Windows. Precisa de Python 3.11 ou mais novo com `websockets` e
`requests`, e das chaves `GROQ_API_KEY` e `GEMINI_API_KEY` no ambiente, em
`~/.hermes/.env` ou num arquivo passado com `--env`.

```sh
# a sessão do Claude Code que estiver aberta com o canal do orbe
./claude-orbe                  # no Windows: claude-orbe.cmd
./hermes_voice_pulso.py --agente claude

# ou um agente ACP qualquer, numa pasta (aqui, o Claude pelo adaptador da Zed)
./hermes_voice_pulso.py --comando "npx -y @zed-industries/claude-agent-acp" --pasta ~/projeto
```

Sem argumentos, o agente é o do `config.json`, o mesmo do daemon. Ao subir, o
orbe de pulso mostra o endereço e o token para o relógio; com o terminal
aberto, uma linha digitada vale por uma fala, para conferir o agente e a voz.
Com a "Voz no relógio" desligada no menu, a resposta vem em texto.

Pelo canal, o Claude pede as permissões na própria sessão. Por ACP, o orbe
aprova sozinho o que o agente pedir, como no daemon: escolha a `--pasta` com
isso em mente.

### O app do relógio

No relógio (Wear OS 3 ou mais novo), com o Android SDK instalado
(`ANDROID_HOME` ou `local.properties`):

```sh
git clone --recursive https://github.com/bbarrosdavi/orbe-watch.git
cd orbe-watch
./gradlew :app:assembleRelease
adb install app/build/outputs/apk/release/app-release.apk
# o endereço e o token, sem digitar no pulso
adb shell am start -n io.hermes.orbe/.MainActivity --es servidor 192.168.0.10 --es token abcd2345
```

O endereço e o token também entram pelo menu do relógio (arraste a tela para
cima ou gire a coroa). Para ver o relógio funcionando sem daemon nem agente,
`./hermes_voice_relogio.py --demo` serve o ciclo da prévia do app.

O relógio precisa alcançar o computador pela rede. Com os dois em redes
separadas (o relógio no Wi-Fi do modem e o computador atrás de outro
roteador, por exemplo), `adb reverse tcp:8777 tcp:8777` leva a porta pelo
próprio adb, e o servidor no relógio passa a ser `127.0.0.1:8777`, enquanto o
adb estiver conectado.

Testado no emulador do Wear OS e num TicWatch Pro 5 (Adreno 702). A resolução
do desenho se ajusta sozinha à GPU do relógio, skin por skin: nele, o anel de
energia roda inteiro e o Ophanim, a pouco menos da metade, os dois a 25 a 30
quadros por segundo. `adb shell setprop log.tag.Orbe VERBOSE` mostra a conta
no logcat.

O token não passa pela rede (o relógio prova que o tem, com um desafio novo a
cada conexão), mas o resto da conversa vai em claro: fora de uma rede de
confiança, ponha a ponte atrás de um proxy com TLS (o relógio aceita `wss://`)
ou numa VPN.

## macOS

No Mac o orbe é uma janela PySide6 (`orbe-qt/orbe_mac.py`) com os mesmos
avatares, shaders (compilados também para Metal) e protocolo; o resto do
daemon é o mesmo. Requisitos: macOS 12 ou mais novo, [uv](https://docs.astral.sh/uv/)
(`brew install uv`) e, para os agentes, os mesmos binários do Linux
(`hermes`, `opencode`, `gemini`, `claude`).

```sh
git clone https://github.com/bbarrosdavi/orbe-desktop.git ~/.local/share/orbe
cd ~/.local/share/orbe
./install-mac.sh
```

O `install-mac.sh` cria um venv Python 3.11 em `.venv` com as dependências
(PySide6 incluso), baixa o detector de voz Silero, instala o LaunchAgent
`io.hermes.orbe` (sobe no login e volta se cair; log em
`~/Library/Logs/orbe.log`), o app **Orbe** em `~/Applications`, o
`claude-orbe` em `~/.local/bin` e as skills do Hermes. Na primeira sessão o macOS pede acesso ao microfone para o Python
do venv: aceite (ou ative em Ajustes do Sistema › Privacidade e Segurança ›
Microfone). `./install-mac.sh --remover` desfaz tudo menos o config.

O que muda em relação ao Linux:

- **Atalho**: `Ctrl+Option+O` por padrão, global, sem pedir permissão de
  Acessibilidade. Troque na aba Ativação do app; `Mod` é a tecla Command.
- **Transcrição**: sem `GROQ_API_KEY`, o daemon transcreve pelo Gemini com a
  mesma `GEMINI_API_KEY` da voz (`voz.stt_provedor` no config força um ou
  outro).
- **Áudio**: CoreAudio pelo `sounddevice`, na entrada e na saída padrão do
  sistema (segue AirPods e afins). O microfone só abre com o orbe ativo. Não
  há cancelamento de eco, então a voz não interrompe a fala do orbe (o toque
  e o atalho, sim); calado, pensando, falar por cima continua valendo.
- **Olhar**: os olhos seguem o cursor em qualquer lugar da tela.
- **Perfil do Hermes**: se o perfil do config não existir (o padrão
  `jarvis`), usa o `default`.

```sh
launchctl kickstart -k gui/$(id -u)/io.hermes.orbe   # reinicia o daemon
tail -f ~/Library/Logs/orbe.log
```

## Modelos locais

Todos opcionais; o daemon procura em `~/.hermes/`:

| Arquivo | Para quê |
|---|---|
| `cache/vad/silero_vad.onnx` | detector de voz Silero (sem ele, usa o webrtcvad) |
| `cache/wakewords/*.onnx`, `*.tflite`, `sherpa-onnx-kws-*` | palavra de ativação; caminhos editáveis no app |
| `piper_models/*.onnx` | voz local do Piper |
| `mww-tf/.venv` | venv com `tensorflow` para o microWakeWord |

`record_and_train_wake.py` e `train_ei_hermes.py` treinam uma palavra de
ativação própria a partir de gravações e de vozes do Piper.

## Controle pela linha de comando

```sh
./orb_control.py toggle    # abre ou fecha uma sessão de voz
./orb_control.py hold      # trava a sessão aberta
./orb_control.py release   # volta a fechar sozinha após o silêncio
./orb_control.py dismiss   # encerra e esconde o orbe
```

## Estrutura

| Arquivo | Papel |
|---|---|
| `hermes_voice_daemon.py` | captura, ativação, VAD, transcrição e orquestração |
| `hermes_voice_acp.py` | cliente ACP: fala com o agente escolhido |
| `hermes_voice_canal.py`, `claude-orbe`, `claude-orbe.cmd` | canal MCP para o Claude Code |
| `hermes_voice_sessao.py` | sessões do Claude Code abertas à mão: lista, hook que acorda a sessão e devolve a resposta |
| `hermes_voice_tts.py` | worker de síntese e reprodução |
| `orbe-qt/orbe.qml` | orbe em Quickshell (layer-shell), desenho em shaders |
| `orbe-qt/orbe_mac.py`, `orbe_mac.qml` | o mesmo orbe no macOS (PySide6, Metal, atalho global) |
| `hermes_voice_play.py` | reprodução do TTS no macOS (o `pw-cat` do Mac) |
| `orbe-qt/app/`, `hermes_voice_app.py` | app de configuração (PySide6 e QML) |
| `orb_control.py` | controle do orbe por socket |
| `hermes_voice_relogio.py` | ponte WebSocket para o relógio |
| `hermes_voice_pulso.py` | orbe de pulso: a ponte de fala do relógio sem o desktop |
| [orbe-watch](https://github.com/bbarrosdavi/orbe-watch) | app do relógio (Wear OS, Kotlin e Compose), em repositório próprio, com os shaders do `orbe-qt` |
| `hermes_voice_config.py` | config única em `~/.config/hermes-voice/config.json` |
| `skills/` | skills do Hermes para segurar e dispensar a sessão |
| `*.service.unit`, `orbe.desktop.in` | modelos preenchidos pelo `install.sh` |
| `install-mac.sh` | instalação no macOS: venv, LaunchAgent e `Orbe.app` |

Para testar os shaders sem abrir nada na tela, `orbe-qt/teste/render.py`
desenha qualquer cena de `orbe-qt/teste/` num PNG:

```sh
QT_QPA_PLATFORM=wayland python3 orbe-qt/teste/render.py orbe-qt/teste/vitrine.qml vitrine.png
```
