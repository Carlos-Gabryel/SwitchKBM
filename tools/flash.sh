#!/usr/bin/env bash
# Grava o firmware switch-side e abre o monitor serial. Uso: tools/flash.sh [/dev/ttyUSB0]
set -e
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$(dirname "${BASH_SOURCE[0]}")/idf-env.sh"

port="$1"
if [ -z "$port" ]; then
    ports=(/dev/ttyUSB* /dev/ttyACM*)
    [ -e "${ports[0]}" ] || { echo "Nenhuma porta /dev/ttyUSB* ou /dev/ttyACM* encontrada. Use: tools/flash.sh /dev/ttyUSB0" >&2; exit 1; }
    port="${ports[0]}"
    echo "Porta detectada: $port"
fi
idf.py -C "$root/switch-side" -p "$port" flash monitor
