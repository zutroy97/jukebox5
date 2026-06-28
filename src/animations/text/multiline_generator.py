import textwrap
import asyncio
import time

from .abstract_text_animator import AbstractTextAnimator

class MultiLineGenerator(AbstractTextAnimator):
    '''Animates text by splitting it into multiple lines and displaying each line one at a time.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines : list[str] = []

    def Start(self) -> None:
        self._lines = textwrap.wrap(self.text, width=self.max_text_width, expand_tabs=False, drop_whitespace=True)
        self._done = False

    def Next(self) -> bool:
        '''Returns true if more data is available'''
        return len(self._lines) > 0

    def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return self._lines.pop(0)

def main():
    anim = MultiLineGenerator(text="Hello there! My name is Slim Shady. This is a test of the multiline slide animation. It should display the text one line at a time."
        , max_text_width=20)
    cnt = 0
    while cnt < 10:
        anim.Start()
        while anim.Next():
            text = anim.GetText()
            # print(text)
            # print('-' * anim.max_text_width)
            time.sleep(0.250)
        cnt += 1

if __name__ == "__main__":
    main()  