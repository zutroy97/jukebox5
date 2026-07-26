from .abstract_text_animator import AbstractTextAnimator


class Slide(AbstractTextAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._position : int = 0
        # How many characters GetText() revealed on its most recent call --
        # GetDpFlags() needs this to return the matching slice, since
        # GetText() advances self._position as a side effect before
        # GetDpFlags() (always called right after, same tick) gets to read it.
        self._last_reveal_upto : int = 0

    def Start(self) -> None:
        self._position = 1
        self._text = self._text[:self.max_text_width] # truncate text to max width if necessary
        self._dp_flags = self._dp_flags[:self.max_text_width]

    def Next(self) -> bool:
        '''Returns true if more data is available'''
        return self._position <= len(self.text)

    def GetText(self) -> str:
        '''Returns the text to be displayed'''
        self._last_reveal_upto = self._position
        result = self._text[:self._position].ljust(self._max_text_width)
        self._position += 1
        return result

    def GetDpFlags(self) -> list[bool]:
        '''Returns dp_flags aligned with the text GetText() just returned.'''
        visible = self._dp_flags[:self._last_reveal_upto]
        return visible + [False] * (self._max_text_width - len(visible))

