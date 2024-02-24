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
from argparse import ArgumentParser
from importlib.metadata import version
from pathlib import Path
from subprocess import call
from typing import Optional

from watchfiles import Change, DefaultFilter, watch

SHOW_CARD = False
KEEP_CARD = False

logging.basicConfig(
  format="%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s",
  level=logging.INFO
)
wf_log = logging.getLogger('watchfiles.main')
wf_log.setLevel(logging.CRITICAL)

__version__ = version("e-qsl")


def send_cards(filename: Path, show_card: bool, keep_card: bool) -> None:
  eqsl: Optional[str] = shutil.which('eqsl')
  if not eqsl:
    raise FileNotFoundError('eqsl not found')

  args: list[str] = [eqsl, '-a', str(filename)]
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


def sendcard() -> None:
  parser = ArgumentParser(description="Watch for the creation on an adif file and call eqsl")
  parser.add_argument("-s", "--show", action="store_true", default=False,
                      help="Show the card")
  parser.add_argument("-k", "--keep", action="store_true", default=False,
                      help="Keep the cards after they have been sent (do not delete)")
  parser.add_argument("-a", "--adif", required=True,
                      help="ADIF file name")
  parser.add_argument("--version", action="version", version=f'eqsl.%(prog)s {__version__}')
  opts = parser.parse_args()

  full_name = Path(opts.adif).expanduser().absolute()
  if full_name.exists():
    logging.info('The ADIF file already exists. Sending cards.')
    send_cards(full_name, opts.show, opts.keep)

  path = full_name.parent
  adif_file = full_name.parts[-1]

  if not path.exists():
    raise FileNotFoundError(f'The directory {path} does not exist')

  watch_filter = ADIFilter(path, adif_file)
  logging.info('Sendcards watching %s for %s', path, adif_file)
  for changes in watch(path, watch_filter=watch_filter, debounce=3200, recursive=False):
    for change, filename in changes:
      if change == Change.added:
        logging.info('Calling send_cards with %s', filename)
        send_cards(filename, opts.show, opts.keep)


def main():
  try:
    sendcard()
  except FileNotFoundError as err:
    logging.info(err)
  except KeyboardInterrupt:
    logging.info('Exit "^C" pressed')


if __name__ == "__main__":
  main()
