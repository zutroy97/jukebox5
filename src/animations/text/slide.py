from .abstract_text_animator import AbstractTextAnimator
import asyncio

class Slide(AbstractTextAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._position : int = 0
    
    async def Start(self) -> None:
        self._position = 1
        self._text = self._text[:self.max_text_width] # truncate text to max width if necessary

    async def Next(self) -> bool:
        '''Returns true if more data is available'''
        return self._position <= len(self.text)

    async def GetText(self) -> str:
        '''Returns the text to be displayed'''
        result = self._text[:self._position].ljust(self._max_text_width)
        self._position += 1
        return result 

async def main():    
    anim = Slide(text="0123456789ABCDEF", max_text_width=10)
    await anim.Start()
    print('-' * anim.max_text_width)
    while await anim.Next():
        print(f'\r{await anim.GetText()}', end='')
        await asyncio.sleep(0.1)
    print()

if __name__ == "__main__":
    asyncio.run(main())    