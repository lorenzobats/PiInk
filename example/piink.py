#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')

if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from waveshare_epd import epd7in5_V2
import time
from PIL import Image,ImageDraw,ImageFont
import traceback
import http.server
import socketserver
from enum import Enum
import asyncio
from aiohttp import web
from typing import NamedTuple, Any


logging.basicConfig(level=logging.DEBUG)
PORT = 8080

class DisplayMode(Enum):
    # Multiple Display Refreshes
    # The display needs to be fully refreshed at least once a day.
    FULL = 0
    # Single Display Refresh
    # Probably most useful if the whole screen needs to be invalidated anyway.
    FAST = 1
    # Partial Display Refresh
    # Refreshes a region on the display as is the case for updating the UI.        
    PARTIAL = 2

# FIXME: Remove once font dictionaries are stored in the UI state
ImageDraw.ImageDraw.font = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)

class Display:
    epd: epd7in5_V2.EPD
    image: Image

    def __init__(self):
        self.epd = epd7in5_V2.EPD()
        self.image = Image.new("1", (self.epd.width, self.epd.height), 255)
        self.font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
        self.font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)

    def set_mode(self, mode: DisplayMode):
        match mode:
            case DisplayMode.FULL:
                self.epd.init()
            case DisplayMode.FAST:
                self.epd.init_fast()
            case DisplayMode.PARTIAL:
                self.epd.init_part()
            case _:
                pass

    def draw(self):
        return ImageDraw.Draw(self.image)

    def display(self):
        self.epd.display(self.epd.getbuffer(self.image))

    def display_partial(self, x: int, y: int, width: int, height: int):
        self.epd.display_Partial(self.epd.getbuffer(self.image), x, y, width, height)

    def clear(self):
        self.epd.Clear()

class Message(NamedTuple):
    type: str
    data: Any

class EventCtx:
    def request_paint(self):
        pass

    def request_animation(self, delay_in_seconds: float):
        pass

class Greeter:
    name: str = ""

    def event(self, ctx: EventCtx, message: Message):
        match message.type:
            case "update":
                self.name = message.data               
                ctx.request_paint()
            case _:
                pass

    def paint(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill = 255)
        ctx.text((0, 0), f"Hallo {self.name}!", font_size = 24, fill = 0)


