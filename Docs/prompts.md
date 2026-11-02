# Prompt 1 — Scaffolding del Progetto e Catalogo Testi in Italiano (src/core/strings.py)

You are developing the "SVF Kiosk" application for a railway museum on Debian 12 minimal (X11).
Following `copilot.instruction.md`, create the project structure configuration and the Italian localization string catalog.

Target files to create:
1. `pyproject.toml` (or `setup.py`):
    - Package name: `svf-kiosk` (version 2.0.0).
    - Python requirement: `>=3.11`.
    - Dependencies: `textual>=0.85.0`, `pydantic>=2.10.0`, `python-mpv-jsonipc>=1.1.1`, `pytest>=8.3.0`.
    - Entry points:
        - `svf-ingest = cli.ingest:main`
        - `svf-usb-sync = cli.usb_sync:main`
        - `svf-playlist-editor = tui.playlist_editor:main`
        - `svf-kiosk-daemon = daemon.kiosk_player:main`
        - `svf-status = cli.status:main`
        - `svf-restore = cli.restore:main`
2. `config/mpv.conf`:
    - Hardware acceleration: `hwdec=auto-safe`, `vo=gpu`.
    - Kiosk settings: `fullscreen=yes`, `no-terminal=yes`, `cursor-autohide=always`, `cursor-autohide-fs-only=yes`.
    - Socket: `input-ipc-server=/run/svf-kiosk/mpv.sock`.
    - Loop: `loop-playlist=inf`.
    - OSD: `osd-font="DejaVu Sans"`, `osd-font-size=32`.
3. `src/core/strings.py`:
    - Pure UTF-8 class `ItalianStrings` containing frozen string constants for all operator and kiosk messages (e.g., visit hours warnings, USB detection, deletion confirmations with `[s/N]`, playback status banners, and hardware diagnostics).

Ensure 100% clean UTF-8 encoding with no legacy Windows code pages or corrupted characters.

# Prompt 2 — Modelli Pydantic e Validazione (src/models/video.py)

Create the data models for SVF Kiosk in `src/models/video.py` following SpecificationV2.

Requirements:
1. Use Pydantic v2.
2. `VideoMetadata` model:
    - `id`: Optional[int] = None
    - `file_path`: str (must end with .mp4, .mkv, .mov, or .avi)
    - `display_title`: str (mandatory, strictly max 38 characters; strip leading/trailing whitespace; raise ValueError if empty or > 38 chars)
    - `description`: Optional[str] = "" (strictly max 150 characters; raise ValueError if > 150 chars)
    - `duration_seconds`: int = 0
    - `resolution`: str = ""
    - `date_added`: Optional[datetime] = None
    - `is_deleted`: bool = False
    - `deleted_at`: Optional[datetime] = None
3. `PlaylistItem` model:
    - `position`: int (>= 1)
    - `video`: VideoMetadata
4. `RemotePreset` model:
    - `preset_key`: int (between 1 and 9)
    - `video_id`: int
5. `KioskState` model:
    - `is_playing`: bool
    - `current_video`: Optional[VideoMetadata]
    - `elapsed_seconds`: float
    - `total_seconds`: float
    - `mode`: str ("ambient" | "on_demand" | "preview" | "standby")

Include unit tests in `tests/test_models.py` verifying that:
- Titles longer than 38 characters are rejected.
- Descriptions longer than 150 characters are rejected.
- Valid models serialize cleanly to dict and JSON.

# Prompt 3 — Livello di Persistenza SQLite & Motore di Backup (src/db/database.py)

Implement the SQLite database and automated backup engine for SVF Kiosk in `src/db/database.py`.

Requirements:
1. Pure UTF-8 encoding.
2. SQLite initialization and configuration:
    - Database path defaults to `{SVF_ROOT}/data/svf_kiosk.db`.
    - Enforce pragmas on every connection:
        - `PRAGMA journal_mode = WAL;`
        - `PRAGMA foreign_keys = ON;`
        - `PRAGMA synchronous = NORMAL;`
3. Schema creation:
    - Table `videos`: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `file_path TEXT NOT NULL UNIQUE`, `display_title TEXT NOT NULL`, `description TEXT`, `duration_seconds INTEGER DEFAULT 0`, `resolution TEXT DEFAULT ''`, `date_added DATETIME DEFAULT CURRENT_TIMESTAMP`, `is_deleted INTEGER DEFAULT 0`, `deleted_at DATETIME NULL`.
    - Table `playlist`: `position INTEGER PRIMARY KEY`, `video_id INTEGER NOT NULL`, `FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE RESTRICT`.
    - Table `remote_presets`: `preset_key INTEGER PRIMARY KEY CHECK(preset_key BETWEEN 1 AND 9)`, `video_id INTEGER NOT NULL`, `FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE`.
    - Table `settings`: `key TEXT PRIMARY KEY`, `value TEXT NOT NULL`.
