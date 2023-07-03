#!/usr/bin/env python
#
# BSD 3-Clause License
#
# Copyright (c) 2023, Fred W6BSD
# All rights reserved.
#
# pylint: disable=no-member,invalid-name,too-many-branches
#

import dbm.gnu as dbm
import logging
import marshal
import os
import re
import smtplib
import ssl
import string
import sys

from argparse import ArgumentParser, FileType
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from shutil import move
from tempfile import NamedTemporaryFile

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

import adif_io
import qrzlib
import yaml

__version__ = "0.1.19"

# US special call sign station don't like to receive e-cards
RE_US_SPECIAL = re.compile('[KNW]\d\w')

NEW_WIDTH = 1024

CONFIG_FILENAME = "eqsl.yaml"
CONFIG_LOCATIONS = ['.', '~/.local', '/etc']

FONTS = {
  'font_call': 'Ubuntu Mono derivative Powerline Bold.ttf',
  'font_text': 'DroidSansMono.ttf',
  'font_foot': 'VeraMono-Italic.ttf',
}

config = None

logging.basicConfig(level=logging.INFO)

def draw_rectangle(draw, coord, color=(0x44, 0x79, 0x9), width=1, fill=(0x75, 0xDB, 0xCD, 190)):
  draw.rectangle(coord, outline=color, fill=fill)
  draw.rectangle(coord, outline=color, width=width)


def send_mail(qso, image):
  server = "127.0.0.1"
  qso = type('QSO', (object,), qso)
  mail_template = config.mail_template + '\n' * 3
  template = string.Template(mail_template).safe_substitute

  if not qso.EMAIL:
    logging.error('No email provided for %s', qso.CALL)
    return

  msg = MIMEMultipart()
  msg['From'] = config.smtp_from
  msg['To'] = qso.EMAIL
  msg['Date'] = formatdate(localtime=True)
  msg['Subject'] = f"Digital QSL from {qso.OPERATOR} to {qso.CALL}"

  data = {}
  data['call'] = qso.CALL
  data['name'] = qso.NAME
  data['qso_date'] = datetime.fromtimestamp(qso.timestamp).strftime("%A %B %d, %Y at %X UTC")
  data['freq_rx'] = qso.FREQ_RX
  data['mode'] = qso.MODE
  data['band'] = qso.BAND_RX
  data['rst_sent'] = qso.RST_SENT
  data['rst_rcvd'] = qso.RST_RCVD
  data['rig'] = qso.MY_RIG
  data['gridsquare'] = qso.MY_GRIDSQUARE

  msg.attach(MIMEText(template(data)))

  with open(image, "rb") as fdi:
    part = MIMEApplication(fdi.read(), Name=os.path.basename(image))
    part['Content-Disposition'] = 'attachment; filename="%s"' % os.path.basename(image)
    msg.attach(part)

  with open(os.path.expanduser('~/.smtp'), encoding='utf-8') as fdp:
    smtp_password = fdp.read()
    smtp_password = smtp_password.strip()

  #context = ssl.create_default_context()
  context = ssl._create_unverified_context()

  try:
    with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
      server.starttls(context=context)
      server.login(config.smtp_login, config.smtp_password)
      server.sendmail(config.smtp_from, qso.EMAIL, msg.as_string())
  except ConnectionRefusedError as err:
    logging.error('SMTP "%s" connection error %s', config.smtp_server, err)
    sys.exit(1)

