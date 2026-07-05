from .abstract_text_animator import AbstractTextAnimator


class Static(AbstractTextAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._read : bool = False
    
    def Start(self) -> None:
        self._read = False

    def Next(self) -> bool:
        if not self._read:
            self._read = True
            return True
        return False

    def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return self._text[:self.max_text_width]
