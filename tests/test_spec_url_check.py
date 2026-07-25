"""Test spec_url_check."""

# flake8: noqa: D102

import io
import textwrap
import unittest
from typing import ClassVar
from unittest import mock

from .context import spectree  # noqa: F401

from spectree import spec_url_check  # noqa: I100
from spectree.spectree import SpecStyle


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
        self.assertCountEqual(['https://example.com/', 'https://example.com/1', 'ftp://example/'],
                              spec_url_check.get_urls_from_spec('test.spec'))


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
        self.assertEqual(
            ({'https://example.com/download/xyzzy-1.2.3.tar.xz',
              'https://example.com/download/xyzzy-1.2.3.tar.xz.asc',
              'coaps+ws://real-scheme'},
             {'ftp://example.net/security.patch',
              'gopher://example.net/9/patch'}),
                spec_url_check.get_sources_from_spec('test.spec'))


class TestProcessPackages(unittest.TestCase):
    """Test process_packages."""

    def setUp(self):
        super().setUp()
        self.maxDiff = 4000

    spec_returns: ClassVar[dict[str, io.StringIO]] = {
        r'rpmspec -q --queryformat "%{URL}\n" -- coolthing/coolthing.spec':
            io.StringIO(
                'https://coolthing.example.com/\n'
                'https://coolthing.example.com/more\n'
                'https://coolthing.example.com/\n'
            ),
        r'spectool -- coolthing/coolthing.spec':
            io.StringIO('Source: https://example.com/coolthing-1.2.3.tgz'),
        r'rpmspec -q --queryformat "%{URL}\n" -- superapp/superapp.spec':
            io.StringIO(
                'ftp://geocities.example/superapp.txt\n'
                'http://example.org/SuperAPP\n'
            ),
        r'spectool -- superapp/superapp.spec':
            io.StringIO(
                'Source0: http://geocities.example/superapp-dl.asp?pkg\n'
                'Source1: bigfile.bin\n'
                'Source2: https://example.com/download.bin\n'
                'Patch0: https://example.com/download.patch\n'
                )
    }

    @mock.patch('os.popen', side_effect=lambda f, m: TestProcessPackages.spec_returns[f])
    def test_process_packages(self, mock_popen):
        proc = spec_url_check.PackageProcessor(SpecStyle.SPEC_STYLE_SPEC_ONLY)
        spec_pkgs = ['coolthing', 'superapp']

        spec_url_check.process_packages(proc, spec_pkgs)

        self.assertCountEqual([
            spec_url_check.UrlResult(
                name='coolthing',
                use=spec_url_check.UrlType.SOURCE,
                url='https://example.com/coolthing-1.2.3.tgz',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='coolthing',
                use=spec_url_check.UrlType.URL,
                url='https://coolthing.example.com/',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='coolthing',
                use=spec_url_check.UrlType.URL,
                url='https://coolthing.example.com/more',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='superapp',
                use=spec_url_check.UrlType.SOURCE,
                url='http://geocities.example/superapp-dl.asp?pkg',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='superapp',
                use=spec_url_check.UrlType.SOURCE,
                url='https://example.com/download.bin',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='superapp',
                use=spec_url_check.UrlType.PATCH,
                url='https://example.com/download.patch',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='superapp',
                use=spec_url_check.UrlType.URL,
                url='ftp://geocities.example/superapp.txt',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='superapp',
                use=spec_url_check.UrlType.URL,
                url='http://example.org/SuperAPP',
                status=spec_url_check.UrlStatus.UNCHECKED),
           ],
           proc.result)


class TestPackageProcessor(unittest.TestCase):
    """Test PackageProcessor.

    Some testing of this class is also performed by TestProcessPackages.
    """

    def test_update_url_status(self):
        proc = spec_url_check.PackageProcessor(SpecStyle.SPEC_STYLE_SPEC_ONLY)
        # Jam canned data into the processor
        proc.result = [
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.SOURCE,
                url='https://example.com/pkg1',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.PATCH,
                url='https://example.com/pkg1.patch',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.URL,
                url='https://homepage.example.com/',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.URL,
                url='rtsp://video.example.com/',
                status=spec_url_check.UrlStatus.UNCHECKED),
            spec_url_check.UrlResult(
                name='pkg2',
                use=spec_url_check.UrlType.URL,
                url='https://homepage.example.com',
                status=spec_url_check.UrlStatus.UNCHECKED),
        ]
        update_status = {
            'https://homepage.example.com/': spec_url_check.UrlStatus.VALID,
            'https://example.com/pkg1.patch': spec_url_check.UrlStatus.REDIRECT,
            'https://example.com/pkg1':  spec_url_check.UrlStatus.NOT_FOUND,
        }

        proc.update_url_status(update_status)

        self.assertCountEqual([
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.SOURCE,
                url='https://example.com/pkg1',
                status=spec_url_check.UrlStatus.NOT_FOUND),
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.PATCH,
                url='https://example.com/pkg1.patch',
                status=spec_url_check.UrlStatus.REDIRECT),
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.URL,
                url='https://homepage.example.com/',
                status=spec_url_check.UrlStatus.VALID),
            spec_url_check.UrlResult(
                name='pkg1',
                use=spec_url_check.UrlType.URL,
                url='rtsp://video.example.com/',
                status=spec_url_check.UrlStatus.UNSUPPORTED),
            spec_url_check.UrlResult(
                name='pkg2',
                use=spec_url_check.UrlType.URL,
                url='https://homepage.example.com',
                status=spec_url_check.UrlStatus.VALID),
        ], proc.result)


class TestStatusFromResponseCode(unittest.TestCase):
    """Test status_from_response_code."""

    def test_status_from_response_code(self):

        for url, code, status in [
            ('http://example.com', 204, spec_url_check.UrlStatus.VALID),
            ('https://example.com/not-found', 404, spec_url_check.UrlStatus.NOT_FOUND),
            ('http://invalid/', 500, spec_url_check.UrlStatus.TEMPORARY_ERR),
            ('http://www.example.org/pub', 423, spec_url_check.UrlStatus.TEMPORARY_ERR),
            ('http://bigcorp.example/', 401, spec_url_check.UrlStatus.AUTHENTICATE),
            ('http://oldsite.example/', 301, spec_url_check.UrlStatus.REDIRECT),
            ('https://future.example/', 777, spec_url_check.UrlStatus.UNSUPPORTED),
            ('ftp://fine.example.org/good', 350, spec_url_check.UrlStatus.VALID),
            ('ftp://fine.example.org/', 550, spec_url_check.UrlStatus.NOT_FOUND),
            ('ftp://ftp.example.org/private', 530, spec_url_check.UrlStatus.AUTHENTICATE),
            ('ftps://ftp.example.org/private', 221, spec_url_check.UrlStatus.TEMPORARY_ERR),
            ('ftps://ftp.example.org/bad', 421, spec_url_check.UrlStatus.TEMPORARY_ERR),
            ('ftps://ftp.future.example/', 777, spec_url_check.UrlStatus.UNSUPPORTED),
            ('quantumleap://video.example.org/', 9998, spec_url_check.UrlStatus.UNSUPPORTED),
        ]:
            with self.subTest(url=url, code=code, status=status):
                self.assertEqual(status, spec_url_check.status_from_response_code(code, url))
