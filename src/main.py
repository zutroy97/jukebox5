import drivers as ldisp
import asyncio
import logging
from animations import TextDiff, RandomTypeWriter, MultiLineGenerator, Slide, AnimationChain, AnimationChainLink
from observers import UpdateEventType, Coordinator,  SingleLineAnimatedObserverBase


                   
async def main():
    coorinator = Coordinator()

    # terminal_observer = TerminalObserver()
    # coorinator.add_observer(terminal_observer)

    led0 = ldisp.led16_display(addr=(0x70, 0x71))
    led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))

    led_artist_observer = SingleLineAnimatedObserverBase(driver=led0, event_type=UpdateEventType.ARTIST)
    coorinator.add_observer(led_artist_observer)
    led_song_title_observer = SingleLineAnimatedObserverBase(driver=led1, event_type=UpdateEventType.SONG_TITLE)
    led_song_title_observer.delay_between_characters_s = 0.01
    led_song_title_observer.changeAnimation((RandomTypeWriter()))
    coorinator.add_observer(led_song_title_observer)


    asyncio.create_task(coorinator.loop())
    coorinator.update_song_info(artist="Conway Twitty", song_title="Hello Darlin'")
    await asyncio.sleep(20)
    coorinator.update_song_info(artist="Kiss", song_title="I Was Made For Lovin' You")
    await asyncio.sleep(20)    
    coorinator.update_song_info(artist="Johnny Cash & June Carter", song_title="Jackson")
    await asyncio.sleep(20)
    coorinator.update_song_info(artist="John Williams", song_title="Jurassic Park Theme")
    await asyncio.sleep(20)
    coorinator.update_song_info(artist="Nirvana", song_title="Smells Like Teen Spirit")
    await asyncio.sleep(20)
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