def card(qso, signature, image_name=None):
  width = NEW_WIDTH
  qso = type('QSO', (object,), qso)

  img = Image.open(config.qsl_card)
  img = img.convert("RGBA")
  img.info['comment'] = 'QSL Card generated by http://github.com/0x9900/QSL/'

  if img.size[0] < NEW_WIDTH and img.size < 576:
    logging.error("The card resolution should be at least 1024x576")
    sys.exit(10)

  font_call = ImageFont.truetype(config.font_call, 24)
  font_text = ImageFont.truetype(config.font_text, 16)
  font_foot = ImageFont.truetype(config.font_foot, 14)

  h_size, v_size = img.size
  ratio = width / h_size
  vsize = int(v_size * ratio)
  img = img.resize((width, vsize), Image.Resampling.LANCZOS)

  overlay = Image.new('RGBA', img.size)
  draw = ImageDraw.Draw(overlay)
  draw_rectangle(draw, ((112, vsize-220), (912, vsize-20)), width=3, fill=config.overlay_color)

  textbox = ImageDraw.Draw(overlay)
  date = datetime.fromtimestamp(qso.timestamp).strftime("%A %B %d, %Y at %X UTC")
  y_pos = vsize - 205
  x_pos = 132
  textbox.text((x_pos+10, y_pos), f"To: {qso.CALL}  From: {qso.OPERATOR}",
               font=font_call, fill=config.text_color)
  textbox.text((x_pos, y_pos+40), (f'Mode: {qso.MODE} • Band: {qso.BAND} • '
                                   f'RST Send: {qso.RST_SENT} • RST Recieved: {qso.RST_RCVD}'
                                  ), font=font_text, fill=config.text_color)
  textbox.text((x_pos, y_pos+65), f'Date: {date}', font=font_text, fill=config.text_color)
  textbox.text((x_pos, y_pos+90), f' Rig: {qso.MY_RIG} • Power: {int(qso.TX_PWR):d} Watt',
               font=font_text, fill=config.text_color)
  textbox.text((x_pos, y_pos+115), (f'Grid: {qso.MY_GRIDSQUARE} • CQ Zone: {config.ituzone} • '
                                    f'ITU Zone: {config.cqzone}'),
               font=font_text, fill=config.text_color)

  textbox.text((x_pos, y_pos+155), signature, font=font_foot, fill=config.text_color)

  textbox.text((NEW_WIDTH-90, vsize-30), '@0x9900', font=font_foot, fill=(0x70, 0x70, 0xa0))

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


def _read_config():
  for path in CONFIG_LOCATIONS:
    filename = os.path.expanduser(os.path.join(path, CONFIG_FILENAME))
    if os.path.exists(filename):
      logging.debug('Reading config file: %s', filename)
      try:
        with open(filename, 'r', encoding='utf-8') as cfd:
          return yaml.safe_load(cfd)
      except ValueError as err:
        logging.error('Configuration error "%s"', err)
        break
      except yaml.scanner.ScannerError as err:
        logging.error('Configuration file syntax error: %s', err)
        break

  logging.error('No configuration file found.')
  logging.error(' >> Go to https://github.com/0x9900/QSL/ for a configuration example')
  sys.exit(10)


def read_config():
  _config = _read_config()
  for font_name in ("font_call", "font_text", "font_foot"):
    font_path = _config.get(font_name, '')
    if not os.path.isfile(font_path):
      logging.warning('Font "%s" not found, using the default font', font_path)
      font_path = os.path.join(os.path.dirname(__file__), 'fonts', FONTS[font_name])
      _config[font_name] = font_path

  for color_name in ('overlay_color', 'text_color'):
    _config[color_name] = tuple(_config[color_name])

  card_path = _config.get('qsl_card', '')
  if not os.path.isfile(card_path):
    logging.warning('QSL Card "%s" not found, using the default QSL Card', card_path)
    card_path = os.path.join(os.path.dirname(__file__), 'card', 'default.jpg')
    _config['qsl_card'] = card_path

  return type('Config', (object, ), _config)


def move_adif(adif_file):
  src = adif_file.name
  dest, _ = os.path.splitext(src)
  dest = dest + '.old'
  if adif_file.name == dest:
    logging.warning('The file "%s" cannot be moved', adif_file.name)
  else:
    logging.info('Moving "%s" to "%s"', os.path.basename(adif_file.name), os.path.basename(dest))
    move(src, dest)


