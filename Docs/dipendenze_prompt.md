Tabella di Sintesi delle Dipendenze tra Prompt
Fase	Prompt	File Target	Dipendenze	Verifica (pytest)
0	Prompt 1	pyproject.toml, config/mpv.conf, src/core/strings.py	Nessuna	Build ambiente
1	Prompt 2	src/models/video.py	Prompt 1	tests/test_models.py
2	Prompt 3	src/db/database.py	Prompt 1, 2	tests/test_db.py
3	Prompt 4	src/core/mpv_client.py	Prompt 1	tests/test_mpv_client.py
4	Prompt 5	src/cli/usb_sync.py, src/cli/ingest.py	Prompt 2, 3, 4	tests/test_ingest.py
5	Prompt 6	src/tui/playlist_editor.py	Prompt 2, 3	Test interattivo TUI
6	Prompt 7	src/daemon/kiosk_player.py	Prompt 2, 3, 4	tests/test_daemon.py
7	Prompt 8	src/cli/status.py, src/cli/restore.py	Prompt 3, 4	CLI test
8	Prompt 9	systemd/svf-kiosk.service, scripts/setup-kiosk.sh	Tutti i precedenti	Test su Debian 12