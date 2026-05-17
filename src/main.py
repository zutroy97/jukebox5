import drivers as ldisp
import asyncio
import logging
from animations.text import TextDiff, RandomTypeWriter, MultiLineGenerator, Slide, AnimationChain, AnimationChainLink
from observers import UpdateEventType, ObserverBase, TerminalObserver, Coordinator, SingleLineObserver, SingleLineAnimatedObserver


async def on_multiline_finished(anim: ldisp.AbstractSingleLineDisplay) -> bool:
    #print("MultiLineGenerator finished!")
    await asyncio.sleep(1.0)
    return True 

async def on_slide_finished(anim: ldisp.AbstractSingleLineDisplay) -> bool:
    #print("Slide finished!")
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
            #print(f'pos={pos} c={c}')
            await ld.write_at_position(pos, c)
        #await ld.write(text)
        #print(f'\r{text}', end='')
        
        await asyncio.sleep(0.1)



async def main3():
    driver = ldisp.pd1200Driver (port='/dev/serial0', baud=9600, width=20)
    await driver.clear_screen()
    await driver.normal_display_mode()
    await driver.set_brightness(5)
    
    display0 = ldisp.pd1200LineDisplay(driver, line=0)
    display1 = ldisp.pd1200LineDisplay(driver, line=1)

    led0 = ldisp.led16_display(addr=(0x70, 0x71))
    led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))

    async with asyncio.TaskGroup() as tg:
        tg.create_task(
            vfdAnimation2(ld = led1, text="Jurassic Park Theme")
        )
        tg.create_task(
            vfdAnimation2(ld = led0, text="John Williams")
        )
        tg.create_task(
            vfdAnimation2(ld = display0, text="Jurassic Park Theme")
        )
        tg.create_task(
            vfdAnimation2(ld = display1, text="John Williams")
        )
    await asyncio.sleep(5)
    async with asyncio.TaskGroup() as tg:
        tg.create_task(
            vfdAnimation2(ld = led1, text="Smells Like Teen Spirit")
        )
        tg.create_task(
            vfdAnimation2(ld = led0, text="Nirvana")
        )
        tg.create_task(
            vfdAnimation2(ld = display0, text="Smells Like Teen Spirit")
        )
        tg.create_task(
            vfdAnimation2(ld = display1, text="Nirvana")
        )
                    
async def main():
    driver = ldisp.pd1200Driver (port='/dev/serial0', baud=9600, width=20)
    await driver.clear_screen()
    await driver.normal_display_mode()
    await driver.set_brightness(5)
    
    display0 = ldisp.pd1200LineDisplay(driver, line=0)
    display1 = ldisp.pd1200LineDisplay(driver, line=1)

    coorinator = Coordinator()
    # terminal_observer = TerminalObserver()
    # coorinator.add_observer(terminal_observer)

    single_line_observer0 = SingleLineAnimatedObserver(driver=display1, event_type=UpdateEventType.SONG_TITLE)
    single_line_observer1 = SingleLineAnimatedObserver(driver=display0, event_type=UpdateEventType.ARTIST)
    coorinator.add_observer(single_line_observer0)
    coorinator.add_observer(single_line_observer1)

    led0 = ldisp.led16_display(addr=(0x70, 0x71))
    led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))

    single_line_observer2 = SingleLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    coorinator.add_observer(single_line_observer2)
    single_line_observer3 = SingleLineAnimatedObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)
    coorinator.add_observer(single_line_observer3)

    asyncio.create_task(coorinator.loop())
    coorinator.update_song_info(artist="John Williams", song_title="Jurassic Park Theme")
    await asyncio.sleep(2)
    single_line_observer3.changeAnimation(Slide)
    await asyncio.sleep(5)
    coorinator.update_song_info(artist="Nirvana", song_title="Smells Like Teen Spirit")
    await asyncio.sleep(5)
    coorinator.shutdown()
    await asyncio.sleep(2)

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

    asyncio.run(main())
