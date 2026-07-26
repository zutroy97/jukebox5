from abc import abstractmethod

from ..abstract_animator import AbstractAnimator

class AbstractTextAnimator(AbstractAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    @abstractmethod
    def Start(self) -> None:
        '''Initializes the animation using the existing text. Must be called before any other methods.'''
        pass

    def StartWithText(self, new_text: str, dp_flags: list[bool] | None = None) -> None:
        '''Initializes the animation using the new_text (and its parallel
        dp_flags, if given -- see AbstractAnimator.dp_flags). Both are
        truncated to max_text_width together so they stay aligned.'''
        if dp_flags is None:
            dp_flags = [False] * len(new_text)
        self._text = new_text[:self.max_text_width] # truncate text to max width if necessary
        self._dp_flags = dp_flags[:self.max_text_width]
        self.Start()

    @abstractmethod
    def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return ""

    def GetDpFlags(self) -> list[bool]:
        '''Returns dp_flags aligned with GetText()'s current return value.
        Default: no decimal-point tracking (all False) -- overridden by
        animators that actually thread fold_periods()'s output through
        their own text manipulation (currently Slide and
        MultiLineGenerator; the only two used by the live app).'''
        return [False] * len(self.GetText())


    


        