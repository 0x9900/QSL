#!/usr/bin/env python
#
# BSD 3-Clause License
#
# Copyright (c) 2023-2024, Fred W6BSD
# All rights reserved.
#
# pylint: disable=no-member,invalid-name,too-many-branches,consider-using-with
#

import dbm
import logging
import os
import pickle
import smtplib
import ssl
import string
import warnings
from argparse import ArgumentParser, FileType
from dataclasses import asdict, dataclass
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile

import adif_io
import qrzlib
import yaml
from PIL import Image, ImageDraw, ImageFont

__version__ = version("e-qsl")

NEW_WIDTH = 1024

CONFIG_FILENAME = "eqsl.yaml"
CONFIG_LOCATIONS = ['.', '~/.local', '/etc']

FONTS = {
  'font_call': 'Ubuntu Mono derivative Powerline Bold.ttf',
  'font_text': 'DroidSansMono.ttf',
  'font_foot': 'VeraMono-Italic.ttf',
}

CACHE_EXPIRE = 86400 * 8

config = None

logging.basicConfig(
  format="%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s",
  level=logging.INFO
)

warnings.filterwarnings('ignore')


@dataclass
class QSOData:
  # pylint: disable=too-many-instance-attributes
  my_call: str
  my_gridsquare: str
  my_rig: str
  call: str
  frequency: float
  band: str
  mode: str
  rst_sent: str
  rst_rcvd: str
  tx_pwr: int
  timestamp: float
  name: str
  email: str
  sota_ref: str
  pota_ref: str
  lang: str

  def __init__(self, qso, cfg):
    date_on = qso.get('QSO_DATE_OFF', qso['QSO_DATE'])
    time_on = qso.get('TIME_OFF', qso.get('TIME_ON', '0000'))

    self.my_call = qso.get('OPERATOR', cfg.call)
    self.my_gridsquare = qso.get('MY_GRIDSQUARE', cfg.gridsquare)
    self.my_rig = qso.get('MY_RIG', cfg.myrig)
    self.call = qso['CALL']
    self.frequency = float(qso['FREQ'])
    self.band = qso['BAND']
    self.mode = qso['MODE']
    self.rst_sent = qso.get('RST_SENT', '599')
    self.rst_rcvd = qso.get('RST_RCVD', '599')
    self.tx_pwr = int(qso.get('TX_PWR', 100))
    self.timestamp = qso_timestamp(date_on, time_on)
    self.name = qso.get('NAME', 'Dear OM')
    self.email = qso.get('EMAIL', self.email_lookup(self.call, cfg))
    self.pota_ref = qso.get('POTA_REF')
    self.sota_ref = qso.get('SOTA_REF')
    self.lang = qso.get('COUNTRY', 'default').lower()

  def email_lookup(self, call, cfg):
    logging.warning('Email address for %s not found in the ADIF file, using qrz.com', call)
    try:
      key = config.qrz_key
    except AttributeError:
      logging.error('Impossible to retrieve the email from qrz.com: API key missing')
      raise SystemExit('qrz.com API key missing') from None

    qrz = qrzlib.QRZ()
    qrz.authenticate(cfg.call, key)
    try:
      qrz.get_call(call)
      return qrz.email
    except qrzlib.QRZ.NotFound:
      logging.error('No email address found for %s', call)
    return None


def draw_rectangle(draw, coord, color=(0x44, 0x79, 0x9), width=1, fill=(0x75, 0xDB, 0xCD, 190)):
  draw.rectangle(coord, outline=color, fill=fill)
  draw.rectangle(coord, outline=color, width=width)


def get_template(qso):
  # there is only one email template
  if hasattr(config, 'mail_template'):
    return string.Template(config.mail_template + '\n' * 3).safe_substitute
  if not hasattr(config, 'mail_templates') or not hasattr(config, 'languages'):
    raise KeyError('Not mail template or language found')

  languages = {v.lower(): k.lower() for k, values in config.languages.items() for v in values}
  lang = languages.get(qso.lang, 'default')
  if lang != 'default':
    logging.info('Using %s template for %s', lang, qso.lang)
  template = config.mail_templates.get(lang, "default")
  return string.Template(template + '\n' * 3).safe_substitute


