#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import netifaces
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
from dataclasses import dataclass, field
import locale
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import random


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


def get_local_ip(interface_name='wlan0'):
    interfaces = netifaces.interfaces()
    if interface_name in interfaces:
        adr = netifaces.ifaddresses(interface_name)
        if netifaces.AF_INET in adr:
            ip_info = adr[netifaces.AF_INET][0]
            print(ip_info['addr'])
            return ip_info['addr']

LOCAL_IP = get_local_ip()

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
    target: Optional[str]
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
    scheduled_tasks: dict[(str, int), asyncio.Task[Any]]
    widget_id: Optional[str] = None
    task_id: int = 0
    changed: bool = False

    def mark_changed(self):
        self.changed = True

    def spawn_task(self, coroutine: Coroutine[None, None, Any]):
        async def dispatch_action(event_queue: asyncio.Queue, widget_id: str, task_id: int):
            result = await coroutine
            await event_queue.put(Event(kind=EventKind.TASK, target=widget_id, data=(task_id, result)))

        task_id = self.task_id
        task = asyncio.create_task(dispatch_action(self.event_queue, self.widget_id, task_id))
        self.scheduled_tasks[(self.widget_id, task_id)] = task
        self.task_id = task_id + 1


@dataclass(slots=True)
class WeatherSummary:
    temperature: float = 0.0
    low: float = 0.0
    high: float = 0.0
    icon: str = "clearsky_polartwilight"


@dataclass(slots=True)
class Weather:
    lattitude: float = 52.520008
    longitude: float = 13.404954
    icon_aliases = {
        # < == Excess s typo in API
        "lightssleetshowersandthunder_day": "lightsleetshowersandthunder_day",
        "lightssleetshowersandthunder_night": "lightsleetshowersandthunder_night",
        "lightssnowshowersandthunder_day": "lightsnowshowersandthunder_day",
        "lightssnowshowersandthunder_night": "lightsnowshowersandthunder_night",
        # == >
    }
    session: aiohttp.ClientSession = None
    summary: WeatherSummary = None
    time_series: dict[Any, Any] = None

    def update(self, ctx: EventCtx, message: Message):
        match message.kind:
            case EventKind.ADDED:
                self.session = aiohttp.ClientSession(
                    base_url="https://api.met.no",
                    headers={
                        "User-Agent": "PiInk/1.0 github.com/lorenzobats/PiInk",
                        "Accept": "application/json"
                    },
                )
                self.time_series = {}
                self.summary = WeatherSummary()
                ctx.spawn_task(self.get_weather())
            case EventKind.TASK:
                now = time.gmtime()
                today = f"{now.tm_year:04}-{now.tm_mon:02}-{now.tm_mday:02}"
                (expiration, data) = message.data[1]

                if data is not None:
                    midnight = f"{today}T00:00:00Z"
                    past_times = [key for key in self.time_series.keys() if key < midnight]

                    for key in past_times:
                        self.time_series.pop(key)

                    for step in data:
                        self.time_series[step["time"]] = step["data"]

                if len(self.time_series) == 0:
                    ctx.spawn_task(self.schedule_weather_update(expiration))
                    return


                key = f"{today}T{now.tm_hour:02}:{now.tm_min:02}:{now.tm_sec:02}Z"
                temperature = next(self.time_series.values().__iter__())["instant"]["details"]["air_temperature"]
                summary = WeatherSummary(temperature, temperature, temperature)

                for (t, d) in filter(lambda s: s[0].startswith(today), self.time_series.items()):
                    temperature = d["instant"]["details"]["air_temperature"]

                    if temperature < summary.low:
                        summary.low = temperature

                    if summary.high < temperature:
                        summary.high = temperature

                    if t <= key:
                        summary.temperature = temperature

                        if "next_1_hours" in d:
                            summary.icon = d["next_1_hours"]["summary"]["symbol_code"]
                        elif "next_6_hours" in d:
                            summary.icon = d["next_6_hours"]["summary"]["symbol_code"]
                        elif "next_12_hours" in d:
                            summary.icon = data["next_12_hours"]["summary"]["symbol_code"]

                if self.summary != summary:
                    self.summary = summary
                    print(f'Weather changed {self.summary}')
                    ctx.mark_changed()

                ctx.spawn_task(self.schedule_weather_update(now.tm_min, expiration))
            case _:
                pass

    async def schedule_weather_update(self, time_minute: int, seconds: float):
        seconds_until_full_hour = float((60 - time_minute) * 60)

        if seconds_until_full_hour < seconds:
            await asyncio.sleep(seconds_until_full_hour)
            return (seconds - seconds_until_full_hour, None)
            
        await asyncio.sleep(seconds)
        return await self.get_weather()

    async def get_weather(self):
        endpoint = "/weatherapi/locationforecast/2.0/compact"
        url = f"{endpoint}?lat={self.lattitude:.4f}&lon={self.longitude:.4f}"

        try:
            async with self.session.get(url) as response:
                self.session.headers["If-Modified-Since"] = response.headers["Last-Modified"]
                expires = response.headers["Expires"]
                expiration_datetime = parsedate_to_datetime(expires)
                expiration_in_seconds = (expiration_datetime - datetime.now(timezone.utc)).total_seconds()

                if response.status == 200:
                    try:
                        weather = await response.json()
                        time_series = weather["properties"]["timeseries"]
                        return (expiration_in_seconds, time_series)
                    except Exception as e:
                        print(e)

                return (expiration_in_seconds, None)
        except Exception as e:
            print(e)
            return (float(random.randrange(10 * 60, 30 * 60)), None)

    def resolve_weather_icon(self, icon: str):
        # Map polar twilight to day and night variant
        if icon != "clearsky_polartwilight" and icon.endswith("_polartwilight"):
            icon = icon.removesuffix("polartwilight")
            now = time.localtime()

            if 6 <= now.tm_hour and now.tm_hour <= 18:
                icon += "day"
            else:
                icon += "night"

        return self.icon_aliases.get(icon, icon)

    def view(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill=255, outline=0, width=3)
        font36 = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 36)
        font24 = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 24)
        ctx.text((130, 50), f'{round(self.summary.temperature)}°C', font=font36)
        # ctx.text((130, 90), f'{self.weather_data.desc}', font=font24)
        ctx.text((130, 120), f"H: {round(self.summary.high)}° // T: {round(self.summary.low)}°", font=font24)

        icon_name = self.resolve_weather_icon(self.summary.icon)
        weather_icon = Image.open(f"../weather_icons/{icon_name}.bmp")
        weather_icon.thumbnail((80, 80))
        ctx.bitmap((20, 80), weather_icon)