def already_sent(qso):
  key = (qso['CALL'] + '-' + qso['BAND']).upper()
  try:
    if os.path.exists(config.qsl_cache):
      with dbm.open(config.qsl_cache, 'r') as qdb:
        if key in qdb:
          return True

    with dbm.open(config.qsl_cache, 'c') as qdb:
      qdb[key] = marshal.dumps(qso)
  except (dbm.error, IOError) as err:
    logging.warning(err)
  return False

class QRZInfo:
  def __init__(self):
    self._qrz = None

  def _connect(self):
    try:
      self._qrz = qrzlib.QRZ()
      self._qrz.authenticate(config.call, config.qrz_key)
    except OSError as err:
      logging.error(err)
      return os.EX_IOERR

  def get_user(self, qso):
    if not self._qrz:
      self._connect()
    try:
      self._qrz.get_call(qso['CALL'])
    except qrzlib.QRZ.NotFound:
      logging.error("%s not found on qrz.com", qso['CALL'])
      return False

    if not getattr(self._qrz, 'email') or not self._qrz.email:
      logging.error("No email provided for %s on qrz.com", qso['CALL'])
      return False

    qso['EMAIL'] = self._qrz.email
    qso['NAME'] = self._qrz.fname.title()
    qso['NAME'] = qso['NAME'].strip()

    return True

def main():
  global config
  config = read_config()

  parser = ArgumentParser(description="Send e-QSL cards")
  parser.add_argument("-a", "--adif-file", default=config.adif_file,
                      type=FileType('r'), help='ADIF log file [default: %(default)s]')
  parser.add_argument("-k", "--keep", action="store_true", default=False,
                      help=('keep the ADIF and the images after sending the cards '
                            '[Default: %(default)s]'))
  parser.add_argument("-n", "--no-email", action="store_true", default=False,
                      help='Do not send the mail, just generate the card only')
  parser.add_argument("-s", "--show", action="store_true", default=False,
                      help='Show the card')
  parser.add_argument("-u", "--uniq", action="store_false", default=True,
                      help="Never send a second QSL")
  parser.add_argument("--version", action="version", version=f'%(prog)s {__version__}')

  opts = parser.parse_args()

  config.show_cards = bool(opts.show)
  qrz = QRZInfo()

  try:
    qsos_raw, _ = adif_io.read_from_string(opts.adif_file.read())
  except IndexError:
    logging.error('Error reading the ADIF file "%s"', opts.adif_file.name)
    return os.EX_IOERR

  for qso in qsos_raw:
    if RE_US_SPECIAL.fullmatch(qso['CALL']):
      logging.warning('Skip special event station (%s)', qso['CALL'])
      continue

    if opts.uniq and already_sent(qso):
      logging.warning('QSL already sent to %s', qso['CALL'])
      continue

    if 'EMAIL' not in qso or not qso['EMAIL']:
      if not qrz.get_user(qso):
        continue

    if 'RST_SENT' not in qso:
      qso['RST_SENT'] = '59'
    if 'RST_RCVD' not in qso:
      qso['RST_RCVD'] = '59'

    if not qso['NAME']:
      qso['NAME'] = 'Dear OM'
    else:
      qso['NAME'] = qso['NAME'].split()[0]

    qso_date = qso.get('QSO_DATE_OFF', qso['QSO_DATE'])
    qso_time = qso.get('TIME_OFF', qso.get('TIME_ON', '0000'))
    qso['timestamp'] = qso_timestamp(qso_date, qso_time)

    image_name = card(qso, config.signature)
    if not opts.no_email:
      try:
        send_mail(qso, image_name)
      except smtplib.SMTPRecipientsRefused:
        logging.warning('Error Recipient "%s" malformed', qso['EMAIL'])
      else:
        logging.info('Mail sent to %s at %s', qso['CALL'], qso['EMAIL'])
    if not opts.keep:
      os.unlink(image_name)

  opts.adif_file.close()
  if not opts.keep:
    move_adif(opts.adif_file)

  return os.EX_OK


if __name__ == "__main__":
  main()
