import asyncio
import json

import pytest

from src.core.strings import ItalianStrings as S
from src.db.database import Database
from src.tui import playlist_editor
from src.tui.playlist_editor import (
    ANSI_PALETTE, LEFT, RIGHT, TRUECOLOR_PALETTE, EditorState, build_app, format_duration,
    select_palette,
)


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path)
    ids = {}
    for name in ("Delta", "Alfa", "Charlie", "Bravo"):
        f = tmp_path / f"{name}.mp4"
        f.write_bytes(b"x")
        ids[name] = db.add_video(str(f), name, f"Descrizione di {name}", 125, "1920x1080")
    return db, ids, tmp_path


def names(state):
    return [v["display_title"] for v in state.playlist_videos()]


def test_left_panel_sorted_alphabetically(env):
    db, _, _ = env
    assert [v["display_title"] for v in EditorState(db).videos] == [
        "Alfa", "Bravo", "Charlie", "Delta"]


def test_format_duration():
    assert format_duration(125) == "02:05"
    assert format_duration(None) == "00:00"
    assert format_duration(3600) == "60:00"


def test_navigation_is_clamped(env):
    st = EditorState(env[0])
    st.move(-1)
    assert st.left_idx == 0
    st.move(99)
    assert st.left_idx == 3
    st.move(1)
    assert st.left_idx == 3


def test_enter_on_left_appends_and_blocks_duplicates(env):
    st = EditorState(env[0])
    st.enter()
    assert names(st) == ["Alfa"] and st.dirty
    st.enter()
    assert names(st) == ["Alfa"]
    assert st.message == S.MSG_TUI_ALREADY_IN_PLAYLIST


def build_playlist(st, count=3):
    for _ in range(count):
        st.enter()
        st.move(1)


def test_tab_toggles_focus_but_not_while_reordering(env):
    st = EditorState(env[0])
    build_playlist(st)
    st.toggle_focus()
    assert st.focus == RIGHT
    st.enter()
    assert st.reorder
    st.toggle_focus()
    assert st.focus == RIGHT
    st.enter()
    st.toggle_focus()
    assert st.focus == LEFT


def test_reorder_moves_row_and_commit_keeps_it(env):
    st = EditorState(env[0])
    build_playlist(st)  # Alfa, Bravo, Charlie
    st.toggle_focus()
    st.enter()
    st.move(1)
    st.move(1)
    st.move(1)  # clamped at the end
    assert names(st) == ["Bravo", "Charlie", "Alfa"] and st.right_idx == 2
    st.enter()
    assert not st.reorder
    st.move(-1)
    assert names(st) == ["Bravo", "Charlie", "Alfa"] and st.right_idx == 1


def test_remove_from_playlist_only_in_right_panel(env):
    st = EditorState(env[0])
    build_playlist(st, 2)
    st.remove()  # focus is LEFT: ignored
    assert len(st.playlist_ids) == 2
    st.toggle_focus()
    st.move(1)
    st.remove()
    assert names(st) == ["Alfa"] and st.right_idx == 0


def test_remove_ignored_while_reordering(env):
    st = EditorState(env[0])
    build_playlist(st, 2)
    st.toggle_focus()
    st.enter()
    st.remove()
    assert len(st.playlist_ids) == 2


def test_delete_in_playlist_rings_bell_and_shows_error(env):
    st = EditorState(env[0])
    st.enter()
    st.move(-1)
    st.delete()
    assert st.bell and st.message == S.MSG_TUI_ERR_IN_PLAYLIST and st.pending is None


def test_delete_requires_double_confirmation(env):
    db, ids, root = env
    st = EditorState(db)
    st.delete()
    assert st.pending == "del1"
    assert st.message == S.MSG_TUI_CONFIRM_DEL_1.format(title="Alfa")
    st.answer(True)
    assert st.pending == "del2" and st.message == S.MSG_TUI_CONFIRM_DEL_2
    st.answer(True)
    assert [v["display_title"] for v in st.videos] == ["Bravo", "Charlie", "Delta"]
    assert not (root / "Alfa.mp4").exists()
    assert list((root / "trash").glob("*_Alfa.mp4"))
    assert st.message == S.MSG_TUI_DELETED.format(title="Alfa")


@pytest.mark.parametrize("first,second", [(False, None), (True, False)])
def test_delete_cancelled_keeps_file(env, first, second):
    db, _, root = env
    st = EditorState(db)
    st.delete()
    st.answer(first)
    if second is not None:
        st.answer(second)
    assert len(st.videos) == 4 and (root / "Alfa.mp4").exists()
    assert st.pending is None


