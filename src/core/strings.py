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