@dataclass(slots=True)
class Todo:
    todos: list[Any] = field(default_factory=list)

    def update(self, ctx: EventCtx, message: Message):
        match message.kind:
            case EventKind.ADDED | EventKind.TASK:
                ctx.mark_changed()
            case EventKind.UPDATE:
                if message.data['action'] == "ADD":
                    if len(self.todos) < 10:
                        self.todos.append(message.data['value'])
                if message.data['action'] == "DELETE":
                    try:
                        self.todos.pop(int(message.data['value']))
                    except:
                        pass
                ctx.mark_changed()
                pass

    def view(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill=255, outline=0, width=3)
        font36 = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 36)
        font28 = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 28)
        centered_text_h('Todos', ctx, font36)
        for idx, todo in enumerate(self.todos):
            todo = f'[{idx}] {todo}'
            text_length = ctx.textlength(todo, font28)
            ctx.text((30, 70 + idx * 32), todo, font=font28)



@dataclass(slots=True)
class Clock:

    def update(self, ctx: EventCtx, message: Message):
        match message.kind:
            case EventKind.ADDED:
                locale.setlocale(locale.LC_TIME, "")
                ctx.mark_changed()
                ctx.spawn_task(asyncio.sleep(60 - min(time.localtime().tm_sec, 60)))
            case EventKind.TASK:
                ctx.mark_changed()
                ctx.spawn_task(asyncio.sleep(60 - min(time.localtime().tm_sec, 60)))
            case _:
                pass

    def view(self, ctx: ImageDraw, size: (int, int)):
        (width, height) = size
        ctx.rectangle((0, 0, width, height), fill=255, outline=0, width=2)
        font36 = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 36)
        font24 = ImageFont.truetype('../fonts/FiraMono-Regular.ttf', 24)
        ctx.text((5, 5), f'{LOCAL_IP}', font=font24)
        centered_text_h(time.strftime('%H:%M'), ctx, font=font36, voffset=70)
        centered_text_h(time.strftime('%A, %x'), ctx, font=font24, voffset=110)

async def ui_handler(event_queue: asyncio.Queue):
    display = Display(epd=epd7in5_V2.EPD(), image=Image.new("1", (800, 480), 255))
    display.set_mode(DisplayMode.FULL)

    ctx = EventCtx(event_queue=event_queue, scheduled_tasks=dict())
    widgets: dict[str, (Any, (int, int, int, int))] = dict([
        ("clock",   (Clock(),   (0, 0, 400, 240))),
        ("weather", (Weather(), (0, 240, 400, 240))),
        ("todo",    (Todo(),    (400, 0, 400, 480))),
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
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(request):
        return web.Response(text='PiInk')

    @routes.get("/{controller}")
    async def get_control(request: web.Request):
        try:
            controller = request.match_info["controller"]
            path = f"../controller/{controller}.html"

            with open(path, mode="r", encoding="utf-8") as file:
                return web.Response(text=file.read(),
                                    content_type="text/html")
        except Exception:
            raise web.HTTPNotFound()

    @routes.post("/{controller}")
    async def post_control(request: web.Request):
        data = await request.post()
        controller = request.match_info["controller"]
        await event_queue.put(Event(kind=EventKind.UPDATE,
                                    target=controller,
                                    data={"action": data["action"], "value": data["value"]}))
        return web.HTTPFound(location=f"/{controller}")

    app = web.Application()
    app.add_routes(routes)
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
