# from drivers.line import pd1200Driver
# from drivers.line import pd1200LineDisplay
# from drivers.line import led16_display
# from drivers.line import AbstractSingleLineDisplay

import drivers as ldisp
import asyncio
import logging
from animations.text import TextDiff, RandomTypeWriter, MultiLineGenerator, Slide, AnimationChain, AnimationChainLink


async def vfdAnimation1(ld : ldisp.AbstractSingleLineDisplay, text: str):
    anim = RandomTypeWriter(text=text, max_text_width=ld.Width)
    diff = TextDiff()
    await anim.Start()
    await ld.clear()
    while await anim.Next():
        text = await anim.GetText()
        chars = diff.getDiff(text)
        #print(chars)
        for pos, c in chars:
            print(f'pos={pos} c={c}')
            await ld.write_at_position(pos, c)
        #await ld.write(text)
        print(f'\r{text}', end='')
        
        await asyncio.sleep(0.1)

async def on_multiline_finished(anim: ldisp.AbstractSingleLineDisplay) -> bool:
    print("MultiLineGenerator finished!")
    await asyncio.sleep(1.0)
    return True 

async def on_slide_finished(anim: ldisp.AbstractSingleLineDisplay) -> bool:
    print("Slide finished!")
    await asyncio.sleep(2.0)
    return True

async def vfdAnimation2(ld : ldisp.AbstractSingleLineDisplay, text: str):
    anim = AnimationChain(
        max_text_width=ld.Width,
        links=[
            AnimationChainLink(MultiLineGenerator, onFinished=on_multiline_finished),
            AnimationChainLink(Slide, onFinished=on_slide_finished),
    ], text=text) 
    diff = TextDiff()
    await anim.Start()
    await ld.clear()
    while await anim.Next():
        text = await anim.GetText()
        chars = diff.getDiff(text)
        #print(chars)
        for pos, c in chars:
            print(f'pos={pos} c={c}')
            await ld.write_at_position(pos, c)
        #await ld.write(text)
        print(f'\r{text}', end='')
        
        await asyncio.sleep(0.1)



async def main2():
    driver = ldisp.pd1200Driver (port='/dev/serial0', baud=9600, width=20)
    await driver.clear_screen()
    await driver.normal_display_mode()
    await driver.set_brightness(5)
    
    display0 = ldisp.pd1200LineDisplay(driver, line=0)
    display1 = ldisp.pd1200LineDisplay(driver, line=1)

    led0 = ldisp.led16_display(addr=(0x70, 0x71))
    led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))


    await vfdAnimation2(ld = led0, text="Jurassic Park Theme")
    await vfdAnimation2(ld = led1, text="John Williams")
    
    await vfdAnimation2(ld = display0, text="Jurassic Park Theme")
    await vfdAnimation2(ld = display1, text="John Williams")   

    await asyncio.sleep(1) 

    await vfdAnimation2(ld = display0, text="Smells Like Teen Spirit")
    await vfdAnimation2(ld = display1, text="Nirvana")   



if __name__ == '__main__':
    formatter = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
        datefmt='%M:%S'
    )    
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    asyncio.run(main2())
