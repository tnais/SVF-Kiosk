# Installazione SVF Kiosk

Guida per installare SVF Kiosk su un computer dedicato con Debian GNU/Linux 12
(Bookworm) minimale. La procedura automatica configura X11, l'utente operatore,
le dipendenze, il software e i servizi di avvio.

## Requisiti

- Computer dedicato con Debian 12, accesso a Internet e uscita HDMI collegata
  al televisore.
- Installazione Debian senza ambiente desktop, con le utilità di sistema
  standard e un server SSH.
- Un account amministrativo con `sudo` e accesso alla rete per scaricare il
  repository e i pacchetti.
- Per il telecomando: Bluetooth integrato o adattatore USB compatibile.

SVF Kiosk usa esclusivamente X11: non installare né configurare Wayland.

## Dipendenze necessarie

Prima di installare SVF Kiosk, assicurarsi che Debian disponga dei pacchetti
di sistema necessari per X11, la riproduzione video, il database, il
telecomando Bluetooth e la sincronizzazione USB:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  xorg xserver-xorg xinit x11-xserver-utils unclutter \
  mpv ffmpeg sqlite3 python3 python3-venv python3-pip \
  udisks2 bluez locales rsync git
```

Le dipendenze Python sono elencate in
[`requirements.txt`](../../requirements.txt):

| Pacchetto | Versione minima | Utilizzo |
| --- | ---: | --- |
| `textual` | 0.85.0 | Interfaccia testuale dell'editor della scaletta |
| `pydantic` | 2.10.0 | Validazione dei metadati e dello stato del kiosk |
| `python-mpv-jsonipc` | 1.1.1 | Comunicazione JSON-IPC con `mpv` |
| `evdev` | 1.7.0 | Lettura del telecomando Bluetooth su Linux |
| `pytest` | 8.3.0 | Esecuzione della suite di test |

Per una configurazione di sviluppo locale, creare un ambiente virtuale e
installare l'elenco completo:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Lo script `scripts/setup-kiosk.sh` installa automaticamente i pacchetti di
sistema e crea un ambiente Python dedicato in `/opt/svf-kiosk/venv` durante il
provisioning. In produzione, eseguire quindi lo script descritto nella sezione
successiva invece di installare manualmente l'applicazione nel sistema.

## Installazione

Accedere al computer con l'account amministrativo e installare Git:

```bash
sudo apt-get update
sudo apt-get install -y git
```

Clonare il repository ed eseguire il provisioning dalla directory del progetto:

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/tnais/SVF-Kiosk.git
cd SVF-Kiosk
sudo ./scripts/setup-kiosk.sh
```

Lo script richiede Debian 12 e privilegi di root. Installa i pacchetti di
sistema, configura il locale `it_IT.UTF-8`, crea l'utente `svf-operatore` e
installa applicazione e ambiente Python in `/opt/svf-kiosk`. I dati persistenti
sono conservati in `/var/lib/svf-kiosk`; il database viene inizializzato
durante la configurazione. Lo script è idempotente e può essere rieseguito per
applicare un aggiornamento.

Al termine, riavviare il computer:

```bash
sudo reboot
```

## Verifica dell'avvio

Dopo il riavvio, verificare che X11 e il lettore siano attivi:

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

Con una scaletta vuota sul televisore compare il messaggio che invita a
rivolgersi all'operatore. Dopo aver caricato e aggiunto i video alla scaletta,
il lettore li riproduce automaticamente a schermo intero.

## Configurazione del telecomando Bluetooth

Eseguire l'associazione da una sessione amministrativa:

```bash
sudo bluetoothctl
```

Al prompt di `bluetoothctl`, abilitare l'adattatore, avviare la scansione e
associare il telecomando (attivare la modalità di associazione sul dispositivo
quando richiesto):

```text
power on
agent on
default-agent
scan on
pair INDIRIZZO_BLUETOOTH
trust INDIRIZZO_BLUETOOTH
connect INDIRIZZO_BLUETOOTH
exit
```

Sostituire `INDIRIZZO_BLUETOOTH` con l'indirizzo rilevato durante la scansione.
Il telecomando deve presentarsi al sistema come tastiera Bluetooth HID. I tasti
da 1 a 9 attivano i preset configurati; `OK`/`Menu` apre o chiude il carosello
e `ESC`/`Annulla` interrompe il filmato richiesto.

## Primo caricamento dei video

Le operazioni di sincronizzazione USB e ingestione sono vietate durante
l'orario di visita. Fuori da tale orario:

1. Copiare i nuovi video nella directory di ingresso
   `/var/lib/svf-kiosk/media/incoming/` tramite SFTP oppure usare
   `svf-usb-sync` per copiarli da un supporto USB.
2. Eseguire `svf-ingest` per importare i video nell'archivio e registrare i
   relativi metadati.
3. Eseguire `svf-playlist-editor` per aggiungere i video alla scaletta e
   salvarla.
4. Eseguire `svf-presets` per associare, se desiderato, i video ai tasti del
   telecomando.

I comandi operatore sono installati in `/usr/local/bin`. Per le opzioni e le
conferme richieste da ciascun comando, consultare la relativa pagina man, ad
esempio `man svf-ingest` o `man svf-playlist-editor`.

## Accesso SSH dell'operatore

Il provisioning crea `svf-operatore` senza password interattiva. Per consentire
la manutenzione via SSH, installare una chiave pubblica autorizzata nella
directory `/home/svf-operatore/.ssh/authorized_keys`, assegnandola all'utente
operatore con permessi appropriati. Mantenere separato l'account amministrativo
usato per gli aggiornamenti di sistema.

## Aggiornamento dell'applicazione

Dalla copia del repository usata per l'installazione, scaricare la revisione
desiderata e rieseguire il provisioning:

```bash
cd ~/src/SVF-Kiosk
git pull --ff-only
sudo ./scripts/setup-kiosk.sh
```

Il provisioning aggiorna il codice in `/opt/svf-kiosk` e riavvia i servizi.
Non elimina i dati applicativi, che risiedono separatamente in
`/var/lib/svf-kiosk`.
