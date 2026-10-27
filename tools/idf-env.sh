#!/usr/bin/env bash
# Ativa o ambiente ESP-IDF 5.4.x. Uso (source): . tools/idf-env.sh
export IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v5.4}"
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh"
