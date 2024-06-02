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
from typing import Any, Coroutine, NamedTuple, Optional
from dataclasses import dataclass


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

@dataclass(slots=True)
class Display:
    epd: epd7in5_V2.EPD
    image: Image
    buffer: bytearray

    def __init__(self):
        self.epd = epd7in5_V2.EPD()
        self.image = Image.new("1", (self.epd.width, self.epd.height), 255)
        self.buffer = bytearray(len(self.image.tobytes()))

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

    def slice(self, x: int, y: int, width: int, height: int) -> Image:
        return self.image.crop((x, y, x + width, y + height))

    def draw(self, x: int, y: int, buffer: Image):
        self.image.paste(buffer, (x, y))

    def show(self):
        image_buffer = self.image.tobytes()

        for i in range(0, len(self.buffer)):
            self.buffer[i] = image_buffer[i] ^ 0xFF
            
        self.epd.display_Partial(self.buffer, 0, 0, self.epd.width, self.epd.height)

    def clear(self):
        self.epd.Clear()

class EventKind(Enum):
    ADDED = 0
    UPDATE = 1
    TASK = 2
    REMOVED = 3

class Event(NamedTuple):
    kind: EventKind
    target: Optional[int]
    data: Any

class Message(NamedTuple):
    kind: EventKind
    data: Any

@dataclass(slots=True)
class EventCtx:
    event_queue: asyncio.Queue
    scheduled_tasks: dict[(int, int), asyncio.Task[Any]]
    widget_id: Optional[int] = None
    task_id: int = 0
    changed: bool = False

    def mark_changed(self):
        self.changed = True

    def spawn_task(self, coroutine: Coroutine[None, None, Any]):
        async def dispatch_action(event_queue: asyncio.Queue, widget_id: int, task_id: int):
            result = await coroutine
            await event_queue.put(Event(kind=EventKind.TASK, target=widget_id, data=(task_id, result)))

        task_id = self.task_id
        task = asyncio.create_task(dispatch_action(self.event_queue, self.widget_id, task_id))
        self.scheduled_tasks[(self.widget_id, task_id)] = task
        self.task_id = task_id + 1


@dataclass(slots=True)
class Greeter:
    name: str = "Welt"

    def update(self, ctx: EventCtx, message: Message):
        match message.kind:
            case EventKind.UPDATE:
                if self.name != message.data:
                    self.name = message.data
                    ctx.mark_changed()
            case _:
                pass

    def view(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill = 255)
        ctx.text((0, 0), f"Hallo {self.name}!", font_size = 24, fill = 0)


@dataclass(slots=True)
class Clock:
    def update(self, ctx: EventCtx, message: Message):
        match message.kind:
            case EventKind.ADDED | EventKind.TASK:
                ctx.mark_changed()
                ctx.spawn_task(asyncio.sleep(60 - min(time.localtime().tm_sec, 60)))
            case _:
                pass

    def view(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill = 255)
        ctx.text((0, 0), time.strftime('%H:%M'), font_size = 24, fill = 0)

async def ui_handler(event_queue: asyncio.Queue):
    display = Display()
    display.set_mode(DisplayMode.FULL)
    display.clear()

    ctx = EventCtx(event_queue=event_queue, scheduled_tasks=dict())
    widgets: dict[int, (Any, (int, int, int, int))] = dict([
        (0, (Clock(), (0, 0, 800, 160))),
        (1, (Greeter(), (0, 160, 800, 320)))
    ])

    for (widget_id, (widget, (x, y, width, height))) in widgets.items():
        message = Message(kind=EventKind.ADDED, data=None)
        ctx.widget_id = widget_id
        widget.update(ctx, message)
        image = display.slice(x, y, width, height)
        widget.view(ImageDraw.Draw(image), (width, height))
        display.draw(x, y, image)

    display.set_mode(DisplayMode.PARTIAL)
    display.show()
    ctx.widget_id = None
    ctx.changed = False

    while True:
        event = await event_queue.get()

        match event.kind:
            case EventKind.ADDED:
                # TODO: Dynamically add widgets.
                pass
            case EventKind.REMOVED:
                # TODO: Widgets currently make no use of as data is stored in
                # memory. In the future it should be used to clean up
                # resources like files.
                pass
            case EventKind.TASK:
                del ctx.scheduled_tasks[(event.target, event.data[0])]
                
        value = widgets.get(event.target)

        if value == None:
            continue

        (widget, (x, y, width, height)) = value
        message = Message(kind=event.kind, data=event.data)
        ctx.widget_id = event.target
        widget.update(ctx, message)

        if ctx.changed:
            image = display.slice(x, y, width, height)
            widget.view(ImageDraw.Draw(image), (width, height))
            display.draw(x, y, image)
            display.show()

        ctx.widget_id = None
        ctx.changed = False


async def web_server(event_queue: asyncio):
    async def index(request):
        return web.Response(text='PiInk')

    async def hello(request: web.Request):
        name = await request.text()
        await event_queue.put(Event(kind=EventKind.UPDATE, target=1, data=name))
        return web.Response(text=f"Post received {name}")

    app = web.Application()
    app.add_routes([web.get("/", index), web.post("/", hello)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=None, port=PORT)
    await site.start()
    print(f"======== Running on {site.name} ========")

    # wait forever
    await asyncio.Event().wait()

async def main():
    event_queue = asyncio.Queue(maxsize=2)

    ui_task = asyncio.create_task(ui_handler(event_queue))
    server_task = asyncio.create_task(web_server(event_queue))

    await server_task
    await ui_task

asyncio.run(main())
