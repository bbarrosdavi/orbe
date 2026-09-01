---
name: voice-orb-dismiss
description: Use when the user says tchau, cala a boca, dispensa, para de falar, or asks Jarvis to stop/hide the voice orb.
---

# Encerrar o orb de voz

Se o Davi dispensar, mandar calar a boca, dizer tchau, chega, pode ir, vai embora, para de falar, silêncio — **não continue a resposta**. Uma frase no máximo (“Beleza.”) ou nada. Depois execute:

```bash
/usr/bin/python3 /home/davi/.hermes/scripts/orb_control.py dismiss
```

Isso esconde o overlay e pede ao daemon para fechar a sessão de voz. Não liste sessões, não busque contexto, não despeje markdown.
