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
import json
from PIL import Image, ImageDraw, ImageFont
from enum import Enum
import asyncio
from aiohttp import web
import aiohttp
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

class Display(NamedTuple):
    epd: epd7in5_V2.EPD
    image: Image

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

    def draw(self, x: int, y: int, image: Image):
        self.image.paste(image, (x, y))

    def display(self):
        buffer = bytearray(self.image.tobytes())

        for i in range(0, len(buffer)):
            buffer[i] ^= 0xFF
            
        self.epd.display(buffer)

    def display_partial(self, x: int, y: int, width: int, height: int):
        bytes = self.image.tobytes()

        x0 = x // 8
        x1 = (x + width + 7) // 8
        y0 = y
        y1 = y + height
        scan_width = x1 - x0

        buffer = bytearray(scan_width * height)

        for i in range(0, height):
            for j in range(0, scan_width):
                image_pos = (y0 + i) * (self.epd.width // 8) + (x0 + j)
                buffer_pos = i * scan_width + j
                buffer[buffer_pos] = bytes[image_pos] ^ 0xFF

        self.epd.display_Partial(buffer, x, y0, x + width, y1)

    def clear(self):
        self.epd.Clear()
        return

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


def centered_text_h(content: str, ctx: ImageDraw, font, voffset: int = 0):
    '''Centers the given content relative to the ImageDraw ctx.
    Vertical Offset can be applied'''
    (width, height) = ctx.im.size
    rendered_len = ctx.textlength(content, font)
    pad = (width - rendered_len) / 2
    ctx.text((pad, voffset), content, font=font)


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
        ctx.rectangle((0, 0, width, height), fill=255, outline=0, width=2)
        ctx.text((0, 0), f"Hallo {self.name}!", font_size = 24, fill = 0)


@dataclass(slots=True)
class WeatherData:
    temperature: float = 0
    min: float = 0
    max: float = 0
    main: str = 'N/A'
    weather_icon: str = 'N/A'


@dataclass(slots=True)
class Weather:
    key: str
    city: str
    session: aiohttp.ClientSession
    weather_data: WeatherData

    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self.weather_data = WeatherData()
        try:
            with open('../openweathermap.json', 'r') as file:
                data = json.load(file)
                self.city = data['city']
                self.key = data['apiKey']
        except:
            print("openweathermap.json file not found.")

    def update(self, ctx: EventCtx, message: Message):
        match message.kind:
            case EventKind.ADDED:
                self.session = aiohttp.ClientSession()
                ctx.spawn_task(self.get_weather())
                pass
            case EventKind.TASK:
                data = message.data[1]
                if self.weather_data != data:
                    self.weather_data = data
                    print(f'Weather changed {self.weather_data}')
                    ctx.mark_changed()
                ctx.spawn_task(self.schedule_weather_update())
            case _:
                pass

    async def schedule_weather_update(self):
        await asyncio.sleep(10)
        return await self.get_weather()

    async def get_weather(self):
        endpoint = 'https://api.openweathermap.org/data/2.5/weather'
        async with self.session.get(f'{endpoint}?q={self.city}&appid={self.key}') as response:
            weather = await response.json()
            weather_data = WeatherData(
                        round(weather['main']['temp'] - 273.15, 1),
                        round(weather['main']['temp_min'] - 273.15, 1),
                        round(weather['main']['temp_max'] - 273.15, 1),
                        weather['weather'][0]['main'],
                        weather['weather'][0]['icon'])
            return weather_data

    def view(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill=255, outline=0, width=2)
        font = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 24)
        centered_text_h('Weather', ctx, font, voffset=0)
        ctx.text((5, 20), f'Temp: {self.weather_data.temperature}°C', font=font)
        ctx.text((5, 40), f"H: {self.weather_data.max}°C", font=font)
        ctx.text((5, 60), f"T: {self.weather_data.min}°C", font=font)
        ctx.text((5, 80), f"Desc: {self.weather_data.main}", font=font)


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
        font = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 24)
        ctx.text((0, 0), time.strftime('%H:%M // %A, %d.%m.%y'), font=font)

async def ui_handler(event_queue: asyncio.Queue):
    display = Display(epd=epd7in5_V2.EPD(), image=Image.new("1", (800, 480), 255))
    display.set_mode(DisplayMode.FULL)

    ctx = EventCtx(event_queue=event_queue, scheduled_tasks=dict())
    widgets: dict[int, (Any, (int, int, int, int))] = dict([
        (0, (Clock(), (0, 0, 800, 30))),
        (1, (Greeter(), (0, 160, 800, 320))),
        (2, (Weather(), (0, 30, 200, 200)))
    ])

    for (widget_id, (widget, (x, y, width, height))) in widgets.items():
        message = Message(kind=EventKind.ADDED, data=None)
        ctx.widget_id = widget_id
        widget.update(ctx, message)
        image = display.slice(x, y, width, height)

        widget.view(ImageDraw.Draw(image), (width, height))
        display.draw(x, y, image)

    display.display()

    display.set_mode(DisplayMode.PARTIAL)
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
        if value is None:
            continue

        (widget, (x, y, width, height)) = value
        message = Message(kind=event.kind, data=event.data)
        ctx.widget_id = event.target
        widget.update(ctx, message)

        if ctx.changed:
            image = display.slice(x, y, width, height)
            widget.view(ImageDraw.Draw(image), (width, height))
            display.draw(x, y, image)
            display.display_partial(x, y, width, height)

        ctx.widget_id = None
        ctx.changed = False


async def web_server(event_queue: asyncio):
    async def index(request):
        return web.Response(text='PiInk')

    async def hello(request: web.Request):
        name = await request.text()
        await event_queue.put(Event(kind=EventKind.UPDATE, target=1, data=name))
        await event_queue.put(Event(kind=EventKind.TASK, target=3, data=name))
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
