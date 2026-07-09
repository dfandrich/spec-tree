"""Test spec_url_check."""

# flake8: noqa: D102

import io
import textwrap
import unittest
from unittest import mock

from .context import spectree  # noqa: F401

from spectree import spec_url_check  # noqa: I100


class TestGetUrlsFromSpec(unittest.TestCase):
    """Test get_urls_from_spec."""

    URLS = textwrap.dedent("""\
        https://example.com/
        https://example.com/1
        ftp://example/
        https://example.com/
        not-a-url.gz
    """)

    @mock.patch('os.popen', return_value=io.StringIO(URLS))
    def test_get_urls_from_spec(self, mock_popen):
        self.assertCountEqual(spec_url_check.get_urls_from_spec('test.spec'),
                              ['https://example.com/', 'https://example.com/1', 'ftp://example/'])


class TestGetSourcesFromSpec(unittest.TestCase):
    """Test get_sources_from_spec."""

    SOURCES = textwrap.dedent("""\
Source0: https://example.com/download/xyzzy-1.2.3.tar.xz
Source1: https://example.com/download/xyzzy-1.2.3.tar.xz.asc
Bad Line should be ignored
Source2: coaps+ws://real-scheme
Patch0: security.patch
Patch1: ftp://example.net/security.patch
Patch2: gopher://example.net/9/patch
Patch2: 133+chaos://patch-not-scheme
    """)

    @mock.patch('os.popen', return_value=io.StringIO(SOURCES))
    def test_get_urls_from_spec(self, mock_popen):
        self.assertEqual(spec_url_check.get_sources_from_spec('test.spec'),
            ({'https://example.com/download/xyzzy-1.2.3.tar.xz',
              'https://example.com/download/xyzzy-1.2.3.tar.xz.asc',
              'coaps+ws://real-scheme'},
             {'ftp://example.net/security.patch',
              'gopher://example.net/9/patch'}))

