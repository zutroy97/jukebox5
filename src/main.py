import drivers as ldisp
import asyncio
import logging
from animations import TextDiff, RandomTypeWriter, MultiLineGenerator, Slide, AnimationChain, AnimationChainLink
from observers import UpdateEventType, ObserverBase, TerminalObserver, Coordinator, SingleLineObserver, SingleLineAnimatedObserver, SingleLineAnimatedSimpleObserver

                   
async def main():
    coorinator = Coordinator()
    
    # driver = ldisp.pd1200Driver (port='/dev/serial0', baud=9600, width=20)
    # vdfDriver = ldisp.pd1200Driver (port='/dev/cu.Zooch3', baud=9600, width=20)
    # await vdfDriver.clear_screen()
    # await vdfDriver.normal_display_mode()
    # await vdfDriver.set_brightness(5)
    
    # vfdLine0 = ldisp.pd1200LineDisplay(vdfDriver, line=0)
    # vfdLine1 = ldisp.pd1200LineDisplay(vdfDriver, line=1)

    # vfd_song_title_observer = SingleLineAnimatedObserver(driver=vfdLine1, event_type=UpdateEventType.SONG_TITLE)
    # vfd_song_title_observer.changeAnimation(RandomTypeWriter)
    # coorinator.add_observer(vfd_song_title_observer)

    # vfd_artist_observer = SingleLineAnimatedObserver(driver=vfdLine0, event_type=UpdateEventType.ARTIST)
    # coorinator.add_observer(vfd_artist_observer)


    # terminal_observer = TerminalObserver()
    # coorinator.add_observer(terminal_observer)

    led0 = ldisp.led16_display(addr=(0x70, 0x71))
    led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))

    # led_artist_observer = SingleLineAnimatedSimpleObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    # coorinator.add_observer(led_artist_observer)
    led_song_title_observer = SingleLineAnimatedSimpleObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)
    coorinator.add_observer(led_song_title_observer)
    #led_song_title_observer.changeAnimation(RandomTypeWriter)

    asyncio.create_task(coorinator.loop())
    # coorinator.update_song_info(artist="John Williams", song_title="Jurassic Park Theme")
    # await asyncio.sleep(20)
    coorinator.update_song_info(artist="Nirvana", song_title="Smells Like Teen Spirit")
    await asyncio.sleep(1000)
    await coorinator.shutdown()
  

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
