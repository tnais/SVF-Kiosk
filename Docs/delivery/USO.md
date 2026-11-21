# Manuale d'uso SVF Kiosk

Guida per gli operatori del chiosco. I comandi vanno eseguiti come
`svf-operatore`, normalmente tramite SSH, e non richiedono privilegi
amministrativi. La sincronizzazione USB, l'importazione dei video e il
ripristino sono operazioni di manutenzione: eseguirle solo fuori dall'orario
di visita e quando non è in corso la riproduzione ambientale.

## Avvio normale

All'accensione il sistema avvia automaticamente X11 e il lettore a schermo
intero. Se la scaletta è vuota, il televisore mostra un messaggio che invita a
rivolgersi all'operatore. Non avviare manualmente il daemon durante il normale
esercizio: è gestito da `systemd`.

Il telecomando Bluetooth si comporta come una tastiera HID:

| Tasto | Funzione |
| --- | --- |
| `1`–`9` | Avvia il video associato al preset corrispondente. |
| `OK` / `Menu` | Mostra o nasconde il carosello informativo. |
| `ESC` / `Annulla` | Interrompe il video su richiesta. |

Al termine o all'interruzione di un video su richiesta, il lettore riprende la
scaletta dal video successivo, senza ricominciare quello interrotto.

## Consultare lo stato

Eseguire:

```bash
svf-status
```

Il rapporto diagnostico mostra lo stato del lettore e del video, memoria,
temperatura CPU, spazio disco, display X11 e connessione Bluetooth. Il comando
è di sola lettura e non accetta opzioni.

## Aggiungere video all'archivio

### Da una chiavetta USB

Fuori dall'orario di visita, collegare il supporto e, se necessario, individuare
la partizione con `lsblk`. Avviare la copia specificando la partizione:

```bash
svf-usb-sync --device /dev/sdb1
```

Sostituire `/dev/sdb1` con il dispositivo corretto. Senza `--device`, il
comando sceglie la prima partizione rilevata tra i dispositivi `/dev/sd*`.
Monta il supporto senza privilegi di root, copia nella directory d'ingresso i
nuovi file video trovati ricorsivamente e smonta il supporto al termine. I
duplicati già nell'archivio o nella directory d'ingresso vengono ignorati.

### Importare i video

I file da importare devono trovarsi in
`/var/lib/svf-kiosk/media/incoming/`. È possibile copiarli lì tramite SFTP
oppure usare `svf-usb-sync`. Poi eseguire:

```bash
svf-ingest
```

Per ogni video non ancora registrato, il comando legge i metadati, richiede
titolo e descrizione e sposta il file nell'archivio. Sono supportati MP4, MKV,
MOV e AVI; il titolo può contenere al massimo 38 caratteri e la descrizione
150. Se il lettore è attivo, l'operatore può scegliere di mostrare
un'anteprima sullo schermo principale.

## Modificare la scaletta

Avviare l'editor interattivo:

```bash
svf-playlist-editor
```

L'interfaccia presenta l'archivio dei video e la scaletta attiva. Le modifiche
non sono applicate al database fino al salvataggio.

| Tasto | Funzione |
| --- | --- |
| `Tab` | Passa tra archivio e scaletta, salvo durante riordino o conferme. |
| `↑` / `↓` | Sposta la selezione; in modalità riordino cambia la posizione nella scaletta. |
| `Invio` | Aggiunge alla scaletta un video dell'archivio; nella scaletta avvia o conclude il riordino. |
| `D` | Rimuove dalla scaletta il video selezionato. |
| `C` | Elimina dall'archivio dopo due conferme; un video in scaletta non può essere eliminato. |
| `P`, poi `1`–`9` | Associa al video selezionato il tasto numerico scelto. |
| `P`, poi `0` | Rimuove le associazioni del telecomando per il video selezionato. |
| `S` | Salva la scaletta e le associazioni, aggiorna la copia JSON. |
| `Q` | Esce; se ci sono modifiche non salvate, chiede conferma. |