def test_delete_blocked_when_db_playlist_still_has_video(env):
    db, ids, _ = env
    db.add_to_playlist(ids["Alfa"])
    st = EditorState(db)
    st.focus = RIGHT
    st.remove()                     # unsaved removal from the in-memory playlist
    st.toggle_focus()
    st.delete()
    st.answer(True)
    st.answer(True)                 # DB still references it: refused
    assert st.message == S.MSG_TUI_ERR_IN_PLAYLIST and st.bell
    assert len(st.videos) == 4


def test_save_writes_db_backups_and_mirror(env):
    db, ids, root = env
    st = EditorState(db)
    build_playlist(st, 2)
    st.save()
    assert [r["id"] for r in db.get_playlist()] == [ids["Alfa"], ids["Bravo"]]
    assert not st.dirty and st.message == S.MSG_TUI_SAVED
    backups = [p.name for p in db.list_backups()]
    assert any("pre_edit" in b for b in backups) and any("post_edit" in b for b in backups)
    mirror = json.loads((root / "data" / "playlist.json").read_text(encoding="utf-8"))
    assert mirror


def test_quit_clean_exits_immediately(env):
    st = EditorState(env[0])
    st.request_quit()
    assert st.should_exit


def test_quit_with_unsaved_changes_asks_confirmation(env):
    st = EditorState(env[0])
    st.enter()
    st.request_quit()
    assert not st.should_exit and st.message == S.MSG_TUI_UNSAVED_EXIT
    st.answer(False)
    assert not st.should_exit and st.pending is None
    st.request_quit()
    st.answer(True)
    assert st.should_exit


def test_keys_ignored_while_prompt_pending(env):
    st = EditorState(env[0])
    st.delete()
    st.move(1)
    st.toggle_focus()
    st.enter()
    st.save()
    assert st.left_idx == 0 and st.focus == LEFT and not st.playlist_ids


def test_render_styles(env):
    st = EditorState(env[0])
    st.enter()  # Alfa in playlist
    left = st.render_panel(LEFT)
    styles = {span.style for span in left.spans}
    assert any("blue" in str(s) or "cyan" in str(s) for s in styles)
    assert any("reverse" in str(s) for s in styles)
    st.toggle_focus()
    st.enter()
    right = st.render_panel(RIGHT)
    assert any("green" in str(s.style).lower() or "00AA00" in str(s.style) for s in right.spans)


def test_render_fits_80x24_and_has_no_overflowing_lines(env):
    st = EditorState(env[0])
    assert len(S.UI_TUI_HEADER) <= 80 and len(S.UI_TUI_FOOTER) <= 160  # footer wraps on 2 lines
    for which in (LEFT, RIGHT):
        for line in st.render_panel(which).plain.split("\n"):
            assert len(line) <= 40


def test_render_empty_panels(tmp_path):
    st = EditorState(Database(tmp_path))
    assert S.MSG_TUI_EMPTY_ARCHIVE in st.render_panel(LEFT).plain
    assert S.MSG_TUI_EMPTY_PLAYLIST in st.render_panel(RIGHT).plain
    assert st.render_inspector().plain == ""


def test_long_list_scrolls_with_cursor(tmp_path):
    db = Database(tmp_path)
    for i in range(30):
        db.add_video(str(tmp_path / f"{i}.mp4"), f"Video {i:02d}")
    st = EditorState(db)
    st.move(29)
    plain = st.render_panel(LEFT).plain
    assert "Video 29" in plain and "Video 00" not in plain
    assert len(plain.split("\n")) <= 13


def test_inspector_content(env):
    db, _, root = env
    st = EditorState(db)
    text = st.render_inspector().plain
    assert "Alfa" in text and "02:05" in text and str(root / "Alfa.mp4") in text
    assert "Descrizione di Alfa" in text


def test_inspector_truncates_and_wraps(tmp_path):
    db = Database(tmp_path)
    db.add_video(str(tmp_path / "a.mp4"), "T" * 38, "parola " * 30)
    text = EditorState(db).render_inspector().plain
    assert "T" * 38 in text
    assert len(text.split("\n")) >= 5  # wrapped description
    assert len(text.split("Descrizione: ")[1].replace("\n", "").replace(" ", "")) <= 150


