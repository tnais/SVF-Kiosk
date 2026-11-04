# SVF Kiosk

SVF Kiosk is a multimedia kiosk application for a small (railway) museum. It manages an
archival video playlist, supports operator-guided video ingestion, and provides
continuous playback with on-demand video selection from a Bluetooth remote.
Operator-facing messages and tools are in Italian.

The production target is Debian GNU/Linux 12 (Bookworm), using a minimal X11
display session and `mpv`. See the [development and installation
guide](Docs/DEVELOPMENT_PLAN_AND_INSTALLATION.md) for complete development,
deployment, and commissioning instructions. The
[system specification](Docs/SpecificationV2.md) describes the intended
architecture and behavior.

## Requirements

- Python 3.11 or newer
- Linux for production playback, USB sync, and Bluetooth remote support
- `mpv` and X11 for kiosk playback

Python dependencies are declared in `pyproject.toml`.

## Development setup

From the repository root:

```bash
./scripts/setup-venv.sh
source .venv/bin/activate
```

Run the test suite with:

```bash
pytest tests/
```

Some playback and hardware integration checks require the production
environment; consult the installation guide for manual acceptance tests.

## Operator commands

Installing the project exposes these command-line tools:

| Command | Purpose |
| --- | --- |
| `svf-kiosk-daemon` | Run the kiosk playback daemon |
| `svf-playlist-editor` | Edit the active video playlist |
| `svf-ingest` | Ingest video files into the archive |
| `svf-usb-sync` | Copy video files from USB media |
| `svf-presets` | Configure remote-control presets |
| `svf-status` | Display kiosk and system status |
| `svf-restore` | Restore a database backup |

I manuali in italiano sono disponibili con `man <comando>` dopo
l'installazione di produzione.

Ingestion and USB synchronization are subject to visit-hour restrictions. For
safe operation and full production installation instructions, refer to the
guide linked above.
