"""Checks that every installed command has an Italian manual page."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAN_DIR = ROOT / "man" / "man1"


def test_every_command_has_an_italian_man_page():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    commands = set(project["project"]["scripts"])
    pages = {path.stem for path in MAN_DIR.glob("*.1")}

    assert pages == commands
    for command in commands:
        text = (MAN_DIR / f"{command}.1").read_text(encoding="utf-8")
        assert text.startswith(f".TH {command.upper()} 1 ")
        assert ".SH NOME" in text
        assert ".SH DESCRIZIONE" in text
        assert any(word in text for word in ("Il ", "La ", "Mostra ", "Avvia "))
        assert not any(bad in text for bad in ("Ã", "â€", "Â"))


def test_setup_installs_man_pages():
    setup = (ROOT / "scripts" / "setup-kiosk.sh").read_text(encoding="utf-8")
    assert 'install -d /usr/local/share/man/man1' in setup
    assert 'install -m 644 "${INSTALL_DIR}"/man/man1/*.1 /usr/local/share/man/man1/' in setup