def test_app_runs_at_80x24_with_keys(env):
    db, ids, _ = env

    async def scenario():
        app = build_app(db)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("enter", "down", "enter")
            await pilot.press("tab", "enter", "down", "enter")
            assert app.state.focus == RIGHT
            for widget_id in ("#header", "#left", "#right", "#inspector", "#status", "#footer"):
                region = app.query_one(widget_id).region
                assert region.bottom <= 24 and region.right <= 80, widget_id
            assert app.query_one("#footer").region.height == 2
            await pilot.press("s")
            assert app.state.message == S.MSG_TUI_SAVED
            await pilot.press("q")
        return app

    app = asyncio.run(scenario())
    assert [r["id"] for r in db.get_playlist()] == [ids["Bravo"], ids["Alfa"]]


# ------------------------------------------------------------------ gap closing

def test_palette_selection_by_terminal_capability():
    assert select_palette({"COLORTERM": "truecolor"}) is TRUECOLOR_PALETTE
    assert select_palette({"COLORTERM": "24bit"}) is TRUECOLOR_PALETTE
    assert select_palette({"TERM": "linux"}) is ANSI_PALETTE
    assert select_palette({}) is ANSI_PALETTE


@pytest.mark.parametrize("palette", [ANSI_PALETTE, TRUECOLOR_PALETTE])
def test_both_palettes_render_playlist_and_reorder_colors(env, palette):
    st = EditorState(env[0], palette)
    st.enter()
    assert any(palette["in_playlist"] in str(sp.style) for sp in st.render_panel(LEFT).spans)
    st.toggle_focus()
    st.enter()
    assert any(palette["reorder"] in str(sp.style) for sp in st.render_panel(RIGHT).spans)


def test_ansi_palette_uses_only_basic_named_colors():
    for style in ANSI_PALETTE.values():
        assert "#" not in style


def test_delete_missing_file_shows_error_and_keeps_video(env):
    db, _, root = env
    (root / "Alfa.mp4").unlink()
    st = EditorState(db)
    st.delete()
    st.answer(True)
    st.answer(True)
    assert st.message.startswith("ERRORE: Eliminazione non riuscita")
    assert len(st.videos) == 4
    assert [v["display_title"] for v in db.get_available_videos()][0] == "Alfa"


def test_delete_last_videos_leaves_usable_empty_archive(tmp_path):
    db = Database(tmp_path)
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    db.add_video(str(f), "Solo")
    st = EditorState(db)
    st.delete()
    st.answer(True)
    st.answer(True)
    assert st.videos == [] and st.left_idx == 0
    for action in (st.enter, st.delete, st.remove, lambda: st.move(1), st.save, st.request_quit):
        action()
    assert st.render_inspector().plain == ""


def test_empty_playlist_actions_are_noops(env):
    st = EditorState(env[0])
    st.toggle_focus()
    st.enter()
    assert not st.reorder
    st.remove()
    st.move(1)
    assert st.playlist_ids == [] and st.right_idx == 0


def test_reorder_with_single_item_is_stable(env):
    st = EditorState(env[0])
    st.enter()
    st.toggle_focus()
    st.enter()
    st.move(1)
    st.move(-1)
    assert names(st) == ["Alfa"] and st.right_idx == 0 and st.reorder


def test_save_while_reordering_persists_and_leaves_reorder(env):
    db, ids, _ = env
    st = EditorState(db)
    build_playlist(st, 2)
    st.toggle_focus()
    st.enter()
    st.move(1)
    st.save()
    assert not st.reorder and not st.dirty
    assert [r["id"] for r in db.get_playlist()] == [ids["Bravo"], ids["Alfa"]]


def test_save_without_changes_is_harmless(env):
    db, _, _ = env
    st = EditorState(db)
    st.save()
    assert st.message == S.MSG_TUI_SAVED and db.get_playlist() == []


def test_dirty_flag_lifecycle(env):
    st = EditorState(env[0])
    assert not st.dirty
    st.enter()
    assert st.dirty
    st.save()
    assert not st.dirty
    st.toggle_focus()
    st.enter()
    st.move(1)
    assert not st.dirty  # single item: no change made


def _run(db, keys, size=(80, 24)):
    async def scenario():
        app = build_app(db)
        async with app.run_test(size=size) as pilot:
            for key in keys:
                await pilot.press(key)
            return app, app.state.message, app.state.pending, app.state.should_exit

    return asyncio.run(scenario())


