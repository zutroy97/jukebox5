from .abstract_text_animator import AbstractTextAnimator
import asyncio

class Static(AbstractTextAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._read : bool = False
    
    async def Start(self) -> None:
        self._read = False

    async def Next(self) -> bool:
        if not self._read:
            self._read = True
            return True
        return False

    async def GetText(self) -> str:
        '''Returns the text to be displayed'''
        return self._text[:self.max_text_width]

async def main():    
    anim = Static(text="0123456789ABCDEF", max_text_width=10)
    await anim.Start()
    print('-' * anim.max_text_width)
    while await anim.Next():
        print(f'\r{await anim.GetText()}', end='')
        await asyncio.sleep(0.1)
    print()

if __name__ == "__main__":
    asyncio.run(main())    