4. Backup & Mirror Engine:
    - `create_backup(prefix: str) -> str`: creates an atomic snapshot using `sqlite3.Connection.backup()` to `{SVF_ROOT}/backups/svf_kiosk_{prefix}_{timestamp}.db`.
    - `rotate_backups(keep_count: int = 20)`: retains only the 20 most recent backup files and deletes older snapshots.
    - `export_json_mirror()`: writes an atomic JSON mirror of the active playlist to `{SVF_ROOT}/data/playlist.json` using a temporary file and `os.replace`.
5. CRUD & Business Logic:
    - `get_available_videos()`: returns all non-deleted videos sorted by `display_title`.
    - `get_playlist()`: returns active playlist ordered by `position`.
    - `add_to_playlist(video_id: int)`: appends video to the end of the playlist.
    - `remove_from_playlist(position: int)`: removes item and re-indexes remaining positions sequentially.
    - `reorder_playlist(source_pos: int, target_pos: int)`: atomic position swap/shift within a transaction.
    - `soft_delete_video(video_id: int, trash_dir: str)`: verifies video is NOT in the active playlist (raises error if present); moves file to trash folder and sets `is_deleted = 1`.

Write thorough unit tests in `tests/test_db.py` covering:
- WAL mode active verification.
- Foreign key constraint enforcement.
- Backup creation and 20-file rolling retention.
- Reordering and soft deletion restrictions.

# Prompt 4 — Client IPC UNIX per mpv (src/core/mpv_client.py)

Create the UNIX socket IPC client for mpv in `src/core/mpv_client.py` for SVF Kiosk.

Requirements:
1. Target socket: `/run/svf-kiosk/mpv.sock` (configurable via environment variable `SVF_IPC_SOCK`).
2. Implement synchronous and asynchronous JSON-IPC communication with the running mpv process over AF_UNIX socket.
3. Essential methods:
    - `is_running() -> bool`: checks if socket exists and responds to a `get_property` ping.
    - `load_file(path: str, mode: str = "replace")`: sends `["loadfile", path, mode]`.
    - `load_playlist(file_paths: list[str])`: clears current playlist and loads new sequence.
    - `pause()`, `resume()`, `stop()`.
    - `get_playback_status() -> dict`: returns `{"file": str, "time_pos": float, "duration": float, "paused": bool}`.
    - `show_osd(text: str, duration_ms: int = 3000)`: sends `["show-text", text, str(duration_ms)]`.
    - `play_preview(path: str, duration_sec: int = 15)`: pauses ambient playback, loads preview file, flashes OSD "ANTEPRIMA OPERATORE", waits 15 seconds, and resumes previous state.
4. Robust error handling:
    - If socket is unavailable, methods must raise a clean custom exception `MpvIpcError` without crashing the caller.

Include unit tests in `tests/test_mpv_client.py` using a mock UNIX socket server.

# Prompt 5 — Riconoscimento USB & Wizard di Acquisizione Filmati (src/cli/usb_sync.py e src/cli/ingest.py)

Implement the USB mounting helper and interactive ingestion CLI tools in `src/cli/usb_sync.py` and `src/cli/ingest.py`.

Context & Operational Rules:
- All user prompts, progress messages, and error dialogues MUST use Italian (`it_IT.UTF-8`).
- Operational Rule from SpecificationV2: Video ingestion is NOT performed during visitor hours. If kiosk is active, warn operator or offer IPC preview on the main monitor.
- Enforce limits: `display_title` <= 38 characters, `description` <= 150 characters.

Requirements for `src/cli/usb_sync.py`:
1. Use `udisksctl` via Python `subprocess` (requires no root password).
2. Scan for connected USB partitions in `/dev/sd*`.
3. Mount safely with `udisksctl mount -b <partition>`.
4. Scan for video files (`.mp4`, `.mkv`, `.mov`, `.avi`).
5. Copy newly detected media files to `{SVF_ROOT}/media/incoming/` with a progress indicator.
6. Safely unmount device with `udisksctl unmount -b <partition>`.
7. Print formatted Italian summary messages.

