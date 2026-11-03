"""Frozen Italian-language messages used by operators and the kiosk."""


class ItalianStrings:
    MSG_BOOT_START = "Avvio sistema SVF-Kiosk in corso..."
    MSG_BOOT_EMPTY = "Nessun video presente nella scaletta. Rivolgersi all'operatore."
    MSG_OSD_TRIGGER = "▶ Riproduzione richiesta: {title}"
    MSG_OSD_RESUME_NEXT = "Ripresa scaletta normale: riproduzione del prossimo filmato..."
    MSG_OSD_PREVIEW = "MODALITÀ ANTEPRIMA: Controllo video da operatore SSH"
    MSG_OSD_PLAYING = "In riproduzione: {title}"
    MSG_OSD_PAUSED = "Riproduzione in pausa."
    MSG_OSD_STOPPED = "Riproduzione interrotta."

    MSG_TUI_CONFIRM_DEL_1 = "Sei sicuro di voler eliminare '{title}'? [s/N]: "
    MSG_TUI_CONFIRM_DEL_2 = (
        "ATTENZIONE: Il file verrà spostato nel cestino di sicurezza. "
        "Confermi l'operazione? [s/N]: "
    )
    MSG_TUI_ERR_IN_PLAYLIST = (
        "ERRORE: Impossibile eliminare! Il video è utilizzato nella scaletta."
    )
    MSG_TUI_SAVED = "Scaletta salvata con successo nel database."
    MSG_TUI_UNSAVED_EXIT = (
        "Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]: "
    )

    MSG_USB_DETECTED = "Supporto USB rilevato: {device}. Avvio scansione filmati..."
    MSG_USB_COPY_SUCCESS = (
        "Copia completata: {count} nuovi video trasferiti nell'archivio."
    )
    MSG_USB_MOUNT_FAILED = "ERRORE: Impossibile montare il supporto USB {device}."
    MSG_USB_UNMOUNT_FAILED = "ERRORE: Impossibile espellere il supporto USB {device}."
    MSG_PREVIEW_PROMPT = (
        "Vuoi visualizzare l'anteprima sul monitor principale della sala? [s/N]: "
    )
    MSG_VISIT_HOUR_WARNING = (
        "ATTENZIONE: Operazione vietata durante l'orario di visita del museo."
    )

    MSG_HW_ACCEL_ENABLED = "Accelerazione hardware video attiva."
    MSG_HW_ACCEL_UNAVAILABLE = (
        "ATTENZIONE: Accelerazione hardware non disponibile; uso della modalità software."
    )
    MSG_HW_DISPLAY_UNAVAILABLE = (
        "ERRORE: Display X11 non disponibile. Verificare il collegamento al monitor."
    )
    MSG_MPV_STARTING = "Avvio del lettore video in corso..."
    MSG_MPV_UNAVAILABLE = "ERRORE: Il lettore video mpv non è disponibile."
    MSG_MPV_RESTARTING = "Il lettore video è stato riavviato."

    MSG_USB_NO_DEVICE = "Nessun supporto USB trovato. Inserire la chiavetta e riprovare."
    MSG_USB_MOUNTED = "Supporto montato in {path}."
    MSG_USB_NO_VIDEOS = "Nessun nuovo filmato trovato sul supporto."
    MSG_USB_COPYING = "Copia [{index}/{total}] {name}: {percent}%"
    MSG_USB_SKIPPED = "{count} filmati già presenti: saltati."
    MSG_USB_UNMOUNTED = "Supporto {device} espulso in sicurezza. Puoi rimuoverlo."

    MSG_INGEST_NO_FILES = "Nessun filmato da acquisire in {path}."
    MSG_INGEST_FOUND = "Trovati {count} filmati da acquisire."
    MSG_INGEST_FILE_HEADER = "--- Filmato {index}/{total}: {name} ---"
    MSG_INGEST_PROBE_INFO = (
        "Durata: {duration} s | Risoluzione: {resolution} | "
        "Codec video: {codec} | Canali audio: {channels}"
    )
    MSG_INGEST_PROBE_FAILED = "ERRORE: Impossibile analizzare il file {name}. Saltato."
    MSG_INGEST_FFPROBE_MISSING = "ERRORE: ffprobe non è installato."
    MSG_INGEST_PREVIEW_FAILED = "ATTENZIONE: Anteprima non disponibile: {error}"
    MSG_INGEST_TITLE_PROMPT = "Titolo da visualizzare (max {max} caratteri): "
    MSG_INGEST_TITLE_EMPTY = "ERRORE: Il titolo non può essere vuoto."
    MSG_INGEST_TITLE_TOO_LONG = (
        "ERRORE: Il titolo è di {length} caratteri; il massimo consentito è {max}."
    )
    MSG_INGEST_DESC_PROMPT = "Descrizione (max {max} caratteri, invio per lasciare vuoto): "
    MSG_INGEST_DESC_TOO_LONG = (
        "ERRORE: La descrizione è di {length} caratteri; il massimo consentito è {max}."
    )
    MSG_INGEST_ARCHIVED = "Filmato archiviato: {title}"
    MSG_INGEST_SUMMARY = (
        "Acquisizione terminata: {done} filmati archiviati, {skipped} saltati."
    )
    MSG_FORCE_ACTIVE = "ATTENZIONE: Opzione --force attiva: controllo orario di visita ignorato."

    MSG_TUI_ALREADY_IN_PLAYLIST = "Il video è già presente nella scaletta."
    MSG_TUI_ADDED = "Video aggiunto alla scaletta: {title}"
    MSG_TUI_REMOVED = "Video rimosso dalla scaletta: {title}"
    MSG_TUI_DELETED = "Video spostato nel cestino: {title}"
    MSG_TUI_DELETE_FAILED = "ERRORE: Eliminazione non riuscita ({error})."
    MSG_TUI_REORDER_ON = "Spostamento attivo: usa ↑ / ↓, poi INVIO per confermare."
    MSG_TUI_REORDER_OFF = "Posizione confermata."
    MSG_TUI_EMPTY_ARCHIVE = "Archivio vuoto."
    MSG_TUI_EMPTY_PLAYLIST = "Scaletta vuota."

    UI_TUI_HEADER = "========================= GESTORE SCALETTA SVF-KIOSK ========================="
    UI_TUI_LEFT_TITLE = "Archivio Video (Disponibili)"
    UI_TUI_RIGHT_TITLE = "Scaletta Attiva (In Riproduzione)"
    UI_TUI_FOOTER = (
        "[TAB] Cambia Pannello | [↑/↓] Scorri | [INVIO] Azione | "
        "[C] Elimina | [D] Rimuovi | [P] Preset | [S] Salva | [Q] Esci"
    )
    UI_TUI_LABEL_ID = "ID"
    UI_TUI_LABEL_TITLE = "Titolo"
    UI_TUI_LABEL_DURATION = "Durata"
    UI_TUI_LABEL_PATH = "Percorso"
    UI_TUI_LABEL_DESCRIPTION = "Descrizione"

    MSG_DAEMON_FILE_MISSING = "ERRORE: File video non trovato: {title}"
    MSG_DAEMON_PRESET_EMPTY = "Nessun filmato associato al tasto {key}."
    MSG_DAEMON_NO_EVDEV = "ATTENZIONE: Telecomando non disponibile (modulo evdev mancante)."
    MSG_DAEMON_NO_REMOTE = "ATTENZIONE: Nessun telecomando trovato in /dev/input."
    MSG_DAEMON_MPV_START_FAILED = "ERRORE: Impossibile avviare il lettore video mpv."
    UI_MENU_HINT = "↑ / ↓ Scorri — OK Riproduci — ESC Chiudi"

    MSG_TUI_PRESET_PROMPT = "Premi un tasto da 1 a 9 per assegnarlo al video (0 = rimuovi, ESC = annulla)."
    MSG_TUI_PRESET_SET = "Tasto {key} assegnato a: {title}"
    MSG_TUI_PRESET_CLEARED = "Tasti rimossi dal video: {title}"
    MSG_TUI_PRESET_NONE = "Il video non ha tasti assegnati."
    MSG_TUI_PRESET_CANCELLED = "Assegnazione annullata."
    MSG_TUI_PRESET_INVALID = "Tasto non valido: usa un numero da 1 a 9."

    MSG_PRESETS_HEADER = "Tasti del telecomando:"
    MSG_PRESETS_LINE = "Tasto {key}: {title} (ID {id})."
    MSG_PRESETS_FREE = "Tasto {key}: libero."
    MSG_PRESETS_SET = "Preset {key} impostato su: {title}"
    MSG_PRESETS_CLEARED = "Tasto {key} liberato."
    MSG_PRESETS_NOT_SET = "Il tasto {key} non era assegnato."
    MSG_PRESETS_BAD_KEY = "ERRORE: Il tasto deve essere un numero da 1 a 9."
    MSG_PRESETS_NOT_FOUND = "ERRORE: Nessun video corrisponde a '{title}'."
    MSG_PRESETS_AMBIGUOUS = "ERRORE: Più video corrispondono a '{title}'. Indica il titolo completo oppure --id:"
    MSG_PRESETS_CANDIDATE = "ID {id}: {title}"

    MSG_STATUS_HEADER = "Stato di SVF-Kiosk:"
    MSG_STATUS_PLAYER_DOWN = "Lettore video: non raggiungibile."
    MSG_STATUS_PLAYER_IDLE = "Lettore video: attivo, nessun filmato in riproduzione."
    MSG_STATUS_PLAYER_FILE = "Filmato in corso: {path}"
    MSG_STATUS_PLAYER_TIME = "Tempo trascorso: {elapsed} su {duration}."
    MSG_STATUS_PLAYER_STATE = "Stato riproduzione: {state}."
    UI_STATUS_STATE_PLAYING = "in riproduzione"
    UI_STATUS_STATE_PAUSED = "in pausa"
    MSG_STATUS_CPU_TEMP = "Temperatura CPU: {temp} °C."
    MSG_STATUS_CPU_TEMP_UNKNOWN = "Temperatura CPU: non disponibile."
    MSG_STATUS_RAM = "Memoria RAM: {used} MB usati su {total} MB."
    MSG_STATUS_RAM_UNKNOWN = "Memoria RAM: non disponibile."
    MSG_STATUS_DISK = "Spazio libero in {path}: {free} GB su {total} GB."
    MSG_STATUS_DISK_UNKNOWN = "Spazio disco: non disponibile."
    MSG_STATUS_DISPLAY = "Schermo: {value}."
    MSG_STATUS_DISPLAY_UNKNOWN = "Schermo: non rilevabile (X11 non raggiungibile)."
    UI_STATUS_DISPLAY_NONE = "nessuna uscita collegata"
    MSG_STATUS_BT_CONNECTED = "Telecomando Bluetooth: connesso ({address})."
    MSG_STATUS_BT_BATTERY = "Batteria telecomando: {battery}%."
    MSG_STATUS_BT_BATTERY_UNKNOWN = "Batteria telecomando: non disponibile."
    MSG_STATUS_BT_DISCONNECTED = "Telecomando Bluetooth: non connesso."
    MSG_STATUS_BT_UNKNOWN = "Telecomando Bluetooth: stato non disponibile."

    MSG_RESTORE_NO_BACKUPS = "Nessuna copia di sicurezza disponibile."
    MSG_RESTORE_LIST_HEADER = "Copie di sicurezza disponibili (dalla più recente):"
    MSG_RESTORE_LIST_LINE = "{index}) {name} ({value})."
    MSG_RESTORE_CHOOSE = "Numero della copia da ripristinare (INVIO per annullare): "
    MSG_RESTORE_INVALID = "ERRORE: Scelta non valida."
    MSG_RESTORE_CANCELLED = "Ripristino annullato."
    MSG_RESTORE_CONFIRM = "Il database attuale verrà sostituito con '{name}'. Confermi? [s/N]: "
    MSG_RESTORE_CORRUPT = "ERRORE: La copia selezionata è danneggiata: {name}"
    MSG_RESTORE_SAFETY = "Copia di sicurezza dello stato attuale creata: {name}"
    MSG_RESTORE_DONE = "Ripristino completato con successo. Scaletta ricaricata."
    MSG_RESTORE_RELOAD_FAILED = "ATTENZIONE: Database ripristinato, ma il riavvio del servizio non è riuscito. Riavviare manualmente."