class Clock:
    def event(self, ctx, message):
        match message.type:
            case "animation":               
                ctx.request_paint()
                ctx.request_animation(1000)
            case _:
                pass

    def paint(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        draw.rectangle((0, 0, width, height), fill = 255)
        draw.text((0, 0), time.strftime('%H:%M'), font_size = 24, fill = 0)


async def ui_handler(event_queue: asyncio.Queue):
    display = Display()
    display.set_mode(DisplayMode.FULL)
    display.clear()
    display.set_mode(DisplayMode.PARTIAL)
    greeter = Greeter()

    while True:
        event = await event_queue.get()
        greeter.event(EventCtx(), Message(type="update", data=event))
        greeter.paint(display.draw(), (display.epd.width, display.epd.height))
        display.display_partial(0, 0, display.epd.width, display.epd.height)
        event_queue.task_done()

async def web_server(event_queue: asyncio):
    async def index(request):
        return web.Response(text='PiInk')

    async def hello(request: web.Request):
        name = await request.text()
        await event_queue.put(name)
        return web.Response(text=f"Post received {name}")

    app = web.Application()
    app.add_routes([web.get("/", index), web.post("/", hello)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=None, port=PORT)
    await site.start()
    print(f"======== Running on {site.name} ========")

    await event_queue.put("Welt")

    # wait forever
    await asyncio.Event().wait()

async def main():
    event_queue = asyncio.Queue(maxsize=2)

    server_task = asyncio.create_task(web_server(event_queue))
    ui_task = asyncio.create_task(ui_handler(event_queue))

    await server_task
    await ui_task

asyncio.run(main())

display = Display()
display.set_mode(DisplayMode.FULL)
display.clear()
display.set_mode(DisplayMode.PARTIAL)

class SimpleHTTPRequestHandle(http.server.SimpleHTTPRequestHandler):

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        response = f"POST received {post_data.decode('utf-8')}"
        self.wfile.write(response.encode('utf-8'))

        draw = display.draw()
        draw.rectangle((10, 10, 200, 70), fill = 255)
        draw.text((10, 10), post_data.decode('utf-8'), font = display.font24, fill = 0)
        display.display_partial(0, 0, display.epd.width, display.epd.height)


with socketserver.TCPServer(("", PORT), SimpleHTTPRequestHandle) as httpd:
    print(f"Serving on Port {PORT}")
    httpd.serve_forever()


# try:
#     logging.info("epd7in5_V2 Demo")
#     epd = epd7in5_V2.EPD()
#     logging.info("init and Clear")
#     epd.init()
#     epd.Clear()
#
#     font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
#     font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
#
#     logging.info("read bmp file")
#     Himage = Image.open(os.path.join(picdir, '7in5_V2.bmp'))
#     epd.display(epd.getbuffer(Himage))
#     time.sleep(2)
#
#     logging.info("read bmp file on window")
#     Himage2 = Image.new('1', (epd.width, epd.height), 255)  # 255: clear the frame
#     bmp = Image.open(os.path.join(picdir, '100x100.bmp'))
#     Himage2.paste(bmp, (50,10))
#     epd.display(epd.getbuffer(Himage2))
#     time.sleep(2)
#
#     # Drawing on the Horizontal image
#     logging.info("Drawing on the Horizontal image...")
#     epd.init_fast()
#     Himage = Image.new('1', (epd.width, epd.height), 255)  # 255: clear the frame
#     draw = ImageDraw.Draw(Himage)
#     draw.text((10, 0), 'hello Chi', font = font24, fill = 0)
#     draw.text((10, 20), '7.5inch e-Paper', font = font24, fill = 0)
#     draw.text((150, 0), u'微雪电子', font = font24, fill = 0)
#     draw.line((20, 50, 70, 100), fill = 0)
#     draw.line((70, 50, 20, 100), fill = 0)
#     draw.rectangle((20, 50, 70, 100), outline = 0)
#     draw.line((165, 50, 165, 100), fill = 0)
#     draw.line((140, 75, 190, 75), fill = 0)
#     draw.arc((140, 50, 190, 100), 0, 360, fill = 0)
#     draw.rectangle((80, 50, 130, 100), fill = 0)
#     draw.chord((200, 50, 250, 100), 0, 360, fill = 0)
#     epd.display(epd.getbuffer(Himage))
#     time.sleep(2)
#
#     # partial update
#     logging.info("5.show time")
#     epd.init_part()
#     # Himage = Image.new('1', (epd.width, epd.height), 0)
#     # draw = ImageDraw.Draw(Himage)
#     num = 0
#     while (True):
#         draw.rectangle((10, 120, 130, 170), fill = 255)
#         draw.text((10, 120), time.strftime('%H:%M:%S'), font = font24, fill = 0)
#         epd.display_Partial(epd.getbuffer(Himage),0, 0, epd.width, epd.height)
#         num = num + 1
#         if(num == 10):
#             break
#
#
#
#     # # Drawing on the Vertical image
#     # logging.info("2.Drawing on the Vertical image...")
#     # epd.init()
#     # Limage = Image.new('1', (epd.height, epd.width), 255)  # 255: clear the frame
#     # draw = ImageDraw.Draw(Limage)
#     # draw.text((2, 0), 'hello world', font = font18, fill = 0)
#     # draw.text((2, 20), '7.5inch epd', font = font18, fill = 0)
#     # draw.text((20, 50), u'微雪电子', font = font18, fill = 0)
#     # draw.line((10, 90, 60, 140), fill = 0)
#     # draw.line((60, 90, 10, 140), fill = 0)
#     # draw.rectangle((10, 90, 60, 140), outline = 0)
#     # draw.line((95, 90, 95, 140), fill = 0)
#     # draw.line((70, 115, 120, 115), fill = 0)
#     # draw.arc((70, 90, 120, 140), 0, 360, fill = 0)
#     # draw.rectangle((10, 150, 60, 200), fill = 0)
#     # draw.chord((70, 150, 120, 200), 0, 360, fill = 0)
#     # epd.display(epd.getbuffer(Limage))
#     # time.sleep(2)
#
#     
#
#     logging.info("Clear...")
#     epd.init()
#     epd.Clear()
#
#     logging.info("Goto Sleep...")
#     epd.sleep()
#     
# except IOError as e:
#     logging.info(e)
#     
# except KeyboardInterrupt:    
#     logging.info("ctrl + c:")
#     epd7in5_V2.epdconfig.module_exit(cleanup=True)
#     exit()
