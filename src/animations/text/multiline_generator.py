import textwrap
from base import TextAnimatorBase
import asyncio

class MultiLineGenerator(TextAnimatorBase):
    '''Animates text by splitting it into multiple lines and displaying each line one at a time.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    async def Start(self) -> None:
        self._lines = textwrap.wrap(self.text, width=self.max_text_width, expand_tabs=False, drop_whitespace=True)
        self._done = False
        await asyncio.sleep(0) # yield control to the event loop

    async def Next(self) -> bool:
        '''Returns true if more data is available'''
        await asyncio.sleep(0) # yield control to the event loop
        return len(self._lines) > 0

    async def GetText(self) -> str:
        '''Returns the text to be displayed'''
        await asyncio.sleep(0) # yield control to the event loop
        return self._lines.pop(0)

async def main():
    anim = MultiLineGenerator(text="Hello there! My name is Slim Shady. This is a test of the multiline slide animation. It should display the text one line at a time."
        , max_text_width=20)
    cnt = 0
    while cnt < 10:
        await anim.Start()
        while await anim.Next():
            text = await anim.GetText()
            print(text)
            print('-' * anim.max_text_width)
            await asyncio.sleep(0.250)
        cnt += 1

if __name__ == "__main__":
    asyncio.run(main())   