def test_app_delete_flow_with_keys(env):
    db, _, root = env
    _, msg, _, _ = _run(db, ["c", "s", "S"])
    assert msg == S.MSG_TUI_DELETED.format(title="Alfa")
    assert not (root / "Alfa.mp4").exists()


@pytest.mark.parametrize("answer", ["n", "enter", "escape", "x"])
def test_app_any_non_s_answer_cancels(env, answer):
    db, _, root = env
    _, _, pending, _ = _run(db, ["c", answer])
    assert pending is None and (root / "Alfa.mp4").exists()


def test_app_quit_with_unsaved_changes_requires_confirmation(env):
    _, _, pending, exited = _run(env[0], ["enter", "q"])
    assert pending == "quit" and not exited
    _, _, pending, exited = _run(env[0], ["enter", "q", "n"])
    assert pending is None and not exited
    _, _, _, exited = _run(env[0], ["enter", "q", "s"])
    assert exited


def test_app_rings_terminal_bell_on_protected_delete(env, monkeypatch):
    from textual.app import App

    rings = []
    monkeypatch.setattr(App, "bell", lambda self: rings.append(1))
    _run(env[0], ["enter", "up", "c"])
    assert rings == [1]


def test_app_fits_in_80x24_with_every_panel_full(tmp_path):
    db = Database(tmp_path)
    for i in range(30):
        db.add_video(str(tmp_path / f"{i}.mp4"), "T" * 38, "d" * 150)
    async def scenario():
        app = build_app(db)
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(15):
                await pilot.press("enter", "down")
            for widget_id in ("#header", "#left", "#right", "#inspector", "#status", "#footer"):
                region = app.query_one(widget_id).region
                assert region.bottom <= 24 and region.right <= 80, widget_id
    asyncio.run(scenario())


