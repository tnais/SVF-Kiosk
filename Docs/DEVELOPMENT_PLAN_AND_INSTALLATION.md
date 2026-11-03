# SVF Kiosk — Development Environment, GitHub Copilot Implementation Plan & Installation Guide

> **Target Platform**: Debian GNU/Linux 12 (Bookworm) minimal  
> **Architecture**: English implementation (code, comments, architecture), Italian operator interface (`it_IT.UTF-8`)  
> **Display Engine**: Minimal X11 (Wayland strictly forbidden)  
> **Encoding**: Pure UTF-8  
> **Specification Reference**: `SpecificationV2` (v2.0)

---

# Table of Contents
1. [Recipe to Create a Development Environment](#1-recipe-to-create-a-development-environment)
   - [1.1 Local Machine Prerequisites](#11-local-machine-prerequisites)
   - [1.2 Debian 12 Development Container / VM Setup](#12-debian-12-development-container--vm-setup)
   - [1.3 System Packages & Dependencies](#13-system-packages--dependencies)
   - [1.4 Python Virtual Environment & Tooling](#14-python-virtual-environment--tooling)
   - [1.5 Directory Structure & Mock Media Environment](#15-directory-structure--mock-media-environment)
   - [1.6 Emulating X11, Audio, and Bluetooth HID for Dev](#16-emulating-x11-audio-and-bluetooth-hid-for-dev)
2. [Step-by-Step Implementation Plan & GitHub Copilot Prompts](#2-step-by-step-implementation-plan--github-copilot-prompts)
   - [Architecture Breakdown](#architecture-breakdown)
   - [Phase 1: SQLite Storage Layer & Backup Engine](#phase-1-sqlite-storage-layer--backup-engine)
   - [Phase 2: USB Media Mounting & Ingestion Wizard (`svf-ingest`)](#phase-2-usb-media-mounting--ingestion-wizard-svf-ingest)
   - [Phase 3: 2-Panel Console Playlist Editor (`svf-playlist-editor`)](#phase-3-2-panel-console-playlist-editor-svf-playlist-editor)
   - [Phase 4: Player Engine & Bluetooth Remote Controller Daemon (`svf-kiosk-daemon`)](#phase-4-player-engine--bluetooth-remote-controller-daemon-svf-kiosk-daemon)
   - [Phase 5: Diagnostics, Backup Rollback & Maintenance CLI Tools](#phase-5-diagnostics-backup-rollback--maintenance-cli-tools)
3. [Production Installation Instructions](#3-production-installation-instructions)
   - [3.1 Target Debian OS Preparation](#31-target-debian-os-preparation)
   - [3.2 User & Permissions Setup (`svf-operatore`)](#32-user--permissions-setup-svf-operatore)
   - [3.3 Package Installation & X11 Configuration](#33-package-installation--x11-configuration)
   - [3.4 Deploying SVF Kiosk Software & Database](#34-deploying-svf-kiosk-software--database)
   - [3.5 Bluetooth Remote Pairing & Persistence](#35-bluetooth-remote-pairing--persistence)
   - [3.6 Systemd Service Setup & Auto-Start](#36-systemd-service-setup--auto-start)
   - [3.7 Acceptance Testing & Commissioning Checklist](#37-acceptance-testing--commissioning-checklist)

---

# 1. Recipe to Create a Development Environment

Developers can build and test the entire kiosk application on a standard Debian 12 workstation, inside a Docker container, or in a lightweight VirtualBox/QEMU virtual machine.

### 1.1 Local Machine Prerequisites
- Linux Workstation (Debian, Ubuntu, Fedora) or macOS/Windows with Docker / Lima / WSL2.
- Git, Python 3.11+, and an X11 server (or `Xvfb` for headless continuous integration).

### 1.2 Debian 12 Development Container / VM Setup
If developing via Docker, use this `Dockerfile.dev` to mirror the target production Debian environment:

```dockerfile
# Dockerfile.dev
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=it_IT.UTF-8
ENV LANGUAGE=it_IT:it
ENV LC_ALL=it_IT.UTF-8

# Install base tools, locales, X11 virtual frame buffer, and media libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    git \
    curl \
    sudo \
    python3 \
    python3-pip \
    python3-venv \
    sqlite3 \
    libsqlite3-dev \
    mpv \
    ffmpeg \
    x11-utils \
    xauth \
    xvfb \
    unclutter \
    udisks2 \
    bluez \
    build-essential \
 && sed -i -e 's/# it_IT.UTF-8 UTF-8/it_IT.UTF-8 UTF-8/' /etc/locale.gen \
 && sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
 && locale-gen \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create unprivileged dev operator
RUN useradd -m -s /bin/bash -u 1000 svf-operatore \
 && echo "svf-operatore ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER svf-operatore
WORKDIR /home/svf-operatore/svf-kiosk
```

Build and run the container mounting your local workspace:
```bash
docker build -t svf-kiosk-dev -f Dockerfile.dev .
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd):/home/svf-operatore/svf-kiosk \
  svf-kiosk-dev bash
```

### 1.3 System Packages & Dependencies
On native Debian 12, install all required packages:
```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip sqlite3 \
    mpv ffmpeg xinit x11-xserver-utils unclutter \
    udisks2 bluez evtest
```

### 1.4 Python Virtual Environment & Tooling
The application uses Python 3.11+ with lightweight libraries. From the repository root, create `.venv` and install the project and its dependencies with:
```bash
./scripts/setup-venv.sh
source .venv/bin/activate
```
The setup script can also be run from outside the repository directory. It creates `.venv` if needed and installs dependencies from `pyproject.toml`.
- `textual`: Modern, ultra-responsive Terminal User Interface (TUI) with full 80x24 VT100/SSH compatibility.
- `python-mpv-jsonipc`: Lightweight, asynchronous UNIX IPC socket client to manage `mpv`.
- `pydantic`: Schema validation and clean data modeling.
- `pytest`: Unit and integration testing.

### 1.5 Directory Structure & Mock Media Environment
Initialize the local mock directory tree mirroring production `/var/lib/svf-kiosk/`:
```bash
mkdir -p dev_root/data dev_root/media/archive dev_root/media/incoming dev_root/trash dev_root/backups run_socket
export SVF_ROOT="$(pwd)/dev_root"
export SVF_IPC_SOCK="$(pwd)/run_socket/mpv.sock"

# Generate 3 lightweight synthetic video test files using ffmpeg
ffmpeg -f lavfi -i testsrc=duration=10:size=1280x720:rate=30 -f lavfi -i sine=frequency=440:duration=10 -pix_fmt yuv420p dev_root/media/archive/video1.mp4 -y
ffmpeg -f lavfi -i testsrc=duration=15:size=1280x720:rate=30 -f lavfi -i sine=frequency=554:duration=15 -pix_fmt yuv420p dev_root/media/archive/video2.mp4 -y
ffmpeg -f lavfi -i testsrc=duration=8:size=1280x720:rate=30 -f lavfi -i sine=frequency=659:duration=8 -pix_fmt yuv420p dev_root/media/incoming/new_sample.mp4 -y
```

### 1.6 Emulating X11, Audio, and Bluetooth HID for Dev
- **Headless X11 testing**:
  ```bash
  Xvfb :99 -screen 0 1920x1080x24 &
  export DISPLAY=:99
  ```
- **Bluetooth Remote Keyboard Simulation**:
  Because standard Bluetooth remotes identify as standard keyboard HID devices, you can test triggers directly using keys `1` through `9`, `Enter`, and `Escape` in a local terminal window.

---

# 2. Step-by-Step Implementation Plan & GitHub Copilot Prompts

### Architecture Breakdown
```
svf-kiosk/
├── config/
│   ├── mpv.conf
│   └── settings.default.json
├── src/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql
│   │   └── database.py        # SQLite connection, WAL mode, foreign keys, backups
│   ├── models/
│   │   ├── __init__.py
│   │   └── video.py           # Pydantic schemas (title <= 38 chars, desc <= 150)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── strings.py         # it_IT.UTF-8 localization catalog
│   │   └── mpv_client.py      # UNIX socket IPC client for mpv
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── ingest.py          # svf-ingest CLI tool
│   │   ├── usb_sync.py        # svf-usb-sync helper
│   │   └── status.py          # svf-status diagnostic
│   ├── tui/
│   │   ├── __init__.py
│   │   └── playlist_editor.py # 2-panel console UI (Textual/curses)
│   └── daemon/
│       ├── __init__.py
│       └── kiosk_player.py    # Main background ambient loop & remote listener
├── tests/
│   ├── test_db.py
│   ├── test_playlist.py
│   └── test_ingest.py
└── setup.py
```

---

## Phase 1: SQLite Storage Layer & Backup Engine

### Goal
Implement database initialization, WAL journal mode, pre/post backup snapshot routines, rolling 20-backup retention, JSON mirror export, and CRUD operations.

#### GitHub Copilot Prompt:
```markdown
You are writing production Python 3 code for a Debian-based museum kiosk called "SVF Kiosk" following SpecificationV2.
Target file: `src/db/database.py`

Requirements:
1. Pure UTF-8 encoding. All system and user logs must support Italian characters.
2. The SQLite database is located at `{SVF_ROOT}/data/svf_kiosk.db`.
3. SQLite Pragmas:
   - PRAGMA journal_mode = WAL;
   - PRAGMA foreign_keys = ON;
   - PRAGMA synchronous = NORMAL;
4. Schema definition:
   - `videos` table:
     - `id INTEGER PRIMARY KEY AUTOINCREMENT`
     - `file_path TEXT NOT NULL UNIQUE` (relative path)
     - `display_title TEXT NOT NULL` (enforce max 38 chars)
     - `description TEXT` (enforce max 150 chars)
     - `duration_seconds INTEGER DEFAULT 0`
     - `resolution TEXT DEFAULT ''`
     - `date_added DATETIME DEFAULT CURRENT_TIMESTAMP`
     - `is_deleted INTEGER DEFAULT 0`
     - `deleted_at DATETIME NULL`
   - `playlist` table:
     - `position INTEGER PRIMARY KEY` (1, 2, 3...)
     - `video_id INTEGER NOT NULL`, FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE RESTRICT
   - `remote_presets` table:
     - `preset_key INTEGER PRIMARY KEY CHECK(preset_key BETWEEN 1 AND 9)`
     - `video_id INTEGER NOT NULL`, FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
   - `settings` table:
     - `key TEXT PRIMARY KEY`, `value TEXT NOT NULL`
5. Backup Engine:
   - Method `create_backup(prefix: str) -> str`: copies `svf_kiosk.db` to `{SVF_ROOT}/backups/svf_kiosk_{prefix}_{timestamp}.db` safely using sqlite3 `iterdump()` or `backup()`.
   - Method `rotate_backups(keep_count: int = 20)`: retains only the 20 most recent backups and removes older ones.
   - Method `export_json_mirror()`: writes a clean JSON mirror of active playlist items to `{SVF_ROOT}/data/playlist_export.json` atomically via temporary file replacement.
6. Provide full typed Python methods for:
   - `get_available_videos()` (excluding deleted, ordered by display_title)
   - `get_playlist()` (ordered by position)
   - `add_to_playlist(video_id: int)`
   - `remove_from_playlist(position: int)`
   - `reorder_playlist(source_pos: int, target_pos: int)`
   - `soft_delete_video(video_id: int, trash_dir: str)`: checks if in playlist (raise exception if present), moves file to trash, sets `is_deleted = 1`.

Include comprehensive unit tests in `tests/test_db.py` using pytest.
```

---

## Phase 2: USB Media Mounting & Ingestion Wizard (`svf-ingest`)

### Goal
Build `svf-usb-sync` and `svf-ingest`. Must strictly enforce the operational rule:
*"This operation will not happen during visits (too much confusion and too little space)"*.
Validates titles up to 38 characters and descriptions up to 150 characters. Communicates in Italian (`it_IT.UTF-8`).

#### GitHub Copilot Prompt:
```markdown
You are building the CLI tools for SVF Kiosk (`src/cli/ingest.py` and `src/cli/usb_sync.py`) according to SpecificationV2.

Context & Rules:
- Language of code: English.
- All user-facing strings MUST be in Italian (`it_IT.UTF-8`).
- Operational constraint: Ingestion will NOT happen during visitor hours. If kiosk player is active, warn operator or offer IPC preview arbitration.

Requirements for `usb_sync.py`:
1. Use `udisksctl` via Python `subprocess` (no root privileges required).
2. Scan for unmounted block devices in `/dev/sd*`.
3. Mount the device safely with `udisksctl mount -b <device>`.
4. Scan mounted filesystem for video files (`.mp4`, `.mkv`, `.mov`, `.avi`).
5. Print Italian progress:
   - `MSG_USB_DETECTED = "Supporto USB rilevato: {device}. Avvio scansione filmati..."`
6. Copy detected media to `{SVF_ROOT}/media/incoming/` with progress bar.
7. Safely unmount with `udisksctl unmount -b <device>`.
8. Print: `MSG_USB_COPY_SUCCESS = "Copia completata: {count} nuovi video trasferiti nell'archivio."`

Requirements for `ingest.py`:
1. Check `{SVF_ROOT}/media/incoming/` for unindexed video files.
2. Automatic pre-backup of SQLite DB via `db.create_backup("pre_ingest")`.
3. For each file:
   - Probe duration, resolution, and audio codec using `ffprobe -v quiet -print_format json -show_format -show_streams`.
   - IPC Preview: prompt operator:
     `MSG_PREVIEW_PROMPT = "Vuoi visualizzare l'anteprima sul monitor principale della sala? [s/N]: "`
     If 's' or 'S', connect to `/run/svf-kiosk/mpv.sock`, pause kiosk player, play 15s preview with OSD banner `"ANTEPRIMA OPERATORE: Verifica filmato in corso..."`, then resume.
   - Prompt for display title:
     Validate non-empty and max 38 characters. Loop if invalid with Italian error.
   - Prompt for brief description:
     Validate max 150 characters.
   - Move file from `incoming/` to `{SVF_ROOT}/media/archive/<filename>`.
   - Insert video record into SQLite database.
4. Run `db.create_backup("post_ingest")` and `db.rotate_backups()`.
5. Exit cleanly with summary report in Italian.
```

---

## Phase 3: 2-Panel Console Playlist Editor (`svf-playlist-editor`)

### Goal
Console application for 80x24 terminals over SSH.
- Left panel: Available videos (Archivio), sorted by display title.
- Right panel: Active playlist (Scaletta Attiva), sorted by position.
- Color rules: Black background `#000000`, white foreground `#FFFFFF`, reverse highlight for cursor.
- Blue highlight/prefix for videos in the playlist (cannot be deleted; beep + error).
- Green highlight for active reordering row in playlist.
- Bottom details inspector showing title (up to 38 chars) and multi-line description (up to 150 chars).
- Double confirmation in Italian for deletion (`[s/N]`).

#### GitHub Copilot Prompt:
```markdown
Create the two-panel TUI playlist editor in Python using Textual or curses for SVF Kiosk (`src/tui/playlist_editor.py`).

Visual Specification (80x24 terminal compatible, black background, white foreground):
========================= GESTORE SCALETTA SVF-KIOSK =========================
 [PANNELLO SINISTRO: Archivio Video]       [PANNELLO DESTRO: Scaletta Attiva]
 +-------------------------------------+   +---------------------------------+
 | [01] Arrivo treno storico 1928      |   | 1. *Restauro Gr. 625 (04:12)    |
 | [02] Centenario Stazione            |   | 2.   Centenario Stazione (02:45)|
 |>[03] Manutenzione Caldaia          <|   | 3.   Locomotiva a Vapore (08:20)|
 +-------------------------------------+   +---------------------------------+
 SCHEDA DETTAGLI:
 Titolo: Manutenzione Caldaia | ID: 3 | Durata: 06:15 | File: archive/caldaia.mp4
 Descrizione: Riprese delle operazioni di smontaggio tubi fumo e prova idraulica
 effettuata dai soci volontari nell'officina museale.
------------------------------------------------------------------------------
 COMANDI: [TAB] Cambia Pannello | [↑ / ↓] Scorri | [INVIO] Azione | [C] Elimina
          [D] Rimuovi da Scaletta | [S] Salva modifiche | [Q] Esci
==============================================================================

Behavior & Key Bindings:
1. `TAB`: Toggle focus between Left and Right panels. Ignored if a video is in active reorder mode (Green).
2. `↑ / ↓`: Move selection up/down. Clamped within list bounds (never out of index).
3. Left Panel (Archivio):
   - Videos already present in the active playlist turn BLUE (or cyan) and are locked against deletion.
   - `INVIO`: Appends highlighted video to the end of the active playlist.
   - `C`: Attempt delete. If video is in playlist, trigger terminal beep (`\a`) and display Italian error:
     `"ERRORE: Impossibile eliminare! Il video è utilizzato nella scaletta."`
     If video is not in playlist, ask for DOUBLE confirmation in Italian:
     1st prompt: `"Sei sicuro di voler eliminare '{display_title}'? [s/N]: "`
     2nd prompt: `"ATTENZIONE: Il file verrà spostato nel cestino di sicurezza. Confermi l'operazione? [s/N]: "`
     If both confirmed, move file to `{SVF_ROOT}/trash/` and flag as deleted in SQLite.
4. Right Panel (Scaletta Attiva):
   - `INVIO`: Toggle active reordering mode. Turns row GREEN.
   - When active (Green): `↑ / ↓` moves video position up or down, swapping positions in the playlist. Pressing `INVIO` again deactivates it.
   - `D`: Removes highlighted video from playlist. It reverts to white in the left panel.
5. Bottom Details Panel:
   - Continuously displays the full display_title (38 chars), ID, duration, file path, and 150-char description of the highlighted item in either panel.
6. Persistence:
   - `S`: Commits changes to SQLite, writes backup snapshot, exports JSON cache, and displays:
     `"Scaletta salvata con successo nel database."`
   - `Q`: Quit. If unsaved changes exist, ask:
     `"Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]: "`
```

---

## Phase 4: Player Engine & Bluetooth Remote Controller Daemon (`svf-kiosk-daemon`)

### Goal
Implement unattended background media loop using `mpv` with hardware acceleration over X11 (`vaapi` / `vdpau`), IPC socket `/run/svf-kiosk/mpv.sock`, and Bluetooth remote controller listener.

#### Key Resumption Logic:
When the volunteer guide triggers a video via remote preset (`1 .. 9`) or on-screen menu (`OK / Menu`):
1. Ambient video is paused/interrupted.
2. Selected video plays with high priority.
3. Upon conclusion or when guide presses `ANNULLA` / `ESC`:
   **The system automatically resumes ambient playback with the next scheduled video.**

#### GitHub Copilot Prompt:
```markdown
Create the main player and remote controller daemon (`src/daemon/kiosk_player.py`) for SVF Kiosk.

Requirements:
1. Environment:
   - Must run on minimal X11 (`DISPLAY=:0`).
   - Pure X11 only; Wayland is strictly forbidden.
   - IPC socket: `/run/svf-kiosk/mpv.sock`.
2. mpv Initialization:
   - Launch `mpv` with arguments:
     `--vo=gpu --hwdec=auto-safe --fullscreen --no-terminal --cursor-autohide=always`
     `--cursor-autohide-fs-only --input-ipc-server=/run/svf-kiosk/mpv.sock`
     `--loop-playlist=inf --osd-font="DejaVu Sans" --osd-font-size=32`
3. Ambient Loop:
   - Read active playlist from SQLite `playlist` table.
   - If playlist is empty, render full-screen fallback standby frame in Italian:
     `"Nessun video presente nella scaletta. Rivolgersi all'operatore."` and sleep 10s.
   - Otherwise, load files into mpv playlist and start continuous rotation.
4. Bluetooth Remote Listener:
   - Remote presents as standard keyboard HID device via Linux evdev (`/dev/input/event*`) or X11 key events.
   - Keys `1` through `9`: Lookup preset in `remote_presets` table in SQLite.
     - If matched:
       - Interrupt current video.
       - Flash OSD banner: `"▶ Riproduzione richiesta: {title}"` (3-second duration).
       - Play requested video immediately.
   - Key `OK` / `Menu`: Toggle discreet lower-third OSD carousel displaying available titles. Up/Down to navigate, OK to select.
   - Key `ESC` / `Back`: Abort current video early.
5. Resumption Policy (SpecificationV2 Coherence):
   - When interrupted video finishes or is aborted with ESC:
     - Execute the policy: **Resume the regular ambient rotation with the next scheduled video.**
     - Advance mpv playlist index to `(interrupted_index + 1) % total_items`.
     - Flash brief OSD: `"Ripresa scaletta normale: riproduzione del prossimo filmato..."`.
6. Watchdog & Resilience:
   - Handle mpv process crashes: automatically restart player within 3 seconds without dropping state.
   - Catch Bluetooth disconnection/reconnection gracefully.
```

---

## Phase 5: Diagnostics, Backup Rollback & Maintenance CLI Tools

### Goal
Provide operators with quick CLI utilities: `svf-status`, `svf-restart`, and `svf-backup-restore`.

#### GitHub Copilot Prompt:
```markdown
Create the diagnostic and rollback CLI tools in `src/cli/`:
1. `svf-status`:
   - Queries `/run/svf-kiosk/mpv.sock` to retrieve current playing file, elapsed time, and total duration.
   - Reads system metrics: CPU temperature (`/sys/class/thermal/thermal_zone0/temp`), RAM usage, and disk space in `/var/lib/svf-kiosk`.
   - Checks Bluetooth remote connection state via `bluetoothctl info`.
   - Prints a formatted report in Italian.
2. `svf-restart`:
   - Sends SIGHUP or restarts systemd unit `systemctl --user restart svf-kiosk.service`.
3. `svf-backup-restore`:
   - Lists the 20 available snapshots in `{SVF_ROOT}/backups/`.
   - Prompts operator to pick a snapshot.
   - Takes a safety backup of the current database before restoring.
   - Restores chosen backup and triggers `svf-restart`.
```

---

# 3. Production Installation Instructions

### 3.1 Target Debian OS Preparation
Install a minimal Debian 12 (Bookworm) standard system (deselect Desktop Environment during installation; install only standard system utilities and SSH server).

### 3.2 User & Permissions Setup (`svf-operatore`)
Create the unprivileged operator user:
```bash
sudo adduser --gecos "Operatore SVF Kiosk" --disabled-password svf-operatore
sudo passwd svf-operatore

# Add to audio, video, and input groups
sudo usermod -aG audio,video,input,render svf-operatore

# Configure polkit for non-root USB storage mounting via udisks2
sudo tee /etc/polkit-1/rules.d/50-svf-usb-mount.rules > /dev/null << 'EOF'
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.udisks2.filesystem-mount" ||
         action.id == "org.freedesktop.udisks2.filesystem-unmount") &&
        subject.isInGroup("svf-operatore")) {
        return polkit.Result.YES;
    }
});
EOF
```

### 3.3 Package Installation & X11 Configuration
```bash
# Install required packages (strictly X11, no Wayland)
sudo apt update
sudo apt install -y --no-install-recommends \
    xorg xserver-xorg xinit x11-xserver-utils \
    unclutter mpv ffmpeg sqlite3 python3 python3-pip python3-venv \
    udisks2 bluez locales

# Ensure Italian UTF-8 locale is compiled
sudo sed -i -e 's/# it_IT.UTF-8 UTF-8/it_IT.UTF-8 UTF-8/' /etc/locale.gen
sudo locale-gen
sudo update-locale LANG=it_IT.UTF-8 LC_ALL=it_IT.UTF-8

# Configure X11 permissions for unprivileged user
sudo tee /etc/X11/Xwrapper.config > /dev/null << 'EOF'
allowed_users=anybody
needs_root_rights=no
EOF
```

The X11 session script is `scripts/x11-session.sh` (screen blanking and DPMS off, `unclutter -idle 0.5 -root`). It is started by `svf-x11.service`; the player runs separately as the user service `svf-kiosk.service`.

### 3.4 Deploying SVF Kiosk Software & Database
```bash
# Create application and storage directories
sudo mkdir -p /opt/svf-kiosk
sudo mkdir -p /var/lib/svf-kiosk/{data,media/archive,media/incoming,trash,backups}
sudo mkdir -p /run/svf-kiosk
sudo chown -R svf-operatore:svf-operatore /opt/svf-kiosk /var/lib/svf-kiosk /run/svf-kiosk

# Switch to operator user and deploy
sudo -u svf-operatore -i
cd /opt/svf-kiosk
git clone <repository_url> .
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# Initialize database schema
sqlite3 /var/lib/svf-kiosk/data/svf_kiosk.db < src/db/schema.sql

# Install CLI wrapper symlinks
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-playlist-editor /usr/local/bin/svf-playlist-editor
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-ingest /usr/local/bin/svf-ingest
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-usb-sync /usr/local/bin/svf-usb-sync
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-presets /usr/local/bin/svf-presets
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-status /usr/local/bin/svf-status
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-restore /usr/local/bin/svf-restore
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-restart /usr/local/bin/svf-restart
sudo ln -sf /opt/svf-kiosk/venv/bin/svf-backup-restore /usr/local/bin/svf-backup-restore
```

### 3.5 Bluetooth Remote Pairing & Persistence
Pair and trust the Bluetooth remote control:
```bash
sudo systemctl enable --now bluetooth

# Run bluetoothctl to pair controller
bluetoothctl
# Inside bluetoothctl prompt:
# power on
# agent on
# default-agent
# scan on
# (press pairing button on remote)
# pair <MAC_ADDRESS>
# trust <MAC_ADDRESS>
# connect <MAC_ADDRESS>
# exit
```
To guarantee automatic reconnection after battery changes or sleep, add to `/etc/bluetooth/main.conf`:
```ini
[Policy]
AutoEnable=true
ReconnectAttempts=0
ReconnectIntervals=1, 2, 4, 8
```

### 3.6 Systemd Service Setup & Auto-Start
Configure `systemd` to run X11 and the kiosk daemon automatically at boot:

Two units are used (both in `scripts/systemd/`):
- `svf-x11.service` (system unit): runs `xinit /opt/svf-kiosk/scripts/x11-session.sh -- /usr/bin/X :0 vt1` as `svf-operatore`.
- `svf-kiosk.service` (**user** unit of `svf-operatore`, installed in `~/.config/systemd/user/`): waits for `/tmp/.X11-unix/X0`, then runs `svf-kiosk-daemon` with `Restart=always`, `RestartSec=3`. It is a user unit so that `svf-restore` can run `systemctl --user restart svf-kiosk.service`; lingering (`loginctl enable-linger svf-operatore`) starts it at boot.

`/run/svf-kiosk` (mpv socket) is created at boot by `/etc/tmpfiles.d/svf-kiosk.conf`.

### 3.6a Automated Provisioning

On a fresh Debian 12 minimal system, from a checkout of the repository:
```bash
sudo ./scripts/setup-kiosk.sh
```
The script (`set -euo pipefail`, refuses non-root and non-Debian-12) installs the packages, the `it_IT.UTF-8` locale, the operator user, the polkit rule, `/var/lib/svf-kiosk/...` (775), the software and venv in `/opt/svf-kiosk`, the `/usr/local/bin` symlinks, and enables both services. It is safe to re-run. Sections 3.2-3.6 describe the same steps manually.

**Automated static checks** (`tests/test_provisioning.py`, no root needed, run by `pytest tests/`): the scripts and unit files are read as text and cross-checked against the Python code. They verify, among other things:
- shell syntax, shebangs, executable bits, LF line endings, no mojibake;
- strict mode, root and Debian 12 checks placed before any system change, and the step order (packages, locale, user, X11/polkit, data directories, software, symlinks, services);
- idempotence markers (`mkdir -p`, `ln -sf`, `rsync`, `id` and `locale -a` checks) and no dangerous patterns (downloads, `| sh`, `rm -rf /`, unquoted variables in `chown`/`chmod`/`rsync`);
- that every `/usr/local/bin` symlink is a real entry point in `pyproject.toml` (and every operator tool is linked), that every referenced file exists, and that the data root, mpv socket directory and operator user match the application defaults;
- the unit constraints (user unit vs system unit, ordering after X, bounded wait for the X socket, `:0` on `vt1`, `Restart=always`/`RestartSec=3`, no Wayland tooling) and `systemd-analyze verify`.

They do not prove that provisioning works on a real machine: that is covered by manual group G.

Useful commands afterwards: `systemctl status svf-x11`, `sudo -u svf-operatore XDG_RUNTIME_DIR=/run/user/$(id -u svf-operatore) systemctl --user status svf-kiosk`, `journalctl _UID=$(id -u svf-operatore) -u svf-kiosk`.

### 3.6b SSH Terminal Smoke Test (Playlist Editor)

Unit tests cannot prove the TUI works over a real SSH pseudo-terminal. On a machine where passwordless SSH to the target host is configured (for example `localhost`), run:

```bash
.venv/bin/python scripts/ssh-smoke-editor.py [host] [TERM]   # defaults: localhost, xterm-256color
```

The script seeds a throw-away `SVF_ROOT` (the real database is never touched), opens `svf-playlist-editor` through `ssh -tt` at 80x24, and verifies panel rendering, add-to-playlist, save, clean quit and persistence. It has been verified with `TERM` set to `xterm-256color`, `xterm`, `vt100` and `linux`. It does not replace a visual check of colours (blue/green) on the operator's actual terminal.

### 3.6c Required Manual Tests (not coverable by `pytest`)

These checks need real hardware, a real terminal or a real `mpv`. Run them once on the target machine before commissioning and after any change to the touched component. Record date, tester and result next to each item.

**A. Playlist editor on the operator terminal** (SSH from the operator PC, `TERM` as the terminal sets it)

| # | Procedure | Expected result |
|---|---|---|
| A1 | Open `svf-playlist-editor`. Look at colours. | Black background, white text, reverse-video cursor. Videos in the playlist are **blue** in the left panel. |
| A2 | Right panel: `INVIO` on a row. | Row turns **green** (readable on the terminal's palette). `↑ / ↓` moves it; `TAB` is ignored; `INVIO` locks it. |
| A3 | Left panel, blue video: press `C`. | Audible beep (or visual bell, depending on terminal settings) and the Italian "in playlist" error. |
| A4 | Same on a 16-colour terminal (`COLORTERM` unset, e.g. `TERM=linux` on the machine console). | Blue/green markers still distinguishable; no garbled escape sequences. |
| A5 | Resize the terminal below 80x24, then back. | No crash; layout recovers at 80x24. Below 80x24 behaviour is only informational. |
| A6 | Accented characters (è à é ì ò ù, —, ↑ ↓, ▶) in titles and messages. | Rendered correctly, no mojibake. |
| A7 | Delete flow: `C` on an unlinked video, answer `s` twice. | Two Italian prompts; file is moved to `trash/`; entry disappears. Any other answer cancels. |
| A8 | Press `S`, then `Q`; reopen the editor. | "Scaletta salvata" shown; order persisted; a snapshot appears in `backups/` and `playlist.json` is updated. |
| A9 | Edit without saving, press `Q`. | Italian unsaved-changes prompt; `n` stays in the editor. |
| A10 | Disconnect the SSH session (close the terminal) while editing. | No corrupted database; the next launch opens normally. |
| A12 | Left or right panel: `P`, then `3`. Press `S`, reopen the editor. | Italian confirmation; a `[3]` badge appears next to the title in both panels and persists after saving. `P` then `0` clears all keys of the video; `ESC` cancels. |
| A13 | `svf-presets set 3 "<part of title>"`, then `svf-presets list`. | Key 3 is listed with the video; an ambiguous title lists candidates and changes nothing (use `--id`). `svf-presets clear 3` frees it. |
| A14 | With the daemon running, press `3` on the remote after A12/A13. | The assigned video plays immediately (presets are read at each keypress). |
| A11 | Keep the editor open, run `svf-ingest --force` in a second session, then press `TAB` / navigate. | Known limitation: the new video appears only after restarting the editor. |

Automated partial coverage: `scripts/ssh-smoke-editor.py` (section 3.6b).

**B. `mpv` integration (requires `mpv` installed and an X11 session)**

| # | Procedure | Expected result |
|---|---|---|
| B1 | Run `pytest tests/test_mpv_client.py` on the target. | The real-mpv test is no longer skipped and passes. |
| B2 | Start `mpv` with `config/mpv.conf` and the IPC socket; send `loadfile`, `pause`, `get_property` through `MpvClient`. | Commands accepted; errors raise `MpvIpcError`. |
| B3 | `play_preview` during ambient playback. | Ambient pauses, preview plays for 15 s with the OSD banner, ambient resumes at the **same position**. The five-argument `loadfile` used to restore the position is unverified against real `mpv`; confirm it. |
| B4 | Kill `mpv` while an `MpvClient` call is in flight. | Italian "mpv unavailable" message; no hang. |
| B5 | Hardware decoding (`vaapi`/`vdpau`) with a real museum video. | `mpv` log shows hardware decoding active; no dropped frames on the TV. |

**C. USB sync and ingest (real devices)**

| # | Procedure | Expected result |
|---|---|---|
| C1 | Plug a USB stick with `.mp4/.mkv/.mov` files; run `svf-usb-sync` as `svf-operatore` outside visit hours (or with `--force`). | Mounted via `udisksctl` without a root password; only new files copied to `media/incoming/`; stick unmounted cleanly. |
| C2 | Unplug the stick (or pull it) during the copy. | Italian error; no crash. A leftover `*.part` file in `incoming/` is a known issue and must be removed by hand. |
| C3 | Stick with FAT32/exFAT/NTFS and with file names containing accents and spaces. | Files copied with correct names. |
| C4 | `svf-ingest` on a real file with accented title; accept the preview. | `ffprobe` metadata correct; preview shown on the TV; file moved to `media/archive/`; row inserted. |
| C5 | Title of 39 characters, description of 151 characters. | Rejected with an Italian message; no silent truncation. |
| C6 | Run `svf-ingest` / `svf-usb-sync` during visit hours and while ambient video plays, without `--force`. | Refused with the Italian visit-hour warning. With `--force` it proceeds. Note: the ambient kiosk plays whenever idle, so operators normally need `--force`. |

**D. System-level**

| # | Procedure | Expected result |
|---|---|---|
| D1 | Pull the AC plug during an editor save or an ingest, then reboot. | SQLite WAL recovers; the database passes `PRAGMA integrity_check`; latest snapshot in `backups/` is usable. |
| D2 | Run `scripts/setup-venv.sh` on a fresh clone. | `.venv` created and `pytest tests/` passes. |
| D3 | `scripts/ssh-smoke-editor.py` against the real host (not only `localhost`). | All checks `OK`. |

**E. Kiosk daemon and Bluetooth remote (`svf-kiosk-daemon`, requires X11, `mpv`, a paired remote; the service user must be in the `input` group to read `/dev/input/event*`)**

| # | Procedure | Expected result |
|---|---|---|
| E1 | Start the daemon under `xinit` with a non-empty playlist. | Fullscreen playback on the TV, cursor hidden, ambient rotation advances at the end of each video (verifies the `idle-active` end-of-file detection and the 1.5 s start grace). |
| E2 | Empty playlist, then add a video with the editor and save. | Italian standby message on a black screen; within ~5 s of the save, playback starts by itself. |
| E3 | Press `1`-`9` (also the keypad) on a mapped key. | Ambient stops, OSD `▶ Riproduzione richiesta: …` for 3 s, requested video plays. Unmapped key: Italian "nessun filmato associato" message. |
| E4 | Let the on-demand video finish, then repeat pressing `ESC`/`Annulla`. | Ambient resumes with the **next** video (not the interrupted one, not from 0:00) and the OSD `Ripresa scaletta normale…`. |
| E5 | `OK`/`Menu`: lower-third carousel, `↑ / ↓`, `OK`. | Carousel readable at the bottom of the screen (verify the ASS `\an2` / `${osd-ass-cc}` markup on the real mpv), wraps around, selection plays on demand; `ESC` or 10 s of inactivity closes it. |
| E6 | `kill -9` the `mpv` process during ambient and during on-demand playback. | mpv is back within 3 s; the same video is replayed; after an on-demand video, `ESC` still resumes with the correct next video. |
| E7 | `systemctl stop` / `kill -TERM` the daemon. | mpv terminated, `/run/svf-kiosk/mpv.sock` removed. |
| E8 | Disconnect/reconnect the Bluetooth remote while running. | Known limitation: devices are opened at start; restart the daemon after re-pairing. |
| E9 | Rename a playlist file on disk while running. | The file is skipped, the next one plays; no infinite loop. |
| E10 | Boot auto-start, screen blanking/DPMS off, cursor hiding (`unclutter`). | After `setup-kiosk.sh` and a reboot, the kiosk starts by itself without login; the screen never blanks; the cursor disappears after 0.5 s. |

**Group G — Provisioning (`scripts/setup-kiosk.sh`, on a clean Debian 12 VM or the target)**

| # | Action | Expected result |
|---|--------|-----------------|
| G1 | Run `sudo ./scripts/setup-kiosk.sh` on a clean minimal Debian 12; then re-run it. | Completes without errors both times (idempotent); on non-Debian-12 or non-root it refuses with an Italian error. |
| G2 | Reboot. | `svf-x11.service` active, `svf-kiosk.service` active for `svf-operatore`, `/run/svf-kiosk/mpv.sock` exists, TV shows the Italian standby or the playlist. |
| G3 | `kill -9` the Python daemon, then `systemctl stop svf-x11` / start. | Daemon back in ~3 s; after an X restart the daemon recovers or is restarted by systemd (verify that mpv re-attaches to the new display). |
| G4 | As `svf-operatore`: `udisksctl mount -b /dev/sdX1` without password. | Mounts without a polkit prompt. |
| G5 | Reboot with no HDMI TV attached, then attach it. | Known risk: X may start without a screen; reboot with the TV on if the picture does not appear. |

Assign keys `1`-`9` with the editor (`P` then a digit, saved with `S`) or with `svf-presets` (see tests A12-A14).

**Group F — `svf-status` and `svf-restore` (real hardware)**

| # | Action | Expected result |
|---|--------|-----------------|
| F1 | `svf-status` while a video plays, then paused, then with the daemon stopped. | File, elapsed/total time and "in riproduzione"/"in pausa"; with the daemon stopped "Lettore video: non raggiungibile." |
| F2 | `svf-status` on the real Pi/PC. | CPU temperature, RAM, free disk in the SVF root, and the HDMI output with its resolution are plausible (`xrandr` needs `DISPLAY=:0`; over SSH it is set automatically). |
| F3 | `svf-status` with the Bluetooth remote on, off, and with low battery. | Address shown when connected; battery shown only if the remote reports it (many HID remotes do not); "non connesso" when off. |
| F4 | `svf-restore`, choose an older snapshot, answer `s`. | Safety `pre_restore` snapshot created, playlist reverted in the editor, `playlist.json` regenerated, daemon restarted (`systemctl --user` needs a user session / lingering) and the kiosk plays the restored playlist. |
| F5 | `svf-restore` when `systemctl --user` fails (e.g. over a plain `su`). | Italian warning that the database was restored but the service must be restarted by hand. |

### 3.7 Acceptance Testing & Commissioning Checklist

| Test Item | Verification Procedure | Expected Result |
|---|---|---|
| **Boot Auto-Start** | Power on the computer from wall circuit breaker. | Debian boots directly into fullscreen TV playback; no mouse cursor or desktop icons visible. |
| **Empty Playlist Fallback** | Start with empty `playlist` table. | Italian message: `"Nessun video presente nella scaletta. Rivolgersi all'operatore."` appears cleanly. |
| **Guide Interruption** | Press key `1` on Bluetooth remote while ambient video loops. | Ambient video pauses; requested video starts immediately with OSD banner. |
| **Next-Video Resume** | Allow interrupted video to finish (or press `ESC`). | Ambient playback automatically resumes with the **next scheduled video**. |
| **USB Media Ingestion** | Connect USB drive and run `svf-usb-sync` over SSH outside visitor hours. | Media detected and safely copied without requiring root password. |
| **38-Char Title Validation** | Ingest video with title > 38 characters in `svf-ingest`. | System blocks input and requests title <= 38 characters in Italian. |
| **Double Delete Confirmation** | Select unlinked video in `svf-playlist-editor` and press `C`. | Asks two confirmations in Italian (`[s/N]`), then moves file to safety trash. |
| **Protected Video Lock** | Select a video currently active in playlist on the left panel and press `C`. | Video turns Blue, system beeps, and displays deletion blocked error. |
| **Reorder in Scaletta** | Press `INVIO` on right panel item, press `↑ / ↓`, then `INVIO`. | Video turns Green while moving; locks into new sequence position upon Enter. |
| **Power-Cut Resilience** | Pull AC power plug during video playback, then reconnect. | System reboots cleanly; SQLite WAL journals recover without data corruption. |
