# SVF Kiosk â€” System Specification & Architecture (Version 2.0)

> **Document Status**: Production Specification  
> **Replaces**: `Scenarios_f0a02826.md` (Version 1.0)  
> **Target Platform**: Debian GNU/Linux (Standard PC / Minimal Resource Footprint)  
> **Official Implementation Language**: English (Code, Comments, Architecture)  
> **User-Facing / Operator Interface Language**: Italian (`it_IT.UTF-8`)  
> **Display Server Policy**: Wayland is evil: Use X11 only

---

## 1. Executive Summary & Context

The **SVF Kiosk** is an ultra-reliable, resource-efficient video kiosk built for a small museum hall operated by an association of cultural/railway preservation volunteers.

The system performs two main duties:
1. **Unattended Ambient Playback**: Continuously loops an organized playlist of association videos on an HDMI television screen.
2. **On-Demand Volunteer Interruption**: Allows a tour guide equipped with a Bluetooth remote controller to immediately trigger a specific presentation video during a guided tour, cleanly pausing or preempting the ambient loop, and automatically resuming the ambient rotation with the next scheduled video once the presentation finishes.

Because the system runs on low-cost/budget hardware and is administered by non-technical volunteers and rotating operators, the software architecture prioritizes:
- **Zero-maintenance crash resilience**: Protection against corruptions caused by sudden wall-switch power cuts at museum closing time.
- **Strict localization**: All user-facing console prompts, on-screen display (OSD) badges, and confirmation dialogues are in clear, idiomatic Italian (`it_IT.UTF-8`).
- **Resource frugality & stability**: Minimal CPU/RAM footprint using native Debian tools, pure X11 without desktop bloat, and a lightweight hardware-accelerated media engine (`mpv` with IPC control).

---

## 2. Weaknesses Identified in Original Specification (v1.0) & Resolutions

| # | Original Weakness / Ambiguity | Risk / Failure Mode | Resolution in v2.0 (Coherent with Scenario-Update) |
|---|---|---|---|
| **W1** | **Dual Data Store** (SQLite for catalog + separate JSON for playlist) | Potential state drift, orphaned playlist entries if a video is deleted from SQLite, and file-locking races during concurrent reads/writes. | Unified in SQLite database (`svf_kiosk.db`) using atomic transactions with WAL mode. Playlists are stored in a dedicated `playlist` table with foreign key integrity, while maintaining an optional JSON export cache for human inspection. |
| **W2** | **Display Contention during Video Ingest & Preview** | Running video preview over SSH while visitors watch the TV creates audio/video clashes or crashes the display server. | Resolved by clear operational policy: **Ingestion and file management are strictly prohibited during visitor hours** ("too much confusion and too little space"). For off-hours maintenance, an IPC lock coordinates preview playback cleanly. |
| **W3** | **Unspecified Remote Control UX & Resumption Logic** | Ambiguity on how videos are selected on a remote, what happens on sleep/reconnect, and how the playlist resumes. | Defined clear remote control schemes: (A) Direct 1 .. 9 numerical presets for top presentation clips; (B) Discrete on-screen carousel menu (OK / Menu). Resumption policy is explicitly set: **playback resumes with the next scheduled video** upon completion or cancellation (`ANNULLA` / `ESC`). |
| **W4** | **Non-Root USB Mounting via SSH** | Unprivileged users cannot invoke `mount` in Debian without root privileges, causing ingest step 2 to fail. | Configured standard `udisks2` / polkit rules allowing USB media mounting into `/media/svf-usb/` with `noexec,nosuid,nodev` safe flags and an interactive helper script `svf-usb-sync`. |
| **W5** | **Direct Hard File Deletion Risk** ("C" key in TUI deletes both DB record and file system) | Accidental loss of irreplaceable museum archival videos if the only copy exists on the kiosk. | Implemented a 30-day safety quarantine trash directory (`/var/lib/svf-kiosk/trash/`) prior to permanent purge, with mandatory double confirmation in Italian (`[s/N]`). |
| **W6** | **Display Title Limitation (Original 20 chars)** | 20 characters is too short for descriptive Italian titles (e.g., *"Restauro Locomotiva Gr. 625"* is 29 chars). | Increased title column limit to **38 characters** (coherent with Scenario-Update) in schema and TUI, with full 150-character multi-line description inspector panel at the screen bottom. |
| **W7** | **Unspecified Kiosk Process Management & DPMS** | Screen blanking/blackout after 10 minutes of inactivity, visible mouse cursor, and lack of recovery if media player crashes. | Added dedicated `systemd` user service with `Restart=always`, pure X11 DPMS/screensaver inhibitor (`xset s off -dpms`, Wayland strictly forbidden), and cursor autohider (`unclutter -idle 0.5`). |
| **W8** | **Missing Italian Strings & Prompts** | No explicit wording specified for error messages, confirmations, and OSD labels. | Comprehensive Italian string catalog codified in UTF-8 in Section 8 of this document. |
| **W9** | **Typographical & Encoding Inconsistencies** | Typos in v1.0 and Windows CP-1252 / mojibake artifacts. | Fully corrected and standardized in pure UTF-8 encoding. |

