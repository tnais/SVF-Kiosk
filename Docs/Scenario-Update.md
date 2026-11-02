# SVF Kiosk â€” Updated Specification (v2.0)

*(This file is an updated, production-ready replacement for Scenarios_f0a02826.md. For complete technical architecture, see SVF_Kiosk_Specification_v2.md)*

## System Description

The system is an off-the-shelf budget computer running Debian GNU/Linux, optimized for minimal resource consumption and zero-maintenance operation. It connects to:
- A main television/display (via HDMI) for visitors in the museum hall.
- A Bluetooth remote controller (presenting as a hybrid Bluetooth mouse/keyboard HID device) for the museum guide.
- An isolated wired network interface with a local DHCP/mDNS server (`svf-kiosk.local`), allowing operators to connect a laptop via Ethernet and SSH in as a dedicated unprivileged user (`svf-operatore`).

All user-facing messages, console prompts, terminal interfaces, and on-screen display (OSD) banners are in Italian (`it_IT.UTF-8`). Code, schema, and system documentation are in English.

---

## Everyday Scenario & Guide Remote Control

In the museum hall, the volunteer guide is talking to visitors about the association's activities. The SVF Kiosk continuously plays an ambient rotation of association documentary and historical videos on the TV screen.

When the guide needs to show a specific video:
1. She presses a designated button on her Bluetooth remote:
   - **Direct Numerical Presets (1 .. 9)**: Directly jumps to pre-assigned key video clips.
   - **Menu Mode (OK / Menu)**: Displays an elegant, semi-transparent lower-third Italian OSD menu listing available videos with their display titles and descriptions.
2. The current ambient video is gracefully paused/interrupted, and its playback position is bookmarked.
3. Once the requested video finishes (or if the guide presses `ANNULLA` / `ESC`):
   - The system automatically resumes the regular ambient rotation with the next scheduled video).
   - Normal unattended playback continues without requiring any manual intervention.

---

## Daily Routine & Resilience

1. **Boot**: The system boots automatically on AC power or scheduled RTC timer into a lightweight, cursor-hidden, DPMS-inhibited Debian display session.
2. **Health Check**: Validates the SQLite database and media files. If the playlist is empty, a friendly Italian standby screen is presented (`"Nessun video presente nella scaletta. Rivolgersi all'operatore."`).
3. **Loop**: Starts continuous, resource-efficient hardware-accelerated looping via `mpv` with IPC control (`/run/svf-kiosk/mpv.sock`).
4. **Power Cut Protection**: Storage uses WAL-mode SQLite with immediate checkpointing; system base files are protected against sudden power cuts at museum closing time.

---

## New Videos & Ingestion (`svf-ingest`)

This operation will not happen during visits (too much confusion and too little space)

Operators manage media through an unprivileged SSH session:
1. **Transfer Options**:
   - Transfer files directly via SFTP/SCP into `/var/lib/svf-kiosk/media/incoming/`.
   - Plug in a USB flash drive. Operators run the provided helper command `svf-usb-sync` which uses `udisksctl` (no root password needed) to mount with safe non-executable permissions (`noexec,nosuid,nodev`), copy media to `incoming/`, and safely unmount.
2. **Ingestion Wizard (`svf-ingest`)**:
   - Creates an automatic pre-ingestion database snapshot.
   - For each newly discovered video file:
     - **Main Screen Preview Arbitration**: Prompts the operator in Italian (`"Vuoi visualizzare l'anteprima sul monitor principale della sala? [s/N]"`). If accepted, coordinates with the background player over IPC to pause ambient video and display a 15-second loop with an operator notice, preventing dual-audio or display crashes.
     - **Display Title**: Prompts for title (up to 38 characters; validated non-empty).
     - **Brief Description**: Prompts for description (up to 150 characters) shown during selection.
     - **Auto-probing**: Runs `ffprobe` to automatically record duration, codec, and resolution.
   - Moves the file to permanent archive storage and registers it in the SQLite catalog.
   - Creates an automatic post-ingestion database snapshot.

---

## Database & Data Architecture

- **Unified SQLite Database**: Stored in `/var/lib/svf-kiosk/data/svf_kiosk.db`. Replaces the prone-to-desync separate JSON playlist file with an ACID-compliant schema with foreign key constraints.
- **Tables**:
  - `videos`: `id`, `file_path`, `display_title` (up to 38 chars), `description` (up to 150 chars), `duration_seconds`, `resolution`, `date_added`, `is_deleted`.
  - `playlist`: `position` (1, 2, 3...), `video_id` (foreign key with `ON DELETE RESTRICT`).
  - `remote_presets`: `preset_key` (1-9), `video_id`.
  - `settings`: Key-value configuration (`resume_interrupted_video`, `osd_language`, etc.).
- **Automatic Backups**: Created in `/var/lib/svf-kiosk/backups/` before and after every modification session, maintaining a rolling 20-version history with automated restore tooling (`svf-backup-restore`). A human-readable JSON mirror (`playlist_export.json`) is maintained automatically.

---

## Console Playlist Editor (`svf-playlist-editor`)

A dedicated terminal application with two panels:
- **Left Panel**: *Archivio Video* (available videos sorted by display title).
- **Right Panel**: *Scaletta Attiva* (active playlist sorted by sequence position `1...N`).
- **Bottom Status & Inspector Panel**: Shows full ID, filename, 38-char title, and complete 150-char description of the currently highlighted video.
- **Color Scheme**: Black background (`#000000`), white foreground (`#FFFFFF`), reverse video for selection.
  - Videos already in the active playlist turn **Blue** on the left panel and cannot be deleted (produces an audible terminal beep and Italian error message: `"ERRORE: Impossibile eliminare un video presente nella scaletta!"`).
  - An active video undergoing reordering turns **Green** on the right panel.

### Controls & Key Bindings:
- **`TAB`**: Passes focus between Left (*Archivio*) and Right (*Scaletta*). (Ignored while a video is actively being reordered in Green).
- **`↑ / ↓` (Arrow Keys)**: Moves the cursor up/down. Clamped within list bounds (never scrolls out of range).
  - When a right-panel video is active (Green), `↑ / ↓` moves its sequence position up or down.
- **`INVIO` (Enter Key)**:
  - On Left Panel: Adds the selected video to the end of the active playlist.
  - On Right Panel: Toggles active reordering mode (turns Green to move; press `INVIO` again to lock in place).
- **`D` Key (Right Panel)**: Removes the selected video from the playlist. It immediately reverts to white in the available video list.
- **`C` Key (Left Panel - Delete)**: 
  - If video is in playlist: blocked with beep and error.
  - If video is not in playlist: asks for **double confirmation** in Italian:
    1. `"Sei sicuro di voler eliminare '%s'? [s/N]: "`
    2. `"ATTENZIONE: Il file verrÃ  spostato nel cestino di sicurezza. Confermi l'operazione? [s/N]: "`
  - If confirmed: moves media file to a 30-day safety trash directory and marks as deleted in database.
- **`S` Key**: Saves modifications to database, creates backup snapshot, updates JSON mirror, and shows confirmation notice (`"Scaletta salvata con successo nel database."`).
- **`Q` Key**: Exits the editor. If changes are unsaved, prompts: `"Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]: "`.
