#!/usr/bin/env python
#
# BSD 3-Clause License
# Copyright (c) 2023 Fred W6BSD All rights reserved.
#

"""
`sendcard` is a companion program for e-qsl (https://pypi.org/project/e-qsl/)
This program monitors a directory for an ADIF file and then calls `eqsl`
with the file as an argument.
"""

import logging
import os
import shutil
import sys
from argparse import ArgumentParser
from importlib.metadata import version
from subprocess import call
from typing import Optional

from watchfiles import Change, DefaultFilter, watch

DEFAULT_ADIF = 'MacLoggerDX_Export.adi'
DEFAULT_DIR = '/Users/fred/Downloads'
SHOW_CARD = False
KEEP_CARD = False

logging.basicConfig(
  format="%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s",
  level=logging.INFO
)
wf_log = logging.getLogger('watchfiles.main')
wf_log.setLevel(logging.CRITICAL)

__version__ = version("e-qsl")


def send_cards(filename: str, show_card: bool, keep_card: bool) -> None:
  eqsl: Optional[str] = shutil.which('eqsl')
  if not eqsl:
    raise FileNotFoundError('eqsl not found')

  args: list[str] = [eqsl, '-a', filename]
  if not os.path.exists(filename):
    return
  if show_card:
    args.append('-s')
  if keep_card:
    args.append('-k')

  logging.info('Command: %s', ' '.join(args))
  call(args)


class ADIFilter(DefaultFilter):
  # pylint: disable=too-few-public-methods

  def __init__(self, directory: str, name: str) -> None:
    super().__init__()
    self.full_name = os.path.join(directory, name)

  def __call__(self, change: Change, path: str) -> bool:
    return super().__call__(change, path) and path == self.full_name


def main() -> None:
  parser = ArgumentParser(description="DXCC entities lookup")
  parser.add_argument("-s", "--show", action="store_true", default=False,
                      help="Show the card")
  parser.add_argument("-k", "--keep", action="store_true", default=False,
                      help="Keep the card in the temporary directory")
  parser.add_argument("-p", "--path", default=DEFAULT_DIR,
                      help="Path [default: %(default)s]")
  parser.add_argument("-a", "--adif", default=DEFAULT_ADIF,
                      help="ADIF file to watch [default: %(default)s]")
  parser.add_argument("--version", action="version", version=f'eqsl.%(prog)s {__version__}')
  opts = parser.parse_args()

  full_name = os.path.join(opts.path, opts.adif)
  if os.path.exists(full_name):
    logging.info('The ADIF file already exists. Sending cards.')
    send_cards(full_name, opts.show, opts.keep)

  watch_filter = ADIFilter(opts.path, opts.adif)
  logging.info('Sendcards watching %s for %s', opts.path, opts.adif)
  for changes in watch(opts.path, watch_filter=watch_filter, debounce=3200, recursive=False):
    if Change.deleted in [c for c, _ in changes]:
      continue
    for _, filename in changes:
      logging.info('Calling send_cards with %s', filename)
      send_cards(full_name, opts.show, opts.keep)


if __name__ == "__main__":
  try:
    main()
  except (FileNotFoundError, KeyboardInterrupt) as err:
    logging.info(err)
    sys.exit()
