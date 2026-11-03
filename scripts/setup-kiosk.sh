#!/usr/bin/env bash
# Provision a minimal Debian 12 machine as an SVF Kiosk. Run as root.
set -euo pipefail

OPERATOR="svf-operatore"
INSTALL_DIR="/opt/svf-kiosk"
DATA_DIR="/var/lib/svf-kiosk"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

die() {
    printf '%s\n' "ERRORE: $*" >&2
    exit 1
}

step() {
    printf '%s\n' "==> $*"
}

[ "$(id -u)" -eq 0 ] || die "eseguire come root (sudo)."
[ -r /etc/debian_version ] || die "sistema non Debian."
[ "$(cut -d. -f1 /etc/debian_version)" = "12" ] || die "è richiesto Debian 12 (Bookworm)."

step "Installazione dei pacchetti"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    xorg xserver-xorg xinit x11-xserver-utils unclutter \
    mpv ffmpeg sqlite3 python3 python3-venv python3-pip \
    udisks2 bluez locales rsync

step "Configurazione del locale it_IT.UTF-8"
if ! locale -a | grep -qiE '^it_IT\.utf-?8$'; then
    sed -i -e 's/^# *it_IT.UTF-8 UTF-8/it_IT.UTF-8 UTF-8/' /etc/locale.gen
    locale-gen
fi
update-locale LANG=it_IT.UTF-8 LC_ALL=it_IT.UTF-8

step "Utente operatore"
if ! id "${OPERATOR}" >/dev/null 2>&1; then
    adduser --gecos "Operatore SVF Kiosk" --disabled-password "${OPERATOR}"
fi
usermod -aG audio,video,input,render "${OPERATOR}"
loginctl enable-linger "${OPERATOR}"

step "Permessi X11 e montaggio USB"
cat > /etc/X11/Xwrapper.config <<'CONF'
allowed_users=anybody
needs_root_rights=no
CONF
cat > /etc/polkit-1/rules.d/50-svf-usb-mount.rules <<'CONF'
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.udisks2.filesystem-mount" ||
         action.id == "org.freedesktop.udisks2.filesystem-unmount") &&
        subject.user == "svf-operatore") {
        return polkit.Result.YES;
    }
});
CONF

step "Directory dati"
mkdir -p "${DATA_DIR}"/{data,media/archive,media/incoming,trash,backups}
chown -R "${OPERATOR}:${OPERATOR}" "${DATA_DIR}"
chmod -R 775 "${DATA_DIR}"
printf '%s\n' "d /run/svf-kiosk 0775 ${OPERATOR} ${OPERATOR} -" > /etc/tmpfiles.d/svf-kiosk.conf
systemd-tmpfiles --create /etc/tmpfiles.d/svf-kiosk.conf

step "Installazione del software in ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'venv' \
    --exclude '__pycache__' --exclude '*.egg-info' --exclude 'build' \
    "${repo_root}/" "${INSTALL_DIR}/"
chown -R "${OPERATOR}:${OPERATOR}" "${INSTALL_DIR}"
sudo -u "${OPERATOR}" python3 -m venv "${INSTALL_DIR}/venv"
sudo -u "${OPERATOR}" "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
sudo -u "${OPERATOR}" "${INSTALL_DIR}/venv/bin/pip" install "${INSTALL_DIR}"
sudo -u "${OPERATOR}" env SVF_ROOT="${DATA_DIR}" \
    "${INSTALL_DIR}/venv/bin/python" -c "from src.db.database import Database; Database()"
for tool in svf-playlist-editor svf-ingest svf-usb-sync svf-presets svf-status svf-restore; do
    ln -sf "${INSTALL_DIR}/venv/bin/${tool}" "/usr/local/bin/${tool}"
done

step "Servizi systemd"
install -m 644 "${INSTALL_DIR}/scripts/systemd/svf-x11.service" /etc/systemd/system/svf-x11.service
user_unit_dir="/home/${OPERATOR}/.config/systemd/user"
sudo -u "${OPERATOR}" mkdir -p "${user_unit_dir}/default.target.wants"
install -o "${OPERATOR}" -g "${OPERATOR}" -m 644 \
    "${INSTALL_DIR}/scripts/systemd/svf-kiosk.service" "${user_unit_dir}/svf-kiosk.service"
ln -sf "${user_unit_dir}/svf-kiosk.service" "${user_unit_dir}/default.target.wants/svf-kiosk.service"
chown -h "${OPERATOR}:${OPERATOR}" "${user_unit_dir}/default.target.wants/svf-kiosk.service"
systemctl daemon-reload
systemctl enable --now bluetooth.service
systemctl enable svf-x11.service
systemctl restart svf-x11.service
sleep 2
operator_uid="$(id -u "${OPERATOR}")"
sudo -u "${OPERATOR}" env XDG_RUNTIME_DIR="/run/user/${operator_uid}" \
    systemctl --user daemon-reload
sudo -u "${OPERATOR}" env XDG_RUNTIME_DIR="/run/user/${operator_uid}" \
    systemctl --user restart svf-kiosk.service || \
    printf '%s\n' "ATTENZIONE: avvio del servizio utente non riuscito; verrà avviato al prossimo riavvio."

step "Installazione completata. Riavviare la macchina per la verifica finale."
