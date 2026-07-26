import textwrap

from .abstract_text_animator import AbstractTextAnimator


class MultiLineGenerator(AbstractTextAnimator):
    """Splits text into display-width chunks and yields them one at a time.

    API:
        Start()    — (re)initialise from self.text
        Next()     — advance to the next line; returns True if one is available
        GetText()  — return the current line (idempotent between Next() calls)
        has_more() — True if at least one further line exists beyond the current one
                     (does NOT advance the iterator)

    Bug fixed vs original: the old GetText() did pop(0) while Next() only checked
    len > 0, so Next() after the last GetText() still returned True and the state
    machine attempted one extra iteration.  Now Next() is the only place that
    advances the iterator and GetText() is side-effect free.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: list[str] = []
        self._line_dp_flags: list[list[bool]] = []
        self._current: str = ""
        self._current_dp_flags: list[bool] = []

    def Start(self) -> None:
        # Wrapping self.text (already period/comma-folded by the time it
        # gets here -- see SingleLineAnimatedObserverBase.Value) is what
        # lets e.g. "192.168.1.112" (10 real cells after folding) fit on
        # one line instead of being split across two just because it was
        # 13 raw characters.
        self._lines = textwrap.wrap(
            self.text,
            width=self.max_text_width,
            expand_tabs=False,
            drop_whitespace=True,
        )
        self._line_dp_flags = self._map_dp_flags_to_lines(self._lines)
        self._current = ""
        self._current_dp_flags = []

    def _map_dp_flags_to_lines(self, lines: list[str]) -> list[list[bool]]:
        """Recovers each wrapped line's slice of self.dp_flags. textwrap
        only ever removes/collapses whitespace and never reorders or
        duplicates non-whitespace content, so a left-to-right find() of
        each line's own text reliably relocates it in the source string.
        Falls back to the current cursor (a non-crashing but potentially
        misaligned slice) on the rare input where find() can't -- doesn't
        occur for the plain metadata/status strings this app displays."""
        cursor = 0
        result: list[list[bool]] = []
        for line in lines:
            start = self.text.find(line, cursor)
            if start == -1:
                start = cursor
            result.append(self.dp_flags[start:start + len(line)])
            cursor = start + len(line)
        return result

    def Next(self) -> bool:
        """Advance to the next line. Returns True if a line is now available."""
        if not self._lines:
            return False
        self._current = self._lines.pop(0)
        self._current_dp_flags = self._line_dp_flags.pop(0)
        return True

    def GetText(self) -> str:
        """Return the line made current by the most recent Next() call."""
        return self._current

    def GetDpFlags(self) -> list[bool]:
        """Return the dp_flags for the line made current by the most
        recent Next() call."""
        return self._current_dp_flags

    def has_more(self) -> bool:
        """True if there are lines remaining beyond the current one."""
        return len(self._lines) > 0