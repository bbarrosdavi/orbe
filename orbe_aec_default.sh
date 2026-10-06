#!/usr/bin/bash
# Aponta a fonte padrao do PipeWire para o microfone com cancelamento de eco,
# e sabe desfazer.
#
# O `restore` NAO adivinha qual era o microfone: o `set` grava o nome da fonte
# padrao anterior num arquivo de runtime. Adivinhar pelo primeiro `alsa_input`
# da lista devolve o no errado (neste host o primeiro e o Mic2, e o ativo e o
# Mic1), e um nome fixo no arquivo quebra em qualquer troca de hardware.
set -u

AEC=orbe_aec_source
PREV="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/orbe-aec.prev"

esperar_no() {
    for _ in $(seq 1 25); do
        pactl list short sources 2>/dev/null | grep -q "$AEC" && return 0
        sleep 0.4
    done
    return 1
}

case "${1:-set}" in
set)
    if ! esperar_no; then
        echo "orbe-aec: fonte '$AEC' nao apareceu; o modulo do PipeWire subiu?" >&2
        exit 1
    fi
    atual=$(pactl get-default-source 2>/dev/null || true)
    if [ -n "$atual" ] && [ "$atual" != "$AEC" ]; then
        printf '%s\n' "$atual" >"$PREV"
    fi
    pactl set-default-source "$AEC"
    ;;
restore)
    alvo=""
    [ -r "$PREV" ] && alvo=$(cat "$PREV")
    # Só aceita o que ainda existe: o no pode ter sumido com troca de perfil.
    if [ -z "$alvo" ] || ! pactl list short sources 2>/dev/null | grep -q "[[:space:]]$alvo[[:space:]]"; then
        # Ultimo recurso: primeira entrada de hardware que nao esteja suspensa.
        alvo=$(pactl list short sources 2>/dev/null \
               | awk '$2 ~ /^alsa_input\./ && $2 !~ /monitor/ && $NF != "SUSPENDED" {print $2; exit}')
    fi
    [ -n "$alvo" ] && pactl set-default-source "$alvo"
    rm -f "$PREV"
    ;;
*)
    echo "uso: $(basename "$0") set|restore" >&2
    exit 2
    ;;
esac
