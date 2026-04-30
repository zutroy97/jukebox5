from drivers.line.pd1200 import pd1200Driver, pd1200LineDisplay
from drivers.line.led_16seg import led16_display
import asyncio
import logging
from animations.text.random_typewriter import RandomTypeWriter
from animations.text import TextDiff
from drivers.line import AbstractSingleLineDisplay

async def main():
    driver = pd1200Driver(port='/dev/serial0', baud=9600, width=20)
    await driver.clear_screen()
    await driver.normal_display_mode()
    await driver.set_brightness(5)
    display0 = pd1200LineDisplay(driver, line=0)
    display1 = pd1200LineDisplay(driver, line=1)

    led0 = led16_display(addr=(0x70, 0x71))
    led1 = led16_display(addr=(0x72, 0x73, 0x74))
    await led0.clear()
    await led0.write('Williams')
    await led1.write('Star Wars Theme')
    
    await display0.write('John Williams ')
    await display1.write('Jurassic Park Theme')

    await asyncio.sleep(2)
    await display0.clear()
    await led0.clear()
    await led1.clear()
    await led0.write('Good') 
    await led1.write('Morning.')

    # await asyncio.sleep(1)
    # await led0.set_position(4)
    # await led0.write('X')

    # await display0.write('morning')

    # await display1.write('Line 1 More and more')
 
    # await asyncio.sleep(1)

    # await display0.set_position(5)
    # await display0.write('X Zooch')

async def vfdAnimation1(ld : AbstractSingleLineDisplay, text: str):
    anim = RandomTypeWriter(text=text, max_text_width=20)
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
    driver = pd1200Driver(port='/dev/serial0', baud=9600, width=20)
    await driver.clear_screen()
    await driver.normal_display_mode()
    await driver.set_brightness(5)
    
    display0 = pd1200LineDisplay(driver, line=0)
    display1 = pd1200LineDisplay(driver, line=1)

    await vfdAnimation1(ld = display0, text="Jurassic Park Theme")
    await vfdAnimation1(ld = display1, text="John Williams")
    

    led0 = led16_display(addr=(0x70, 0x71))
    led1 = led16_display(addr=(0x72, 0x73, 0x74))

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