Requirements for `src/cli/ingest.py`:
1. Scan `{SVF_ROOT}/media/incoming/` for unindexed video files.
2. Trigger pre-ingest database backup: `db.create_backup("pre_ingest")`.
3. For each incoming file:
    - Inspect duration, resolution, video codec, and audio channels using `ffprobe` (JSON output).
    - IPC Preview Prompt:
      "Vuoi visualizzare l'anteprima sul monitor principale della sala? [s/N]: "
      If yes, call `mpv_client.play_preview()`.
    - Prompt operator for Display Title:
      Enforce non-empty and <= 38 characters. Loop with clear Italian error if exceeded.
    - Prompt operator for Description:
      Enforce <= 150 characters.
    - Move file from `incoming/` to `{SVF_ROOT}/media/archive/<sanitized_name>`.
    - Insert video into SQLite database.
4. Trigger post-ingest backup: `db.create_backup("post_ingest")` and `db.rotate_backups()`.
5. Print final Italian summary report.

Include tests in `tests/test_ingest.py` mocking `ffprobe` and `udisksctl`.

# Prompt 6 — Editor della Scaletta a Due Pannelli in Terminale (src/tui/playlist_editor.py)

Create the two-panel Terminal User Interface (TUI) playlist editor in `src/tui/playlist_editor.py` using Textual (or curses) for SVF Kiosk.

Layout & Appearance:
- Strictly compatible with standard 80x24 VT100 / Linux SSH terminals.
- High contrast: Black background (`#000000`), white text (`#FFFFFF`), reverse video for cursor.
- Top Header: "========================= GESTORE SCALETTA SVF-KIOSK =========================".
- Left Panel: "Archivio Video (Disponibili)" (sorted alphabetically by title).
- Right Panel: "Scaletta Attiva (In Riproduzione)" (sorted by playlist position).
- Visual Color Coding:
    - Blue/Cyan text: Videos currently assigned to the active playlist. These CANNOT be deleted from the archive.
    - Green background/highlight: The row currently being moved/reordered in the right panel.
- Bottom Details Inspector:
  Displays highlighted video's ID, Title (max 38 chars), Duration (mm:ss), File Path, and Description (max 150 chars).
- Footer Keymap:
  "[TAB] Cambia Pannello | [↑/↓] Scorri | [INVIO] Azione | [C] Elimina | [D] Rimuovi | [S] Salva | [Q] Esci"

Interactive Behavior:
1. `TAB`: Switch active focus between Left and Right panels (disabled during active row reordering).
2. `↑ / ↓`: Scroll list with bounded index navigation.
3. Left Panel Actions:
    - `INVIO`: Add highlighted video to the end of the active playlist (item turns Blue).
    - `C`: Delete video.
        - If video is in playlist: emit terminal bell (`\a`) and display Italian error:
          "ERRORE: Impossibile eliminare! Il video è utilizzato nella scaletta."
        - If video is free: require DOUBLE Italian confirmation:
          1st prompt: "Sei sicuro di voler eliminare '{title}'? [s/N]: "
          2nd prompt: "ATTENZIONE: Il file verrà spostato nel cestino di sicurezza. Confermi l'operazione? [s/N]: "
          If both confirmed, move file to `{SVF_ROOT}/trash/` and flag as soft-deleted in SQLite.
4. Right Panel Actions:
    - `INVIO`: Toggle active reorder mode (row turns Green). While active, `↑ / ↓` moves the row up or down. Pressing `INVIO` again commits position.
    - `D`: Remove selected video from playlist (item reverts to normal white in Left Panel).
5. Global Actions:
    - `S`: Commit changes to SQLite, write backup snapshot, export `playlist.json`, and show confirmation.
    - `Q`: Quit. If unsaved changes exist, prompt: "Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]: ".

# Prompt 7 — Demone di Riproduzione e Ricevitore Telecomando Bluetooth (src/daemon/kiosk_player.py)

Implement the main background media playback and Bluetooth remote control daemon in `src/daemon/kiosk_player.py`.

Requirements:
1. Execution Environment:
    - Runs under minimal X11 (`DISPLAY=:0`).
    - Wayland is strictly forbidden.
    - mpv socket: `/run/svf-kiosk/mpv.sock`.
2. mpv Process Management:
    - Spawn mpv with flags: `--vo=gpu --hwdec=auto-safe --fullscreen --no-terminal --cursor-autohide=always --cursor-autohide-fs-only --input-ipc-server=/run/svf-kiosk/mpv.sock --loop-playlist=inf --osd-font="DejaVu Sans" --osd-font-size=32`.
    - Watchdog: If mpv process crashes, restart it within 3 seconds without losing current playlist state.