def send_mail(qso, image, debug_email=None):
  template = get_template(qso)
  to_addr = debug_email if debug_email else qso.email

  msg = MIMEMultipart()
  msg['From'] = config.smtp_from
  msg['To'] = to_addr
  msg['Date'] = formatdate(localtime=True)
  msg['Subject'] = f"Digital QSL from {qso.my_call} to {qso.call}"

  data = asdict(qso)
  data['qso_date'] = datetime.fromtimestamp(qso.timestamp).strftime("%A %B %d, %Y at %X UTC")

  msg.attach(MIMEText(template(data)))

  with open(image, "rb") as fdi:
    part = MIMEApplication(fdi.read(), Name=os.path.basename(image))
    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(image)}"'
    msg.attach(part)

  context = ssl.create_default_context()
  try:
    with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
      server.ehlo()
      server.starttls(context=context)
      server.ehlo()
      server.login(config.smtp_login, config.smtp_password)
      server.sendmail(config.smtp_from, to_addr, msg.as_string())
  except ConnectionRefusedError as err:
    logging.error('Connection "%s" error: %s', config.smtp_server, err)
    raise SystemExit("Exit send_mail error") from None
  except (smtplib.SMTPDataError, smtplib.SMTPAuthenticationError) as err:
    logging.error('SMTP "%s": %s', config.smtp_server, err.smtp_error.decode('utf-8'))
    raise SystemExit("Exit send_mail error") from None


def card(qso, signature, image_name=None):
  # pylint: disable=too-many-locals
  width = NEW_WIDTH

  img = Image.open(config.qsl_card)
  img = img.convert("RGBA")
  img.info['comment'] = 'QSL Card generated by http://github.com/0x9900/QSL/'

  if img.size[0] < NEW_WIDTH and img.size < 576:
    logging.error("The card resolution should be at least 1024x576")
    raise SystemExit("Exit with error")

  font_call = ImageFont.truetype(config.font_call, 24)
  font_text = ImageFont.truetype(config.font_text, 16)
  font_foot = ImageFont.truetype(config.font_foot, 14)

  h_size, v_size = img.size
  ratio = width / h_size
  vsize = int(v_size * ratio)
  img = img.resize((width, vsize), Image.Resampling.LANCZOS)

  overlay = Image.new('RGBA', img.size)
  draw = ImageDraw.Draw(overlay)
  draw_rectangle(draw, ((112, vsize-230), (912, vsize-20)), width=3, fill=config.overlay_color)

  textbox = ImageDraw.Draw(overlay)
  date = datetime.fromtimestamp(qso.timestamp).strftime("%A %B %d, %Y at %X UTC")
  y_pos = vsize - 220
  x_pos = 132
  textbox.text((x_pos+10, y_pos), f"To: {qso.call}  From: {qso.my_call}",
               font=font_call, fill=config.text_color)
  textstr = (f'Mode: {qso.mode} • Band: {qso.band} • RST Send: {qso.rst_sent} • '
             f'RST Received: {qso.rst_rcvd}')
  textbox.text((x_pos, y_pos+40), textstr, font=font_text, fill=config.text_color)
  textbox.text((x_pos, y_pos+65), f'Date: {date}', font=font_text, fill=config.text_color)
  textbox.text((x_pos, y_pos+90), f' Rig: {qso.my_rig} • Power: {int(qso.tx_pwr):d} Watt',
               font=font_text, fill=config.text_color)
  textbox.text((x_pos, y_pos+115), (f'Grid: {qso.my_gridsquare} • CQ Zone: {config.ituzone} • '
                                    f'ITU Zone: {config.cqzone}'),
               font=font_text, fill=config.text_color)
  if qso.sota_ref:
    textbox.text((x_pos, y_pos+140), f'SOTA: Summit Reference ({qso.sota_ref})',
                 font=font_text, fill=config.text_color)
  elif qso.pota_ref:
    textbox.text((x_pos, y_pos+140), f'POTA: Park Reference ({qso.pota_ref})',
                 font=font_text, fill=config.text_color)

  textbox.text((x_pos, y_pos+165), signature, font=font_foot, fill=config.text_color)

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
  for _path in CONFIG_LOCATIONS:
    path = Path(_path).joinpath(CONFIG_FILENAME)
    filename = path.expanduser()
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
  logging.error('Follow the link bellow to find a configuration example')
  logging.error('https://github.com/0x9900/QSL/blob/main/eqsl.yaml.sample')
  raise SystemExit("Exit with error")


