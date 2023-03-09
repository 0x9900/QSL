#!/usr/bin/env python
#
# BSD 3-Clause License
#
# Copyright (c) 2023, Fred W6BSD
# All rights reserved.
#

import adif_io
import logging
import os
import re
import smtplib
import sqlite3
import ssl
import string
import sys
import yaml

from argparse import ArgumentParser
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from tempfile import NamedTemporaryFile

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

import qrzlib

TEXT_COLOR = (0, 0, 77)
NEW_WIDTH = 1024

CONFIG_FILENAME = "qsl.yaml"
CONFIG_LOCATIONS = ['/etc', '~/.local', '.']

logging.basicConfig(level=logging.INFO)

def draw_rectangle(draw, coord, color=(0x28, 0x36, 0x18), width=1, fill=(0x75, 0xDB, 0xCD, 190)):
  draw.rectangle(coord, outline=color, fill=fill)
  draw.rectangle(coord, outline=color, width=width)


def send_mail(qso, image):
  server = "127.0.0.1"
  qso = type('QSO', (object,), qso)
  mail_template = config.mail_template + '\n' * 3
  template = string.Template(mail_template).safe_substitute

  if not qso.email:
    logging.error('No email provided for %s', qso.CALL)
    return

  msg = MIMEMultipart()
  msg['From'] = config.smtp_from
  msg['To'] = qso.email
  msg['Date'] = formatdate(localtime=True)
  msg['Subject'] = f"Digital QSL from {qso.OPERATOR} to {qso.CALL}"

  data = {}
  data['fname'] = qso.fname
  data['qso_date'] = datetime.fromtimestamp(qso.timestamp).strftime("%A %B %d, %Y at %X")
  data['freq_rx'] = qso.FREQ_RX
  data['mode'] = qso.MODE
  data['band'] = qso.BAND_RX
  data['rst_sent'] = qso.RST_SENT
  data['rst_rcvd'] = qso.RST_RCVD

  msg.attach(MIMEText(template(data)))

  with open(image, "rb") as fd:
    part = MIMEApplication(fd.read(), Name=os.path.basename(image))
    part['Content-Disposition'] = 'attachment; filename="%s"' % os.path.basename(image)
    msg.attach(part)

  smtp_password = open(os.path.expanduser('~/.smtp')).read()
  smtp_password = smtp_password.strip()

  #context = ssl.create_default_context()
  context = ssl._create_unverified_context()

  with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
    server.starttls(context=context)
    server.login(config.smtp_login, config.smtp_password)
    server.sendmail(config.smtp_from, qso.email, msg.as_string())


def card(qso, image_name=None):
  width = NEW_WIDTH
  qso = type('QSO', (object,), qso)

  img = Image.open(config.qsl_card)
  img = img.convert("RGBA")
  img.info['comment'] = 'QSL Card generated by 0x9900'

  if img.size[0] < NEW_WIDTH and img.size < 576:
    logging.error("The card resolution should be at least 1024x576")
    sys.exit(os.EX_CONFIG)

  big_font = ImageFont.truetype(config.font, 32)
  small_font = ImageFont.truetype(config.font, 16)
  xsmall_font = ImageFont.truetype(config.font2, 14)

  x_pos = 132
  h_size, v_size = img.size
  ratio = width / h_size
  vsize = int(v_size * ratio)
  img = img.resize((width, vsize), Image.Resampling.LANCZOS)

  overlay = Image.new('RGBA', img.size)#, (0,0,0,63))
  draw = ImageDraw.Draw(overlay)
  draw_rectangle(draw, ((112, vsize-220), (912, vsize-20)), width=3)

  textbox = ImageDraw.Draw(overlay)
  left = vsize - 215
  textbox.text((x_pos, left), f"From: {qso.OPERATOR}", font=big_font, fill=TEXT_COLOR)
  textbox.text((x_pos, left+38), f"  To: {qso.CALL}", font=big_font, fill=TEXT_COLOR)
  textbox.text((x_pos, left+85), (f'Mode: {qso.MODE} - Band: {qso.BAND} - '
                                  f'RST Send: {qso.RST_SENT} - RST Recieved: {qso.RST_RCVD}'
                                  ), font=small_font, fill=TEXT_COLOR)

  date = datetime.fromtimestamp(qso.timestamp).strftime("%A %B %d, %Y at %X")
  textbox.text((x_pos, left+110), f'Date: {date}', font=small_font, fill=TEXT_COLOR)
  textbox.text((x_pos, left+135),
               f' Rig: {qso.MY_RIG} - Grid: {qso.MY_GRIDSQUARE} - Power: {int(qso.TX_PWR)} Watt',
               font=small_font, fill=TEXT_COLOR)
  textbox.text((x_pos, left+165),
               'Thank you for the QSO, and I will look forward for our next contact, 73',
               font=xsmall_font, fill=TEXT_COLOR)

  textbox.text((NEW_WIDTH-90, vsize-30), '@0x9900', font=xsmall_font, fill=(0xff, 0xff, 0xff))

  img = Image.alpha_composite(img, overlay)
  img = img.convert("RGB")

  if not image_name:
    image_name = NamedTemporaryFile(prefix='QSL-', suffix='.jpg', delete=False).name
  img.save(image_name, "JPEG", quality=80, optimize=True, progressive=True)
  if config.show_cards:
    img.show()
  return image_name