3. Ambient Loop:
    - Read active playlist from SQLite.
    - If playlist is empty, render a standby screen:
      "Nessun video presente nella scaletta. Rivolgersi all'operatore."
    - Otherwise, play items in continuous rotation.
4. Bluetooth Remote Controller Listener:
    - Capture keyboard HID events from `/dev/input/event*` (using `evdev` or X11 keypresses).
    - Keys `1` to `9`:
        - Lookup video mapped in `remote_presets` table.
        - If mapped: interrupt ambient loop, flash OSD "▶ Riproduzione richiesta: {title}" for 3s, and play selected video immediately.
    - Key `OK` / `Menu`:
        - Open discreet lower-third on-screen carousel menu listing all available videos. Up/Down to navigate, OK to select.
    - Key `ESC` / `Annulla`:
        - Abort on-demand playback immediately.
5. RESUMPTION POLICY (SpecificationV2 Coherence):
    - When an on-demand video finishes or is aborted with ESC:
        - The daemon MUST resume the ambient rotation with the NEXT scheduled video in order:
          `next_index = (interrupted_index + 1) % total_playlist_items`.
        - Flash brief OSD: "Ripresa scaletta normale: riproduzione del prossimo filmato...".
6. Graceful shutdown on SIGTERM / SIGINT: terminate mpv and remove socket file.

Write tests in `tests/test_daemon.py` simulating preset triggers and verifying the next-video resumption calculation.

# Prompt 8 — Strumenti CLI di Diagnostica e Ripristino Backup (src/cli/status.py e src/cli/restore.py)

Create the diagnostic and rollback CLI tools in `src/cli/status.py` and `src/cli/restore.py`.

Requirements:
1. `svf-status` (`src/cli/status.py`):
    - Connect to `/run/svf-kiosk/mpv.sock` and report: current playing file, elapsed time, duration, and paused state.
    - System telemetry:
        - CPU temperature from `/sys/class/thermal/thermal_zone0/temp`.
        - RAM usage and free disk space in `/var/lib/svf-kiosk`.
        - Display state (`xrandr` output on `DISPLAY=:0`).
    - Bluetooth status: inspect `bluetoothctl info` to report connected remote address and battery status.
    - Output formatted report strictly in Italian UTF-8.
2. `svf-restore` (`src/cli/restore.py`):
    - List available backup snapshots in `{SVF_ROOT}/backups/` sorted by date descending.
    - Allow operator to select a snapshot number.
    - Create a safety backup of the current database before restoring (`db.create_backup("pre_restore")`).
    - Restore selected snapshot over `svf_kiosk.db`.
    - Regenerate `playlist.json` mirror.
    - Trigger daemon reload or restart (`systemctl --user restart svf-kiosk.service`).
    - Print Italian confirmation: "Ripristino completato con successo. Scaletta ricaricata."

# Prompt 9 — Script di Provisioning Debian e Servizi Systemd (scripts/setup-kiosk.sh e Unit Files)

Create the production deployment and automation scripts for Debian 12 minimal in `scripts/`:

1. `systemd/svf-kiosk.service`:
    - Runs as user `svf-operatore`.
    - Environment: `DISPLAY=:0`, `XAUTHORITY=/home/svf-operatore/.Xauthority`, `PYTHONUNBUFFERED=1`.
    - `ExecStartPre`: wait for X11 socket `/tmp/.X11-unix/X0`.
    - `ExecStart=/opt/svf-kiosk/venv/bin/svf-kiosk-daemon`.
    - `Restart=always`, `RestartSec=3`.
2. `scripts/x11-session.sh`:
    - Launch minimal X11 session with `xset s off -dpms` (disable screen blanking and power saving).
    - Start `unclutter -idle 0.5 -root` (hide mouse cursor).
    - Start window manager or launch daemon directly.
3. `scripts/setup-kiosk.sh`:
    - Bash script with `set -euo pipefail`.
    - Verify execution on Debian 12 (check `/etc/debian_version`).
    - Check and configure Italian locale (`it_IT.UTF-8`).
    - Install required apt packages (`xorg`, `unclutter`, `mpv`, `ffmpeg`, `sqlite3`, `python3-venv`, `udisks2`, `bluez`).
    - Configure `/etc/polkit-1/rules.d/50-svf-usb-mount.rules` for non-root USB mounting by `svf-operatore`.
    - Set up `/var/lib/svf-kiosk/{data,media/archive,media/incoming,trash,backups}` with permissions `775 svf-operatore:svf-operatore`.
    - Initialize Python virtualenv and install `svf-kiosk`.
    - Enable and start systemd user/system services.

