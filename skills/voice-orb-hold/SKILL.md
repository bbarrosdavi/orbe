---
name: voice-orb-hold
description: Use when the user asks Jarvis to keep the voice session open — segura a sessão, fica aberto, não desliga, me espera, espera aí, continua ouvindo, não some. Also handles the opposite (solta a sessão, pode fechar depois).
---

# Segurar a sessão de voz aberta

Por padrão a sessão de voz fecha sozinha após 10 segundos sem fala, e o orbe some.
Quando o usuário pedir para **segurar a sessão** (ou "fica aberto", "não desliga",
"espera aí", "me espera", "continua ouvindo"), desligue esse timeout:

```bash
/usr/bin/python3 @ORBE@/orb_control.py hold
```

Confirme com **uma frase curta** ("Segurando." / "Fico aqui.") e nada mais. Não
liste sessões, não busque contexto, não despeje markdown.

A partir daí a sessão dura até o usuário dispensar explicitamente (a skill
`voice-orb-dismiss` cuida disso). Há um teto de segurança de 30 minutos sem
nenhuma fala detectada, para um hold esquecido não deixar o microfone armado
para sempre.

## Soltar sem encerrar

Se ele pedir para **soltar** a trava mas continuar a conversa ("pode soltar",
"volta ao normal", "não precisa mais segurar"), devolva o timeout sem fechar:

```bash
/usr/bin/python3 @ORBE@/orb_control.py release
```

Não confunda com dispensa: `release` mantém a sessão viva, só volta a contar os
10 segundos. Se ele quer que você vá embora, é `voice-orb-dismiss`.
