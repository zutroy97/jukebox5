import drivers as ldisp
import asyncio
import logging
from animations import RandomTypeWriter, Slide
from observers import UpdateEventType, Coordinator,  SingleTextLineAnimatedObserver,KeyValueTextObserver, SingleLineLed16AnimatedObserver
from animations.abstract_clear_animator import AbstractClearTextAnimator, ClearTextImmediatelyAnimator, ClearTextBlankLeftToRightAnimator

led0 = ldisp.led16_display(addr=(0x70, 0x71))
led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))
                   
async def main():
    coorinator = Coordinator()
    sleep_s : int = 25

    #led_artist_observer = SingleLineLed16AnimatedObserver(driver=led0.Seg14x4, event_type=UpdateEventType.ARTIST)
    led_artist_observer = SingleTextLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    led_artist_observer.delay_between_characters_s = 0.01
    led_artist_observer.delay_after_animation_finished_s = 2
    #coorinator.add_observer(led_artist_observer)
    
    led_song_title_observer = SingleTextLineAnimatedObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)    
    # led_song_title_observer = SingleLineLed16AnimatedObserver(driver=led1.Seg14x4, event_type=UpdateEventType.SONG_TITLE)
    led_song_title_observer.delay_between_characters_s = 0.01
    led_song_title_observer.delay_after_animation_finished_s = 2
    led_song_title_observer.changeAnimation(RandomTypeWriter())
    led_song_title_observer.ClearDisplayAnimation = ClearTextBlankLeftToRightAnimator()
    #coorinator.add_observer(led_song_title_observer)

    kv_observer = KeyValueTextObserver(key_driver = led_artist_observer, value_driver=led_song_title_observer)
    coorinator.add_observer(kv_observer)


    asyncio.create_task(coorinator.loop())
    coorinator.update_song_info(artist="Chumbawamba", song_title="Tubthumping (I Get Knocked Down)")
    await asyncio.sleep(sleep_s)    
    coorinator.update_song_info(artist="Conway Twitty", song_title="Hello Darlin'")
    await asyncio.sleep(sleep_s)
    coorinator.update_song_info(artist="Kiss", song_title="I Was Made For Lovin' You")
    await asyncio.sleep(sleep_s)

    # coorinator.remove_observer(led_artist_observer)
    # led_artist_observer = SingleTextLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    # coorinator.add_observer(led_artist_observer)

    coorinator.update_song_info(artist="Johnny Cash & June Carter", song_title="Jackson")
    await asyncio.sleep(sleep_s)
    coorinator.update_song_info(artist="John Williams", song_title="Jurassic Park Theme")
    await asyncio.sleep(sleep_s)
    coorinator.update_song_info(artist="Nirvana", song_title="Smells Like Teen Spirit")
    await asyncio.sleep(sleep_s)
    coorinator.update_song_info(artist="Weird Al Yankovic", song_title="Amish Paradise")
    await asyncio.sleep(sleep_s)
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

# if __name__ == "__main__":
#     import asyncio
#     from animations.text.random_typewriter import RandomTypeWriter
#     from animations.led_16.led16_static import LED16TextAnimatorAdapter

#     async def main():
#         animator = LED16TextAnimatorAdapter(RandomTypeWriter(text="Hello World!", max_text_width=8))
#         await animator.Start()
#         while await animator.Next():
#             #led0._display. set_segments(await animator.GetSegments())  # Update the LED display with the current segments
#             segments = await animator.GetSegments()
#             #print(segments)
#             for i, seg in enumerate(segments):
#                 print(f"Position {i}: {bin(seg)}")
#                 led0._display.set_digit_raw(i, seg)  # Update the LED display with the current segments
#             await asyncio.sleep(0.1)  # Add a small delay to control the animation speed
    
#     asyncio.run(main())    

# if __name__ == "__main__":
#     import asyncio
#     from animations.text.random_typewriter import RandomTypeWriter
#     from animations.led_16.led16_static import LED16Static

#     async def main():
#         animator = LED16Static(text="Hello World!", max_text_width=led1.Width)
#         await animator.Start()
#         while await animator.Next():
#             #led0._display. set_segments(await animator.GetSegments())  # Update the LED display with the current segments
#             segments = await animator.GetSegments()
#             #print(segments)
#             for i, seg in enumerate(segments):
#                 print(f"Position {i}: {bin(seg)}")
#                 led1._display.set_digit_raw(i, seg)  # Update the LED display with the current segments
#             await asyncio.sleep(0.1)  # Add a small delay to control the animation speed
    
#     asyncio.run(main())    