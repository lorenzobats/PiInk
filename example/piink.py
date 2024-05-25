#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
print(libdir)
if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from waveshare_epd import epd7in5_V2
import time
from PIL import Image,ImageDraw,ImageFont
import traceback
import http.server
import socketserver


logging.basicConfig(level=logging.DEBUG)
PORT = 8080


class Display:
    def __init__(self):
        epd = epd7in5_V2.EPD()
        print("init and Clear")
        # epd.init()
        # epd.Clear()

        self.font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
        self.font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
        self.epd = epd

display = Display()
display.epd.init()
display.epd.Clear()
Himage = Image.new('1', (display.epd.width, display.epd.height), 255)  # 255: clear the frame
draw = ImageDraw.Draw(Himage)
display.epd.init_part()
class CustomHTTPServer(socketserver.TCPServer):
    font24: ImageFont
    font18: ImageFont
    epd: epd7in5_V2.EPD
    state: Display

    def __init_(self, server_address, RequestHandlerClass, state):
        super().__init__(server_address, RequestHandlerClass)
        print(state)
        self.state = state

class SimpleHTTPRequestHandle(http.server.SimpleHTTPRequestHandler):

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        # print(self.server)
        # display = self.server.state
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        response = f"POST received {post_data.decode('utf-8')}"
        self.wfile.write(response.encode('utf-8'))
        draw.rectangle((10, 10, 200, 70), fill = 255)
        draw.text((10, 10), post_data.decode('utf-8'), font = display.font24, fill = 0)
        display.epd.display_Partial(display.epd.getbuffer(Himage), 0, 0, display.epd.width, display.epd.height)


with CustomHTTPServer(("", PORT), SimpleHTTPRequestHandle, Display()) as httpd:
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
