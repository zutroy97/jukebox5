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
        self._current: str = ""

    def Start(self) -> None:
        self._lines = textwrap.wrap(
            self.text,
            width=self.max_text_width,
            expand_tabs=False,
            drop_whitespace=True,
        )
        self._current = ""

    def Next(self) -> bool:
        """Advance to the next line. Returns True if a line is now available."""
        if not self._lines:
            return False
        self._current = self._lines.pop(0)
        return True

    def GetText(self) -> str:
        """Return the line made current by the most recent Next() call."""
        return self._current

    def has_more(self) -> bool:
        """True if there are lines remaining beyond the current one."""
        return len(self._lines) > 0