def read_config():
  _config = _read_config()

  for color_name in ('overlay_color', 'text_color'):
    _config[color_name] = tuple(_config[color_name])

  for font_name in ("font_call", "font_text", "font_foot"):
    font_path = _config.get(font_name)
    if not font_path:
      logging.warning('Font "%s" not configured. Using the default font', font_name)
      _config[font_name] = files('eqsl.fonts').joinpath(FONTS[font_name])
    elif not os.path.isfile(font_path):
      logging.warning('Font "%s" not found, using the default font', font_path)
      _config[font_name] = files('eqsl.fonts').joinpath(FONTS[font_name])
    else:
      _config[font_name] = font_path

  card_path = _config.get('qsl_card')
  if not card_path:
    logging.warning('QSL Card not configured. Using the default QSL Card')
    _config['qsl_card'] = files('eqsl.card').joinpath('default.jpg')
  elif not os.path.isfile(card_path):
    logging.warning('QSL Card "%s" not found, using the default QSL Card', card_path)
    _config['qsl_card'] = files('eqsl.card').joinpath('default.jpg')
  else:
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
  key = f'{qso.call}-{qso.band}-{qso.mode}'.upper()
  try:
    with dbm.open(config.qsl_cache, 'r') as qdb:
      cached = pickle.loads(qdb[key])
    if cached.timestamp > datetime.utcnow().timestamp() - CACHE_EXPIRE:
      return True
  except dbm.error:
    pass
  except (KeyError, IOError):
    pass

  try:
    with dbm.open(config.qsl_cache, 'c') as qdb:
      qdb[key] = pickle.dumps(qso)
  except IOError as err:
    logging.warning(err)
  return False


def parse_args():
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
  parser.add_argument("--resend", action="store_true", default=False,
                      help="Resend already sent QSL")
  parser.add_argument("--debug-email", help="Email address for debuging")
  parser.add_argument("--version", action="version", version=f'%(prog)s {__version__}')

  return parser.parse_args()


def main():
  global config  # pylint: disable=global-statement
  config = read_config()
  opts = parse_args()

  config.show_cards = bool(opts.show)

  try:
    qsos_raw, _ = adif_io.read_from_string(opts.adif_file.read())
  except IndexError:
    logging.error('Error reading the ADIF file "%s"', opts.adif_file.name)
    raise SystemExit("Exit with error") from None

  for _qso in qsos_raw:
    try:
      qso = QSOData(_qso, config)
    except KeyError as err:
      logging.error('The ADIF file is missing the key: %s', err)
      raise SystemExit(f'ADIF missing key: {err}') from None

    if not opts.resend and already_sent(qso):
      logging.warning('QSL already sent to %s', qso.call)
      continue

    if not opts.no_email:
      image_name = card(qso, config.signature)
      try:
        send_mail(qso, image_name, opts.debug_email)
      except smtplib.SMTPRecipientsRefused:
        logging.warning('Error Recipient "%s" malformed', qso.email)
      else:
        logging.info('Mail sent to %s at %s', qso.call,
                     opts.debug_email if opts.debug_email else qso.email)

    if not opts.keep:
      os.unlink(image_name)

  opts.adif_file.close()
  if not opts.keep:
    move_adif(opts.adif_file)


if __name__ == "__main__":
  main()
