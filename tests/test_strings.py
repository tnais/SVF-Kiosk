"""Python implementation for test strings."""

import re

from src.core.strings import ItalianStrings

MOJIBAKE = ("Ã", "Â", "â€", "�")


def _messages():
    """Handle messages operations."""
    return {k: v for k, v in vars(ItalianStrings).items() if k.startswith("MSG_")}


def test_all_messages_are_non_empty_strings():
    """Verify all messages are non empty strings."""
    msgs = _messages()
    assert msgs
    assert all(isinstance(v, str) and v for v in msgs.values())


def test_no_mojibake():
    """Verify no mojibake."""
    for name, text in _messages().items():
        assert not any(m in text for m in MOJIBAKE), name


def test_placeholders_format():
    """Verify placeholders format."""
    for name, text in _messages().items():
        fields = re.findall(r"{(\w+)}", text)
        assert text.format(**{f: "x" for f in fields})  # no stray braces


def test_known_placeholders():
    """Verify known placeholders."""
    assert "Film" in ItalianStrings.MSG_OSD_TRIGGER.format(title="Film")
    assert "sdb1" in ItalianStrings.MSG_USB_DETECTED.format(device="sdb1")
    assert "3" in ItalianStrings.MSG_USB_COPY_SUCCESS.format(count=3)


def test_accents_are_proper_utf8():
    """Verify accents are proper utf8."""
    assert "À" in ItalianStrings.MSG_OSD_PREVIEW
    assert "è" in ItalianStrings.MSG_TUI_ERR_IN_PLAYLIST or "à" in ItalianStrings.MSG_TUI_CONFIRM_DEL_2


def test_authoritative_strings_match_spec():
    """Verify authoritative strings match spec."""
    s = ItalianStrings
    assert s.MSG_BOOT_START == "Avvio sistema SVF-Kiosk in corso..."
    assert s.MSG_BOOT_EMPTY == "Nessun video presente nella scaletta. Rivolgersi all'operatore."
    assert s.MSG_OSD_TRIGGER == "▶ Riproduzione richiesta: {title}"
    assert s.MSG_OSD_RESUME_NEXT == "Ripresa scaletta normale: riproduzione del prossimo filmato..."
    assert s.MSG_TUI_CONFIRM_DEL_1 == "Sei sicuro di voler eliminare '{title}'? [s/N]: "
    assert s.MSG_TUI_ERR_IN_PLAYLIST == "ERRORE: Impossibile eliminare! Il video è utilizzato nella scaletta."
    assert s.MSG_TUI_SAVED == "Scaletta salvata con successo nel database."
    assert s.MSG_TUI_UNSAVED_EXIT == "Ci sono modifiche non salvate. Vuoi uscire senza salvare? [s/N]: "
    assert s.MSG_VISIT_HOUR_WARNING == "ATTENZIONE: Operazione vietata durante l'orario di visita del museo."


def test_confirmation_prompts_end_with_default_hint():
    """Verify confirmation prompts end with default hint."""
    for name in ("MSG_TUI_CONFIRM_DEL_1", "MSG_TUI_CONFIRM_DEL_2",
                 "MSG_TUI_UNSAVED_EXIT", "MSG_PREVIEW_PROMPT"):
        assert getattr(ItalianStrings, name).endswith("[s/N]: ")


def test_source_file_is_valid_utf8():
    """Verify source file is valid utf8."""
    from pathlib import Path
    import src.core.strings as mod
    Path(mod.__file__).read_bytes().decode("utf-8")


ALLOWED_PLACEHOLDERS = {"key", "id", "title", "device", "count", "path", "name", "index", "total",
                        "percent", "duration", "resolution", "codec", "channels",
                        "length", "max", "done", "skipped", "error", "value", "used", "free",
                        "temp", "address", "battery", "elapsed", "state"}
ENGLISH_LEFTOVERS = re.compile(
    r"\b(the|error|failed|please|video not|loading|playing|saved|file not)\b", re.IGNORECASE)


def test_no_duplicate_message_texts():
    """Verify no duplicate message texts."""
    texts = list(_messages().values())
    assert len(texts) == len(set(texts))


def test_no_duplicate_constant_names():
    """Verify no duplicate constant names."""
    from pathlib import Path
    import src.core.strings as mod
    names = re.findall(r"^\s+(MSG_\w+)\s*=", Path(mod.__file__).read_text(encoding="utf-8"), re.M)
    assert len(names) == len(set(names))


def test_placeholder_names_are_allowed():
    """Verify placeholder names are allowed."""
    for name, text in _messages().items():
        assert set(re.findall(r"{(\w+)}", text)) <= ALLOWED_PLACEHOLDERS, name


def test_no_unformatted_braces():
    """Verify no unformatted braces."""
    for name, text in _messages().items():
        stripped = re.sub(r"{\w+}", "", text)
        assert "{" not in stripped and "}" not in stripped, name


def test_messages_look_italian_not_english():
    """Verify messages look italian not english."""
    for name, text in _messages().items():
        assert not ENGLISH_LEFTOVERS.search(re.sub(r"{\w+}", "", text)), name


def test_messages_have_no_stray_whitespace():
    """Verify messages have no stray whitespace."""
    for name, text in _messages().items():
        if text.endswith(": "):
            assert not text.endswith("  "), name
        else:
            assert text == text.strip(), name


PUNCTUATION_EXEMPT = {"MSG_OSD_PREVIEW", "MSG_INGEST_FILE_HEADER"}


def test_messages_end_with_punctuation_or_prompt():
    """Verify messages end with punctuation or prompt."""
    for name, text in _messages().items():
        if text.endswith(("}", "%")) or name in PUNCTUATION_EXEMPT:
            continue  # banners ending with a placeholder, or spec-fixed banners
        assert text.rstrip().endswith((".", "...", "!", ":", "]:", "?")) or text.endswith(": "), name


def test_ui_constants_are_clean_utf8():
    """Verify ui constants are clean utf8."""
    ui = {k: v for k, v in vars(ItalianStrings).items() if k.startswith("UI_")}
    assert ui
    for name, text in ui.items():
        assert isinstance(text, str) and text, name
        assert not any(m in text for m in MOJIBAKE), name
