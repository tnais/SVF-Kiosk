#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="${repo_root}/.venv"

if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "ERRORE: Python 3 non è installato o non è disponibile nel PATH." >&2
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    printf '%s\n' "ERRORE: SVF Kiosk richiede Python 3.11 o successivo." >&2
    exit 1
fi

printf '%s\n' "Creazione dell'ambiente virtuale .venv..."
python3 -m venv "${venv_dir}"

printf '%s\n' "Installazione di SVF Kiosk e delle dipendenze..."
"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install --editable "${repo_root}"

printf '%s\n' "Ambiente pronto. Attivarlo con: source .venv/bin/activate"
