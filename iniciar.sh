#!/usr/bin/env bash
# Inicia o Assistente de Relíquias. Usado direto ou pelo autostart do sistema
# (~/.config/autostart). Ativa o venv do projeto e roda o app.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$DIR/venv" ]; then
  echo "venv não encontrado em $DIR/venv — rode 'python3 -m venv venv && pip install -r requirements.txt' primeiro." >&2
  exit 1
fi

exec "$DIR/venv/bin/python" -m app.main