---

## 3. System Architecture & Hardware Topology

```
+------------------------------------------------------------------------+
|                          MUSEUM HALL HARDWARE                          |
|                                                                        |
|  +-------------------+       Bluetooth HID       +------------------+  |
|  | Bluetooth Remote  | ------------------------> | Debian Kiosk PC  |  |
|  | (Keys: 1..9, OK,  |                           | (x86_64 or ARM64 |  |
|  |  Play/Pause, ESC) |                           |  Low-cost MiniPC)|  |
|  +-------------------+                           +--------+---------+  |
|                                                           |            |
|                                                HDMI Out   |            |
|                                                           v            |
|                                                  +------------------+  |
|                                                  | TV / Display     |  |
|                                                  | (1080p / 4K)     |  |
|                                                  +------------------+  |
+------------------------------------------------------------------------+
                                    ^
                                    | Wired Ethernet
                                    v
+------------------------------------------------------------------------+
|                         OPERATOR LAPTOP (SSH)                          |
|                     (Maintenance outside visit hours)                  |
|                                                                        |
|  - SFTP / SCP video upload to `/var/lib/svf-kiosk/media/incoming/`     |
|  - USB drive mounting via `svf-usb-sync`                               |
|  - Video ingestion & metadata tool: `svf-ingest`                       |
|  - Interactive 2-panel playlist editor: `svf-playlist-editor`          |
+------------------------------------------------------------------------+
```

### 3.1 Network Configuration
*Will be handled in a separated document by a trusted human specialist.*

### 3.2 Display Server & Media Engine
- **Display Engine**: Minimal **X11 only** (Wayland is strictly excluded). Uses a minimal `xinit` / lightweight X11 display session auto-starting without desktop environment bloat:
  - Screen blanking / DPMS disabled: `xset s off -dpms`
  - Mouse cursor auto-hidden: `unclutter -idle 0.5 -root`
- **Media Player**: `mpv` compiled with hardware acceleration (`vaapi` / `vdpau`), configured with:
  ```ini
  # /etc/svf-kiosk/mpv.conf
  vo=gpu
  hwdec=auto-safe
  no-terminal
  cursor-autohide=always
  cursor-autohide-fs-only
  input-ipc-server=/run/svf-kiosk/mpv.sock
  loop-playlist=inf
  osd-font="DejaVu Sans"
  osd-font-size=32
  osd-color="#FFFFFFFF"
  osd-border-color="#FF000000"
  osd-border-size=2
  ```

---

## 4. Database Schema & Storage Model

All video metadata and playlists are maintained in SQLite (`/var/lib/svf-kiosk/data/svf_kiosk.db`).

### 4.1 SQLite Schema (`schema.sql`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Video Archive Catalog
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,       -- Relative to media root, allows subfolders
    display_title TEXT NOT NULL,          -- Up to 38 characters (coherent with Scenario-Update)
    description TEXT,                     -- Up to 150 characters, descriptive summary
    duration_seconds INTEGER DEFAULT 0,   -- Auto-probed via ffprobe
    resolution TEXT DEFAULT '',           -- e.g. '1920x1080'
    date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0,         -- 0 = active, 1 = in safety trash
    deleted_at DATETIME NULL
);

-- Active Kiosk Playlist
CREATE TABLE IF NOT EXISTS playlist (
    position INTEGER PRIMARY KEY,         -- 1, 2, 3... sequential playback order
    video_id INTEGER NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE RESTRICT
);