def qso_timestamp(day, time='0000'):
  _dt = datetime.strptime(day + time[:-2], '%Y%m%d%H%M')
  return _dt.timestamp()

def read_config():
  for path in CONFIG_LOCATIONS:
    filename = os.path.expanduser(os.path.join(path, CONFIG_FILENAME))
    if os.path.exists(filename):
      logging.debug('Reading config file: %s', filename)
      try:
        with open(filename, 'r', encoding='utf-8') as cfd:
          config = yaml.safe_load(cfd)
          return type('Config', (object, ), config)
      except ValueError as err:
        logging.error('Configuration error "%s"', err)
        break
      except yaml.scanner.ScannerError as err:
        logging.error('Configuration file syntax error: %s', err)
        break

  logging.error('No configuration file found')
  sys.exit(os.EX_CONFIG)

def get_user(qrz, call):
  try:
    qrz.get_call(call)
  except qrzlib.QRZ.NotFound as err:
    logging.error(err)
    return None
  return qrz

def send_qsl(qso):
  assert 'email' in qso
  image_name = card(qso)
  send_mail(qso, image_name)
  logging.info('Mail sent to %s at %s', qso['CALL'], qso['email'])
  os.unlink(image_name)

def main():
  global config
  config = read_config()

  parser = ArgumentParser(description="Send e-QSL cards")
  parser.add_argument("-a", "--adif-file", required=True,
                      help='ADIF log file')
  parser.add_argument("-s", "--show", action="store_true", default=False,
                      help='Show the card')
  parser.add_argument("-k", "--keep", action="store_true", default=False,
                      help='keep the ADIF file after sending the cards [Default: %(default)s]')

  opts = parser.parse_args()

  adif_file = os.path.expanduser(opts.adif_file)
  if not os.path.exists(adif_file):
    logging.error('File "%s" not found', opts.adif_file)
    sys.exit(os.EX_IOERR)

  config.show_cards = True if opts.show else False
  qrz = qrzlib.QRZ()
  qrz.authenticate(config.call, config.qrz_key)

  qsos_raw, _ = adif_io.read_from_file(adif_file)
  for qso in qsos_raw:
    user_info = get_user(qrz, qso['CALL'])
    if not user_info.email:
      logging.warning('No email provided for %s', qso['CALL'])
      continue

    qso['email'] = user_info.email
    qso['country'] = user_info.country
    qso['name'] = user_info.name
    qso['fname'] = user_info.fname.title() if user_info.fname else 'Dear OM'

    if 'RST_SENT' not in qso:
      qso['RST_SENT'] = '59'
    if 'RST_RCVD' not in qso:
      qso['RST_RCVD'] = '59'

    qso_date = qso.get('QSO_DATE_OFF', qso['QSO_DATE'])
    qso_time = qso.get('TIME_OFF', qso.get('TIME_ON', '0000'))
    qso['timestamp'] = qso_timestamp(qso_date, qso_time)
    send_qsl(qso)

  if not opts.keep:
    logging.info('Removing %s', opts.adif_file)
    os.unlink(adif_file)

if __name__ == "__main__":
  main()
