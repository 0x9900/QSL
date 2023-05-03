#!/usr/bin/env python3
#
# BSD 3-Clause License
#
# Copyright (c) 2023, Fred W6BSD
# All rights reserved.
#

import sys

from setuptools import setup

__author__ = "Fred C. (W6BSD)"
__version__ = "0.1.10"
__license__ = 'BSD-3'

py_version = sys.version_info[:2]
if py_version < (3, 8):
  raise RuntimeError('eqsl requires Python 3.8 or later')

def readme():
  with open('README.md', encoding="utf-8") as fdr:
    return fdr.read()

setup(
  name='e-qsl',
  version=__version__,
  description='Send contacts confirmation cards (QSL Cards)',
  long_description=readme(),
  long_description_content_type='text/markdown',
  url='https://github.com/0x9900/QSL/',
  license=__license__,
  author=__author__,
  author_email='w6bsd@bsdworld.org',
  py_modules=['eqsl'],
  install_requires=['Pillow', 'adif_io', 'qrzlib', 'PyYAML'],
  entry_points = {
    'console_scripts': ['eqsl = eqsl:main'],
  },
  package_data = {
    "sql": ["fonts/*.ttf", "cards/*.jpg"],
  },
  classifiers=[
    'Development Status :: 3 - Alpha',
    'Intended Audience :: Telecommunications Industry',
    'License :: OSI Approved :: BSD License',
    'Operating System :: OS Independent',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.8',
    'Topic :: Communications :: Ham Radio',
  ],
)