def test_main_builds_app_with_default_database(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    started = {}

    class FakeApp:
        def run(self):
            started["ran"] = True

    monkeypatch.setattr(playlist_editor, "build_app", lambda db: (started.setdefault("root", db.root), FakeApp())[1])
    assert playlist_editor.main() == 0
    assert started["ran"] and started["root"] == tmp_path


# ---- remote presets (P key) ---------------------------------------------
def press(state, *keys):
    for k in keys:
        if state.awaiting_preset:
            state.press_preset_key(k)
        elif k == "p":
            state.start_preset()


def test_preset_assign_marks_dirty_and_shows_message(env):
    db, ids, _ = env
    st = EditorState(db)  # cursor on Alfa
    press(st, "p")
    assert st.awaiting_preset and st.message == S.MSG_TUI_PRESET_PROMPT
    press(st, "3")
    assert st.presets == {3: ids["Alfa"]} and st.dirty and not st.awaiting_preset
    assert st.message == S.MSG_TUI_PRESET_SET.format(key="3", title="Alfa")


def test_preset_not_saved_until_s_and_saved_with_playlist(env):
    db, ids, _ = env
    st = EditorState(db)
    press(st, "p", "3")
    assert db.get_remote_presets() == {}
    st.save()
    assert db.get_remote_presets()[3]["id"] == ids["Alfa"]
    assert len(db.list_backups()) >= 2 and not st.dirty


def test_preset_loaded_from_database_on_start(env):
    db, ids, _ = env
    db.set_remote_preset(7, ids["Bravo"])
    assert EditorState(db).presets == {7: ids["Bravo"]}


def test_preset_reassigning_a_key_moves_it(env):
    db, ids, _ = env
    st = EditorState(db)
    press(st, "p", "2")
    st.move(1)
    press(st, "p", "2")
    assert st.presets == {2: ids["Bravo"]}


def test_one_video_can_hold_several_keys_and_badge_lists_them(env):
    db, ids, _ = env
    st = EditorState(db)
    press(st, "p", "5", "p", "1")
    assert st.keys_of(ids["Alfa"]) == [1, 5]
    assert "[1,5]" in st.render_panel(LEFT).plain.splitlines()[1]


def test_preset_zero_clears_all_keys_of_video(env):
    db, ids, _ = env
    st = EditorState(db)
    press(st, "p", "5", "p", "1")
    st.dirty = False
    press(st, "p", "0")
    assert st.presets == {} and st.dirty
    assert st.message == S.MSG_TUI_PRESET_CLEARED.format(title="Alfa")


def test_preset_zero_on_video_without_keys_is_a_noop(env):
    db, *_ = env
    st = EditorState(db)
    press(st, "p", "0")
    assert not st.dirty and st.message == S.MSG_TUI_PRESET_NONE


def test_preset_escape_cancels(env):
    db, *_ = env
    st = EditorState(db)
    press(st, "p", "escape")
    assert not st.awaiting_preset and not st.dirty and st.message == S.MSG_TUI_PRESET_CANCELLED


def test_preset_invalid_key_keeps_waiting(env):
    db, *_ = env
    st = EditorState(db)
    press(st, "p", "x")
    assert st.awaiting_preset and st.message == S.MSG_TUI_PRESET_INVALID
    press(st, "9")
    assert st.presets and not st.awaiting_preset


def test_preset_works_from_right_panel(env):
    db, ids, _ = env
    st = EditorState(db)
    st.enter()  # Alfa -> playlist
    st.toggle_focus()
    press(st, "p", "4")
    assert st.presets == {4: ids["Alfa"]}


def test_preset_ignored_while_reordering_or_confirming(env):
    db, *_ = env
    st = EditorState(db)
    st.enter()
    st.toggle_focus()
    st.enter()  # reorder on
    st.start_preset()
    assert not st.awaiting_preset
    st.enter()
    st.toggle_focus()
    st.delete()  # pending del? Alfa is in playlist -> bell, then try on Bravo
    st.move(1)
    st.delete()
    assert st.pending == "del1"
    st.start_preset()
    assert not st.awaiting_preset


def test_actions_are_blocked_while_waiting_for_a_preset_key(env):
    db, *_ = env
    st = EditorState(db)
    st.start_preset()
    before = (st.focus, st.left_idx, list(st.playlist_ids))
    st.toggle_focus()
    st.move(1)
    st.enter()
    st.delete()
    st.remove()
    st.request_quit()
    st.save()
    assert (st.focus, st.left_idx, st.playlist_ids) == before and not st.should_exit
    assert st.awaiting_preset


def test_deleting_a_video_drops_its_presets(env):
    db, ids, _ = env
    st = EditorState(db)
    press(st, "p", "6")
    st.save()
    st.delete()
    st.answer(True)
    st.answer(True)
    assert st.presets == {} and db.get_remote_presets() == {}
    st.save()  # must not fail on the vanished video


def test_badge_never_overflows_panel_width(env):
    db, *_ = env
    st = EditorState(db)
    press(st, *"p1p2p3p4p5p6p7p8p9")
    for line in st.render_panel(LEFT).plain.splitlines()[1:]:
        assert len(line) <= 40
    assert "[1,2,3,4,5,6,7,8,9]" in st.render_panel(LEFT).plain


def test_footer_mentions_preset_key_and_fits_two_lines():
    assert "[P] Preset" in S.UI_TUI_FOOTER and len(S.UI_TUI_FOOTER) <= 160


def test_app_p_then_digit_flow_and_save(env):
    db, ids, _ = env
    _, _, _, exited = _run(db, ["p", "2", "s", "q"])
    assert db.get_remote_presets()[2]["id"] == ids["Alfa"] and exited


def test_app_keys_after_p_do_not_trigger_other_actions(env):
    db, _, _ = env
    _, msg, _, exited = _run(db, ["p", "q"])
    assert not exited and msg == S.MSG_TUI_PRESET_INVALID


def test_save_does_not_erase_presets_set_by_cli_meanwhile(env):
    db, ids, _ = env
    st = EditorState(db)  # opened with no presets
    db.set_remote_preset(8, ids["Bravo"])  # CLI assigns while the editor is open
    press(st, "p", "3")
    st.save()
    assert {k: v["id"] for k, v in db.get_remote_presets().items()} == {3: ids["Alfa"], 8: ids["Bravo"]}
    assert st.presets == {3: ids["Alfa"], 8: ids["Bravo"]}


def test_save_still_applies_removals_made_in_editor(env):
    db, ids, _ = env
    db.set_remote_presets({1: ids["Alfa"], 2: ids["Bravo"]})
    st = EditorState(db)
    press(st, "p", "0")  # clears Alfa
    st.save()
    assert list(db.get_remote_presets()) == [2]


def test_editor_assignment_wins_over_concurrent_cli_on_same_key(env):
    db, ids, _ = env
    st = EditorState(db)
    db.set_remote_preset(3, ids["Bravo"])
    press(st, "p", "3")
    st.save()
    assert db.get_remote_presets()[3]["id"] == ids["Alfa"]
