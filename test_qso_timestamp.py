#!/usr/bin/env python3
"""
Simple test suite for the qso_timestamp function from eqsl._eqsl module.
Tests the core functionality: 4-character and 6-character timestamp handling.
"""

from datetime import datetime

from eqsl._eqsl import qso_timestamp


def test_4_character_timestamp():
  """Test that 4-character timestamps work correctly."""
  result = qso_timestamp('20240115', '1430')
  expected = datetime(2024, 1, 15, 14, 30).timestamp()
  assert result == expected


def test_6_character_timestamp_truncation():
  """Test that 6-character timestamps are truncated to 4 characters."""
  result = qso_timestamp('20240115', '143045')
  expected = datetime(2024, 1, 15, 14, 30).timestamp()
  assert result == expected


def test_default_time():
  """Test that default time '0000' is used when no time is provided."""
  result = qso_timestamp('20240115')
  expected = datetime(2024, 1, 15, 0, 0).timestamp()
  assert result == expected


def test_longer_timestamp_truncation():
  """Test that timestamps longer than 6 characters are truncated to 4."""
  result = qso_timestamp('20240115', '14304567')
  expected = datetime(2024, 1, 15, 14, 30).timestamp()
  assert result == expected