Per riordinare un video, selezionarlo nel pannello della scaletta, premere
`Invio`, spostarlo con `↑`/`↓` e premere nuovamente `Invio` per terminare.
Salvare con `S` prima di uscire per mantenere le modifiche.

## Gestire i preset del telecomando

Per visualizzare i nove tasti e le relative associazioni:

```bash
svf-presets list
```

Per associare un video tramite titolo o identificativo:

```bash
svf-presets set 2 "Titolo del video"
svf-presets set 3 --id 12
```

Per cancellare l'associazione di un tasto:

```bash
svf-presets clear 2
```

I tasti ammessi sono da 1 a 9. La ricerca per titolo non distingue
maiuscole/minuscole: prova prima una corrispondenza esatta e poi una parziale.
Se la ricerca parziale trova più video, mostra i candidati senza modificare
l'associazione.

## Regole di sicurezza per la manutenzione

`svf-usb-sync`, `svf-ingest` e `svf-restore` rifiutano l'operazione durante
l'orario di visita o mentre è in corso la riproduzione ambientale. Non usare
`--force` durante le visite o mentre il chiosco è in uso: l'opzione aggira
entrambi i controlli e può interrompere l'esperienza dei visitatori.

L'opzione è riservata a una manutenzione eccezionale, concordata e svolta fuori
dal servizio:

```bash
svf-usb-sync --device /dev/sdb1 --force
svf-ingest --force
svf-restore --force
```

Prima di usare `--force`, verificare che lo schermo non sia necessario ai
visitatori e che il personale responsabile abbia autorizzato l'intervento.

## Ripristinare una copia di sicurezza

Fuori dall'orario di visita e quando la riproduzione ambientale è ferma,
eseguire:

```bash
svf-restore
```

Il comando elenca le copie disponibili dalla più recente alla più vecchia.
Selezionare quella desiderata e confermare con attenzione: prima del ripristino
viene salvata una copia di sicurezza del database attuale. Al termine vengono
aggiornati i dati esportati e riavviato il servizio del chiosco. L'operazione
può essere annullata prima della conferma.

## Servizi e problemi comuni

Lo stato dei servizi può essere controllato dall'account amministrativo:

```bash
systemctl status svf-x11
sudo -u svf-operatore \
  env XDG_RUNTIME_DIR=/run/user/$(id -u svf-operatore) \
  systemctl --user status svf-kiosk
```

Per consultare i log del lettore:

```bash
journalctl _UID=$(id -u svf-operatore) -u svf-kiosk
```

Il daemon `svf-kiosk-daemon` è destinato a `systemd`: non lanciarlo in una
seconda sessione mentre il servizio è attivo. Se il telecomando viene
riassociato o ricollegato dopo l'avvio del daemon e non risponde, riavviare il
servizio del chiosco fuori dall'orario di visita:

```bash
sudo -u svf-operatore \
  env XDG_RUNTIME_DIR=/run/user/$(id -u svf-operatore) \
  systemctl --user restart svf-kiosk
```

## Pagine man installate

L'installazione di produzione copia le pagine man in
`/usr/local/share/man/man1/`. Consultare il riferimento completo di un comando
con `man nome-comando`:

| Pagina man | Contenuto |
| --- | --- |
| `man svf-status` | Diagnostica del lettore, del sistema, del display e del telecomando. |
| `man svf-usb-sync` | Sintassi `--device` e `--force`, copia da USB e codici di uscita. |
| `man svf-ingest` | Importazione, formati, anteprima, `--force` e limiti dei metadati. |
| `man svf-playlist-editor` | Tasti dell'editor e salvataggio. |
| `man svf-presets` | Comandi `list`, `set`, `clear` e selezione tramite ID. |
| `man svf-restore` | Ripristino, conferma, `--force` e codici di uscita. |
| `man svf-kiosk-daemon` | Funzionamento del lettore e gestione del processo. |

Per l'installazione e gli aggiornamenti, consultare
[`INSTALLAZIONE.md`](INSTALLAZIONE.md).
