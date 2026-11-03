"""Two-panel console playlist editor (80x24 compatible)."""

from __future__ import annotations

import sys
import textwrap
from typing import Any

from rich.text import Text

from ..core.strings import ItalianStrings as S
from ..db.database import Database

PANEL_WIDTH = 40
PANEL_ROWS = 12
LEFT, RIGHT = "left", "right"

TRUECOLOR_PALETTE = {
    "normal": "#FFFFFF on #000000",
    "in_playlist": "#5FAFFF on #000000",
    "reorder": "bold #000000 on #00AA00",
}
# Plain 8/16-colour terminals (Linux console, VT100): dark blue is unreadable on black,
# so the "blue" family uses cyan.
ANSI_PALETTE = {
    "normal": "white on black",
    "in_playlist": "cyan on black",
    "reorder": "bold black on green",
}


def select_palette(env: dict[str, str] | None = None) -> dict[str, str]:
    import os

    env = os.environ if env is None else env
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return TRUECOLOR_PALETTE
    return ANSI_PALETTE


def format_duration(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class EditorState:
    """All editor logic, independent from the UI toolkit."""

    def __init__(self, db: Database, palette: dict[str, str] | None = None) -> None:
        self.db = db
        self.palette = palette or select_palette()
        self.videos: list[dict[str, Any]] = db.get_available_videos()
        self.by_id = {v["id"]: v for v in self.videos}
        self.playlist_ids: list[int] = [r["id"] for r in db.get_playlist()]
        self.focus = LEFT
        self.left_idx = 0
        self.right_idx = 0
        self.reorder = False
        self.dirty = False
        self.message = ""
        self.pending: str | None = None  # "del1" | "del2" | "quit"
        self.bell = False
        self.should_exit = False

    # ------------------------------------------------------------ accessors
    def playlist_videos(self) -> list[dict[str, Any]]:
        return [self.by_id[i] for i in self.playlist_ids]

    def current_video(self) -> dict[str, Any] | None:
        items = self.videos if self.focus == LEFT else self.playlist_videos()
        idx = self.left_idx if self.focus == LEFT else self.right_idx
        return items[idx] if 0 <= idx < len(items) else None

    def _clamp(self) -> None:
        self.left_idx = max(0, min(self.left_idx, len(self.videos) - 1))
        self.right_idx = max(0, min(self.right_idx, len(self.playlist_ids) - 1))

    # ------------------------------------------------------------ navigation
    def toggle_focus(self) -> None:
        if self.reorder or self.pending:
            return
        self.focus = RIGHT if self.focus == LEFT else LEFT

    def move(self, delta: int) -> None:
        if self.pending:
            return
        if self.focus == LEFT:
            self.left_idx = max(0, min(self.left_idx + delta, len(self.videos) - 1))
            return
        last = len(self.playlist_ids) - 1
        if self.reorder:
            target = self.right_idx + delta
            if 0 <= target <= last:
                ids = self.playlist_ids
                ids[self.right_idx], ids[target] = ids[target], ids[self.right_idx]
                self.right_idx = target
                self.dirty = True
        else:
            self.right_idx = max(0, min(self.right_idx + delta, last))

    # --------------------------------------------------------------- actions
    def enter(self) -> None:
        if self.pending:
            return
        video = self.current_video()
        if video is None:
            return
        if self.focus == LEFT:
            if video["id"] in self.playlist_ids:
                self.message = S.MSG_TUI_ALREADY_IN_PLAYLIST
                return
            self.playlist_ids.append(video["id"])
            self.dirty = True
            self.message = S.MSG_TUI_ADDED.format(title=video["display_title"])
        else:
            self.reorder = not self.reorder
            self.message = S.MSG_TUI_REORDER_ON if self.reorder else S.MSG_TUI_REORDER_OFF

    def remove(self) -> None:
        if self.pending or self.focus != RIGHT or self.reorder or not self.playlist_ids:
            return
        video = self.by_id[self.playlist_ids.pop(self.right_idx)]
        self.dirty = True
        self._clamp()
        self.message = S.MSG_TUI_REMOVED.format(title=video["display_title"])

    def delete(self) -> None:
        if self.pending or self.focus != LEFT:
            return
        video = self.current_video()
        if video is None:
            return
        if video["id"] in self.playlist_ids:
            self.bell = True
            self.message = S.MSG_TUI_ERR_IN_PLAYLIST
            return
        self.pending = "del1"
        self.message = S.MSG_TUI_CONFIRM_DEL_1.format(title=video["display_title"])

    def request_quit(self) -> None:
        if self.pending:
            return
        if self.dirty:
            self.pending = "quit"
            self.message = S.MSG_TUI_UNSAVED_EXIT
        else:
            self.should_exit = True

    def answer(self, yes: bool) -> None:
        """Answer the pending [s/N] question (anything but yes means no)."""
        pending, self.pending = self.pending, None
        if pending is None:
            return
        if not yes:
            self.message = ""
            return
        if pending == "quit":
            self.should_exit = True
        elif pending == "del1":
            self.pending = "del2"
            self.message = S.MSG_TUI_CONFIRM_DEL_2
        elif pending == "del2":
            self._do_delete()

    def _do_delete(self) -> None:
        video = self.current_video()
        if video is None:
            return
        try:
            self.db.soft_delete_video(video["id"], self.db.root / "trash")
        except ValueError:
            self.bell = True
            self.message = S.MSG_TUI_ERR_IN_PLAYLIST
            return
        except OSError as exc:
            self.message = S.MSG_TUI_DELETE_FAILED.format(error=exc.strerror or exc)
            return
        self.videos = [v for v in self.videos if v["id"] != video["id"]]
        self.by_id.pop(video["id"], None)
        self._clamp()
        self.message = S.MSG_TUI_DELETED.format(title=video["display_title"])

    def save(self) -> None:
        if self.pending:
            return
        self.db.create_backup("pre_edit")
        self.db.set_playlist(self.playlist_ids)
        self.db.create_backup("post_edit")
        self.db.rotate_backups()
        self.db.export_json_mirror()
        self.dirty = False
        self.reorder = False
        self.message = S.MSG_TUI_SAVED

    # ------------------------------------------------------------- rendering
    def render_panel(self, which: str) -> Text:
        videos = self.videos if which == LEFT else self.playlist_videos()
        cursor = self.left_idx if which == LEFT else self.right_idx
        active = self.focus == which
        title = S.UI_TUI_LEFT_TITLE if which == LEFT else S.UI_TUI_RIGHT_TITLE
        out = Text()
        out.append(title[:PANEL_WIDTH].ljust(PANEL_WIDTH), style="bold underline" if active else "bold")
        out.append("\n")
        if not videos:
            out.append(S.MSG_TUI_EMPTY_ARCHIVE if which == LEFT else S.MSG_TUI_EMPTY_PLAYLIST)
            return out
        top = max(0, min(cursor - PANEL_ROWS + 1, len(videos) - PANEL_ROWS))
        for i in range(top, min(top + PANEL_ROWS, len(videos))):
            video = videos[i]
            prefix = f"{i + 1:>2}. " if which == RIGHT else "   "
            line = (prefix + video["display_title"])[: PANEL_WIDTH - 1].ljust(PANEL_WIDTH - 1)
            style = self.palette["normal"]
            if which == LEFT and video["id"] in self.playlist_ids:
                style = self.palette["in_playlist"]
            if i == cursor and active:
                style = self.palette["reorder"] if (which == RIGHT and self.reorder) else "reverse " + style
            out.append(line, style=style)
            if i < min(top + PANEL_ROWS, len(videos)) - 1:
                out.append("\n")
        return out

    def render_inspector(self) -> Text:
        video = self.current_video()
        out = Text()
        if video is None:
            return out
        title = video["display_title"][:38]
        out.append(f"{S.UI_TUI_LABEL_ID}: {video['id']}   {S.UI_TUI_LABEL_TITLE}: {title}\n")
        out.append(
            f"{S.UI_TUI_LABEL_DURATION}: {format_duration(video['duration_seconds'])}\n"
        )
        out.append(f"{S.UI_TUI_LABEL_PATH}: {video['file_path']}"[:158] + "\n")
        description = (video.get("description") or "")[:150]
        wrapped = textwrap.wrap(description, 66) or [""]
        out.append(f"{S.UI_TUI_LABEL_DESCRIPTION}: {wrapped[0]}")
        for extra in wrapped[1:]:
            out.append("\n" + " " * 13 + extra)
        return out


def build_app(db: Database):
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    class PlaylistEditor(App):
        CSS = """
        Screen { background: #000000; color: #FFFFFF; layout: vertical; }
        #header { height: 1; }
        #panels { height: 13; }
        #left, #right { width: 40; height: 13; }
        #inspector { height: 6; border-top: ascii #FFFFFF; }
        #status { height: 1; }
        #footer { height: 2; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.state = EditorState(db)

        def compose(self) -> ComposeResult:
            from textual.containers import Horizontal

            yield Static(S.UI_TUI_HEADER, id="header")
            with Horizontal(id="panels"):
                yield Static(id="left")
                yield Static(id="right")
            yield Static(id="inspector")
            yield Static(id="status")
            yield Static(S.UI_TUI_FOOTER, id="footer")

        def on_mount(self) -> None:
            self.refresh_view()

        def refresh_view(self) -> None:
            st = self.state
            self.query_one("#left", Static).update(st.render_panel(LEFT))
            self.query_one("#right", Static).update(st.render_panel(RIGHT))
            self.query_one("#inspector", Static).update(st.render_inspector())
            self.query_one("#status", Static).update(Text(st.message))
            if st.bell:
                st.bell = False
                self.bell()  # terminal bell (\a) through the driver
            if st.should_exit:
                self.exit()

        def on_key(self, event) -> None:
            st = self.state
            key = event.key
            if st.pending:
                st.answer(key.lower() in ("s",))
            elif key == "tab":
                st.toggle_focus()
            elif key == "up":
                st.move(-1)
            elif key == "down":
                st.move(1)
            elif key == "enter":
                st.enter()
            elif key == "c":
                st.delete()
            elif key == "d":
                st.remove()
            elif key == "s":
                st.save()
            elif key == "q":
                st.request_quit()
            else:
                return
            event.stop()
            event.prevent_default()
            self.refresh_view()

    return PlaylistEditor()


def main() -> int:
    build_app(Database()).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