-- Remote Control Preset Triggers (Hotkeys 1-9 on Remote)
CREATE TABLE IF NOT EXISTS remote_presets (
    preset_key INTEGER PRIMARY KEY CHECK(preset_key BETWEEN 1 AND 9),
    video_id INTEGER NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- System Configuration & Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Default Settings Seed (Resumption advances to next scheduled video per Scenario-Update)
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('resume_interrupted_video', 'false'),
    ('resume_policy', 'next_video'),
    ('osd_language', 'it_IT'),
    ('transition_delay_ms', '500'),
    ('safety_trash_days', '30');
```

### 4.2 Backup Strategy
- **Pre-edit Snapshot**: Before any modification in `svf-playlist-editor` or `svf-ingest`, the database is backed up to `/var/lib/svf-kiosk/backups/svf_kiosk_pre_{TIMESTAMP}.db`.
- **Post-edit Snapshot**: Upon clean user exit/save, a snapshot `/var/lib/svf-kiosk/backups/svf_kiosk_post_{TIMESTAMP}.db` is created.
- **Rotation**: Automated retention keeps the last 20 snapshots and purges older ones.
- **JSON Export**: For auditability and fast fallback, the system automatically writes a read-only mirror to `/var/lib/svf-kiosk/data/playlist_export.json` on each commit.

---

## 5. Daily Routine & Playback Scenarios

### 5.1 System Boot Routine
1. Computer powers on (scheduled BIOS/UEFI wake or main hall circuit breaker).
2. Debian boots in multi-user target, launches `svf-kiosk.service`.
3. Startup script executes verification check:
   - Validates existence of `/var/lib/svf-kiosk/data/svf_kiosk.db`.
   - Checks that at least 1 video exists in `playlist` table and that referenced media files exist on disk.
   - If empty or missing files detected: displays fallback Italian slide (`"Nessun video presente nella scaletta. Rivolgersi all'operatore."`) while attempting database auto-repair from latest backup.
4. `mpv` launches in fullscreen borderless mode on primary display (`:0`).
5. Ambient rotation begins, cycling through playlist positions `1 -> N -> 1`.

### 5.2 On-Demand Guide Interruption Scenario
1. **Volunteer Action**: The museum guide uses the Bluetooth remote:
   - **Direct Numerical Presets (1 .. 9)**: Directly jumps to pre-assigned key video clips.
   - **Menu Mode (OK / Menu)**: Displays an elegant, semi-transparent lower-third Italian OSD menu listing available videos with their display titles and descriptions.
2. **Player Reaction**:
   - The current ambient video is gracefully paused/interrupted, and its playback position is bookmarked.
   - The requested special video starts playing immediately with high priority.
3. **Completion & Resume (Coherent with Scenario-Update)**:
   - Once the requested video finishes (or if the guide presses `ANNULLA` / `ESC`):
   - **The system automatically resumes the regular ambient rotation with the next scheduled video.**
   - Normal unattended playback continues without requiring any manual intervention.

---

## 6. Video Ingestion Tool (`svf-ingest`) Workflow

> **Operational Rule**: *This operation will not happen during visits (too much confusion and too little space).*  
> Ingestion is performed exclusively during closed museum hours by operators over SSH (`svf-operatore@svf-kiosk.local`).

### Step 1: File Transfer
- **Via SFTP**: Operator transfers video files (`.mp4`, `.mkv`, `.mov`) directly to `/var/lib/svf-kiosk/media/incoming/`.
- **Via USB Drive**: Operator plugs USB drive into the kiosk. Runs helper command:
  ```bash
  svf-usb-sync
  ```
  This securely mounts the removable device (via `udisksctl` with safe `noexec,nosuid,nodev` flags), scans for valid media containers, displays detected files, and copies them to the incoming directory.

### Step 2: Ingestion Wizard (`svf-ingest`)
When launched outside visit hours, `svf-ingest` performs:
1. Automatic pre-backup of database.
2. Scans `/var/lib/svf-kiosk/media/incoming/` for unindexed media.
3. For each detected file:
   - **Main Display Preview Arbitration**: 
     Prompts operator in Italian:
     ```
     Vuoi visualizzare l'anteprima sul monitor principale della sala? [s/N]:
     ```
     If accepted: sends IPC command to running kiosk daemon to pause ambient video and display a 15-second loop preview with an Italian overlay:  
     `"ANTEPRIMA OPERATORE: Verifica filmato in corso..."`.  
     Once checked or dismissed, ambient video resumes.
   - **Display Title Input**: Operator enters title (validated up to **38 characters**, mandatory non-empty, coherent with Scenario-Update).
   - **Brief Description Input**: Operator enters description (up to **150 characters**).
   - **Technical Auto-probing**: File duration, audio channels, and video resolution are automatically captured via `ffprobe` and stored in SQLite.
4. Moves the file from `incoming/` to the permanent storage `/var/lib/svf-kiosk/media/archive/`.
5. Post-backup of database executed automatically.

---

## 7. Interactive Playlist Editor (`svf-playlist-editor`)

Console-based TUI (Terminal User Interface) built using `ncurses` or `textual`, designed for standard 80x24 terminal windows over SSH.

### 7.1 Visual Layout (Black background `#000000`, White foreground `#FFFFFF`)

```
========================= GESTORE SCALETTA SVF-KIOSK =========================
 [PANNELLO SINISTRO: Archivio Video]       [PANNELLO DESTRO: Scaletta Attiva]
 +-------------------------------------+   +---------------------------------+
 | [01] Arrivo treno storico 1928      |   | 1. *Restauro Gr. 625 (04:12)    |
 | [02] Centenario Stazione            |   | 2.   Centenario Stazione (02:45)|
 | [03] Intervista Macchinista         |   | 3.   Locomotiva a Vapore (08:20)|
 | [04] Lavori in Officina             |   |                                 |
 |>[05] Manutenzione Caldaia          <|   |                                 |
 | [06] Modellismo Ferroviario         |   |                                 |
 +-------------------------------------+   +---------------------------------+
 SCHEDA DETTAGLI:
 Titolo: Manutenzione Caldaia  | ID: 5 | Durata: 06:15 | File: 2026/caldaia.mp4
 Descrizione: Riprese delle operazioni di smontaggio tubi fumo e prova idraulica
 effettuata dai soci volontari nell'officina museale.
------------------------------------------------------------------------------
 COMANDI: [TAB] Cambia Pannello | [â†‘ / â†“] Scorri | [INVIO] Azione | [C] Elimina
          [D] Rimuovi da Scaletta | [S] Salva modifiche | [Q] Esci
==============================================================================
```

### 7.2 Styling & Color Rules
- **Foreground / Background**: White text on black background.
- **Cursor Selection**: Row shown in reverse video (black on white).
- **Playlist Membership Indicator**: In the left panel (*Archivio*), any video that already belongs to the active playlist is displayed with a **Blue** prefix or label and cannot be deleted (`"ERRORE: Impossibile eliminare un video presente nella scaletta!"` with audible beep).
- **Active Reordering State**: When a playlist video on the right panel is activated with `INVIO`, its text color turns **Green** (or bold green reverse). In this state, `â†‘ / â†“` move its sequence position. Pressing `INVIO` again deactivates and confirms the new position.

### 7.3 Detailed Key Bindings

| Context | Key | Action & Constraint |
|---|---|---|
| **Global** | `TAB` | Toggles focus between *Archivio Video* (Left) and *Scaletta Attiva* (Right). If a video is in active reorder state, `TAB` is ignored until deactivated. |
| **Global** | `S` | Saves current playlist modifications to SQLite, updates backup, and exports JSON. Displays confirmation in Italian. |
| **Global** | `Q` | Exits the editor. If unsaved changes exist, prompts: `"Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]"`. |
| **Left Panel** (Archivio) | `â†‘ / â†“` | Moves cursor up/down. Clamped between index 0 and `N-1` (never scrolls out of bounds). |
| **Left Panel** (Archivio) | `INVIO` (Enter) | Appends selected video to the end of the active playlist. The video turns Blue on the left panel. |
| **Left Panel** (Archivio) | `C` | Initiates deletion. **Safety Protocol**: <br>1. Checks if video is in active playlist; if yes, blocks with error beep.<br>2. First confirmation: `"Sei sicuro di voler eliminare '%s'? [s/N]: "`<br>3. Second confirmation: `"ATTENZIONE: Il file verrÃ  spostato nel cestino di sicurezza. Confermi l'operazione? [s/N]: "`<br>If both confirmed: file moved to trash, DB flag updated. |
| **Right Panel** (Scaletta) | `â†‘ / â†“` | When inactive: moves selection cursor up/down.<br>When active (Green): swaps video position with neighbor above/below (clamped to bounds `1` and `Total`). |
| **Right Panel** (Scaletta) | `INVIO` (Enter) | Toggles active reordering state (turns Green on activate, turns normal on deactivate). |
| **Right Panel** (Scaletta) | `D` | Removes selected video from active playlist. Video returns to normal white in the left panel. |

---

## 8. Complete Italian Localization Dictionary (`it_IT.UTF-8`)

All user interfaces, CLI tools, error dialogs, and OSD television alerts strictly utilize these standardized UTF-8 Italian strings:

| Message ID | Standardized Italian Text (UTF-8) | Context / Usage |
|---|---|---|
| `MSG_BOOT_START` | `Avvio sistema SVF-Kiosk in corso...` | Boot splash screen |
| `MSG_BOOT_EMPTY` | `Nessun video presente nella scaletta. Rivolgersi all'operatore.` | Error screen if playlist is empty |
| `MSG_OSD_TRIGGER` | `â–¶ Riproduzione richiesta: %s` | OSD TV banner when remote triggers video |
| `MSG_OSD_RESUME_NEXT` | `Ripresa scaletta normale: riproduzione del prossimo filmato...` | OSD TV banner when resuming next video |
| `MSG_OSD_PREVIEW` | `MODALITÃ€ ANTEPRIMA: Controllo video da operatore SSH` | OSD TV banner during SSH test playback |
| `MSG_TUI_CONFIRM_DEL_1` | `Sei sicuro di voler eliminare '%s'? [s/N]: ` | First deletion confirmation |
| `MSG_TUI_CONFIRM_DEL_2` | `ATTENZIONE: Il file verrÃ  spostato nel cestino di sicurezza. Confermi l'operazione? [s/N]: ` | Second deletion confirmation |
| `MSG_TUI_ERR_IN_PLAYLIST`| `ERRORE: Impossibile eliminare! Il video Ã¨ utilizzato nella scaletta.` | Deletion blocked message |
| `MSG_TUI_SAVED` | `Scaletta salvata con successo nel database.` | Save completion notice |
| `MSG_TUI_UNSAVED_EXIT` | `Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]: ` | Unsaved changes dialog on quit |
| `MSG_USB_DETECTED` | `Supporto USB rilevato: %s. Avvio scansione filmati...` | USB tool greeting |
| `MSG_USB_COPY_SUCCESS` | `Copia completata: %d nuovi video trasferiti nell'archivio.` | USB sync report |
| `MSG_PREVIEW_PROMPT` | `Vuoi visualizzare l'anteprima sul monitor principale della sala? [s/N]: ` | SSH ingest prompt |

---

## 9. Security, Maintenance & Failure Recovery Procedures

1. **Power Cut Immunity**: 
   - Root filesystem can be mounted with Debian `overlayroot` (read-only base OS).
   - Only `/var/lib/svf-kiosk/` is mounted read-write with ext4 journal data ordering (`data=ordered`) and SQLite in WAL mode with synchronous checkpointing.
2. **Watchdog & Automated Health Check**:
   - `systemd` user service runs with `Restart=always` and `RestartSec=3s`.
   - If `mpv` exits or hangs, the service restarts seamlessly within 3 seconds.
3. **Display Server Guarantee**:
   - Strictly X11 only. No Wayland compositor dependencies.
4. **Bluetooth Recovery**:
   - `bluetoothctl` configured with auto-reconnect (`AutoConnect=true`) for the registered remote MAC address.
   - Low-latency input handling prevents keystroke buffering if remote sleeps.
5. **Remote Operators Toolkit**:
   - `svf-status`: Prints current playing video, CPU temperature, memory usage, and playlist status.
   - `svf-restart`: Gracefully restarts media playback without rebooting Linux.
   - `svf-backup-restore`: Allows instant rollback to any of the 20 pre/post snapshot backups.
