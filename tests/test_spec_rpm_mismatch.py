"""Test spec_rpm_mismatch."""

# flake8: noqa: D102

import io
import textwrap
import unittest
from unittest import mock

from .context import spectree  # noqa: F401

from spectree import spec_rpm_mismatch  # noqa: I100


class TestPackageName(unittest.TestCase):
    """Test package_name."""

    def test_package_name(self):
        for pkg, name in [
            ('foo-123-1.mga1.src.rpm', 'foo'),
            ('tilde-app-49~alpha-6.mga10.src.rpm', 'tilde-app'),
            ('a-0-0.mga99.src.rpm', 'a'),
            ('sub-rev-0.1.2.3-0.1.mga99.src.rpm', 'sub-rev'),
            ('plus-9.4+2.4-5.mga10.src.rpm', 'plus'),
            ('bleeding-edge-2.4.0-0.git20250525.3.mga10.src.rpm', 'bleeding-edge'),
            ('dnf-4.99.0^really5.4.0.0-3.mga10.src.rpm', 'dnf'),
            ('gtk4.0-4.10.3-3.mga9.src.rpm', 'gtk4.0'),
        ]:
            with self.subTest(pkg=pkg, name=name):
                self.assertEqual(spec_rpm_mismatch.package_name(pkg), name)

    def test_package_name_false(self):
        for pkg in [
            'xyzzy',
            'foo-123-1.mga1',
            'foo-123-1.mga1.x86_64.rpm',
            'not-1-99-3%4.mga9.src.rpm',
        ]:
            with self.subTest(pkg=pkg):
                self.assertEqual(spec_rpm_mismatch.package_name(pkg), '')


class TestRpmBaseName(unittest.TestCase):
    """Test rpm_base_name."""

    def test_rpm_base_name(self):
        for pkg, namever in [
            ('foo-123-1.mga1.src.rpm', 'foo-123-1.mga1'),
            ('tilde-app-49~alpha-6.mga10.src.rpm', 'tilde-app-49~alpha-6.mga10'),
            ('a-0-0.mga99.src.rpm', 'a-0-0.mga99'),
            ('sub-rev-0.1.2.3-0.1.mga99.src.rpm', 'sub-rev-0.1.2.3-0.1.mga99'),
            ('plus-9.4+2.4-5.mga10.src.rpm', 'plus-9.4+2.4-5.mga10'),
            ('bleeding-edge-2.4.0-0.git20250525.3.mga10.src.rpm', 'bleeding-edge-2.4.0-0.git20250525.3.mga10'),
            ('dnf-4.99.0^really5.4.0.0-3.mga10.src.rpm', 'dnf-4.99.0^really5.4.0.0-3.mga10'),
            ('xyzzy', ''),
        ]:
            with self.subTest(pkg=pkg, namever=namever):
                self.assertEqual(spec_rpm_mismatch.rpm_base_name(pkg), namever)


class TestRpmVersions(unittest.TestCase):
    """Test rpm_versions."""

    def test_rpm_versions(self):
        for pkg, versions in [
            ('foo-123-1.mga1', ('foo', '123', '1', 'mga1')),
            ('tilde-app-49~alpha-6.mga10', ('tilde-app', '49~alpha', '6', 'mga10')),
            ('a-0-0.mga99', ('a', '0', '0', 'mga99')),
            ('sub-rev-0.1.2.3-0.1.mga99', ('sub-rev', '0.1.2.3', '0.1', 'mga99')),
            ('plus-9.4+2.4-5.mga10', ('plus', '9.4+2.4', '5', 'mga10')),
            ('bleeding-edge-2.4.0-0.git20250525.3.mga10', ('bleeding-edge', '2.4.0', '0.git20250525.3', 'mga10')),
            ('dnf-4.99.0^really5.4.0.0-3.mga10', ('dnf', '4.99.0^really5.4.0.0', '3', 'mga10')),
            ('xyzzy', ('', '', '', '')),
        ]:
            with self.subTest(pkg=pkg, versions=versions):
                self.assertEqual(spec_rpm_mismatch.rpm_versions(pkg), versions)


class TestResultCollection(unittest.TestCase):
    """Test ResultCollection."""

    def setUp(self):
        self.testrc = spec_rpm_mismatch.ResultCollection()
        self.testrc.add(spec_rpm_mismatch.NoSrpmFile(name='nosrpm_pkg'))
        self.testrc.add(spec_rpm_mismatch.ParseError(name='parseerror2_pkg'))
        self.testrc.add(spec_rpm_mismatch.ParseError(name='parseerror_pkg'))
        self.testrc.add(spec_rpm_mismatch.VersionMismatch(
            name='versionmatch_pkg', srpm_name='versionmatch_pkg-0-1-2.mga3.src.rpm',
            base_name='versionmatch_pkg-0-1-1.mga3.src.rpm'))

    def test_is_matching(self):
        self.assertCountEqual(self.testrc.matching(spec_rpm_mismatch.NoSrpmFile),
                              [spec_rpm_mismatch.NoSrpmFile('nosrpm_pkg')])
        self.assertCountEqual(self.testrc.matching(spec_rpm_mismatch.ParseError),
                              [spec_rpm_mismatch.ParseError('parseerror_pkg'),
                               spec_rpm_mismatch.ParseError('parseerror2_pkg')])
        self.assertCountEqual(self.testrc.matching(spec_rpm_mismatch.VersionMismatch),
                              [spec_rpm_mismatch.VersionMismatch(
                                   name='versionmatch_pkg',
                                   srpm_name='versionmatch_pkg-0-1-2.mga3.src.rpm',
                                   base_name='versionmatch_pkg-0-1-1.mga3.src.rpm')])

    def test_has_matching(self):
        self.assertTrue(self.testrc.has_matching(spec_rpm_mismatch.NoSrpmFile))
        self.assertTrue(self.testrc.has_matching(spec_rpm_mismatch.ParseError))
        self.assertTrue(self.testrc.has_matching(spec_rpm_mismatch.VersionMismatch))

    def test_has_matching_false(self):
        self.assertFalse(self.testrc.has_matching(spec_rpm_mismatch.VersionMatch))


class TestRetrieveDirContents(unittest.TestCase):
    """Test RetrieveDirContents."""

    def test_retrieve_dir_contents_unsupported_scheme(self):
        with self.assertRaises(RuntimeError):
            spec_rpm_mismatch.retrieve_dir_contents('rtsp://valid/but/unsupported')

    @mock.patch('os.popen', return_value=io.StringIO('foo\nbar\n'))
    def test_retrieve_dir_contents_http_unsupported(self, mock_popen):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('http://unsupported/'), [])

    NGINX_LISTING = textwrap.dedent("""\
        <html>
        <head><title>Index of /nginx/</title></head>
        <body>
        <h1>Index of /nginx/</h1><hr><pre><a href="../">../</a>
        <a href="software/">software/</a>                                          24-Feb-2020 12:14       -
        <a href="mirror.readme">mirror.readme</a>                                      15-Sep-2024 13:04    2381
        </pre><hr></body>
        </html>
    """)

    @mock.patch('os.popen', return_value=io.StringIO(NGINX_LISTING))
    def test_retrieve_dir_contents_http_nginx(self, mock_popen):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('http://nginx-server/'),
                              ['mirror.readme'])

    APACHE_LISTING = textwrap.dedent("""\
        <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
        <html>
         <head>
          <title>Index of /pub/apache</title>
         </head>
         <body>
        <h1>Index of /pub/apache</h1>
          <table>
           <tr><th valign="top"><img src="/icons/blank.gif" alt="[ICO]"></th><th><a href="?C=N;O=D">Name</a></th><th><a href="?C=M;O=A">Last modified</a></th><th><a href="?C=S;O=A">Size</a></th><th><a href="?C=D;O=A">Description</a></th></tr>
           <tr><th colspan="5"><hr></th></tr>
        <tr><td valign="top"><img src="/icons/back.gif" alt="[PARENTDIR]"></td><td><a href="/pub/">Parent Directory</a></td><td>&nbsp;</td><td align="right">  - </td><td>&nbsp;</td></tr>
        <tr><td valign="top"><img src="/icons/text.gif" alt="[TXT]"></td><td><a href="mirror.readme">mirror.readme</a></td><td align="right">2024-09-15 09:04  </td><td align="right">2.3K</td><td>&nbsp;</td></tr>
        <tr><td valign="top"><img src="/icons/folder.gif" alt="[DIR]"></td><td><a href="software/">software/</a></td><td align="right">2020-02-24 07:14  </td><td align="right">  - </td><td>&nbsp;</td></tr>
           <tr><th colspan="5"><hr></th></tr>
        </table>
        </body></html>
    """)

    @mock.patch('os.popen', return_value=io.StringIO(APACHE_LISTING))
    def test_retrieve_dir_contents_http_apache(self, mock_popen):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('http://apache-server/'),
                              ['mirror.readme'])

    LIGHTTPD_LISTING = textwrap.dedent("""\
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="UTF-8">
        <title>Index of /root/lighttpd-server/</title>
        <style type="text/css">
        a, a:active {text-decoration: none; color: blue;}
        // elided
        </style>
        <meta name="color-scheme" content="light dark">
        </head>
        <body>
        <pre class="header"></pre><h2>Index of /root/lighttpd-server/</h2>
        <div class="list">
        <table summary="Directory Listing" cellpadding="0" cellspacing="0">
        <thead><tr><th class="n">Name</th><th class="m">Last Modified</th><th class="s">Size</th><th class="t">Type</th></tr></thead>
        <tbody>
        <tr class="d"><td class="n"><a href="../">..</a>/</td><td class="m" data-value="-1">&nbsp;</td><td class="s" data-value="-1">- &nbsp;</td><td class="t">Directory</td></tr>
        <tr class="d"><td class="n"><a href="software/">software</a>/</td><td class="m">2023-Dec-16 20:34:09</td><td class="s" data-value="-1">- &nbsp;</td><td class="t">Directory</td></tr>
        <tr><td class="n"><a href="mirror.readme">mirror.readme</a></td><td class="m">2026-Jul-09 15:12:33</td><td class="s" data-value="0">0.0K</td><td class="t">text/plain</td></tr>
        </tbody>
        </table>
        </div>
        <pre class="readme"></pre><div class="foot">lighttpd/1.4.80</div>

        <script type="text/javascript">
        // <!--
        // Javascript elided
        // -->
        </script>

        </body>
        </html>
    """)

    @mock.patch('os.popen', return_value=io.StringIO(LIGHTTPD_LISTING))
    def test_retrieve_dir_contents_http_lighttpd(self, mock_popen):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('http://lighttpd-server/'),
                              ['mirror.readme'])

    IIS_LISTING = textwrap.dedent("""\
<html><head>
<title>iis-server - /</title></head><body>
 <h1>iis-server - /</h1><hr>

<pre> 9/28/2021  1:54 PM        &lt;dir&gt; <a href="software/">software</a><br> 9/28/2021  7:57 AM          102 <a href="mirror.readme">mirror.readme</a><br></pre><hr></body></html>
""")

    @mock.patch('os.popen', return_value=io.StringIO(IIS_LISTING))
    def test_retrieve_dir_contents_iis(self, mock_popen):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('http://iis-server/'),
                              ['mirror.readme'])

    FTP_LISTING = textwrap.dedent("""\
        mirror.readme
        software
    """)

    @mock.patch('os.popen', return_value=io.StringIO(FTP_LISTING))
    def test_retrieve_dir_contents_ftp(self, mock_popen):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('ftp://generic-ftp/'),
                              ['mirror.readme', 'software'])

    @mock.patch('os.listdir', return_value=['mirror.readme', 'software'])
    def test_retrieve_dir_contents_file(self, mock_listdir):
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('file:///filesystem/dir/'),
                              ['mirror.readme', 'software'])
        self.assertCountEqual(spec_rpm_mismatch.retrieve_dir_contents('file://localhost/dir/'),
                              ['mirror.readme', 'software'])


class TestRetrieveAllPackages(unittest.TestCase):
    """Test retrieve_all_packages."""

    @mock.patch('spectree.spec_rpm_mismatch.retrieve_dir_contents',
                return_value=[
                    'null-0.4-9.mga9.src.rpm',
                    'task-obsolete-9-123.mga9.src.rpm',
                    'not-regular.rpm',
                    'media_info'])
    def test_retrieve_all_packages(self, mock_dir):
        expected = ({'null-0.4-9.mga9', 'task-obsolete-9-123.mga9'},
                    {'null': 'null-0.4-9.mga9', 'task-obsolete': 'task-obsolete-9-123.mga9'})

        self.assertEqual(spec_rpm_mismatch.retrieve_all_packages('http://dummy.example.com/rpms/'),
                         expected)

    def test_retrieve_all_packages_bad_scheme(self):
        with self.assertRaises(RuntimeError):
            spec_rpm_mismatch.retrieve_all_packages('not-real-scheme://just/made/up')

    @mock.patch('spectree.spec_rpm_mismatch.retrieve_dir_contents', return_value=[])
    def test_retrieve_all_packages_empty(self, mock_dir):
        with self.assertRaises(RuntimeError):
            spec_rpm_mismatch.retrieve_all_packages('http://server.example.com/emptydir/')


class TestGetSrpmNameStubFromSpec(unittest.TestCase):
    """Test get_srpm_name_stub_from_spec."""

    @mock.patch('os.popen', return_value=io.StringIO('foo-bar-1.23-4.NOREL\nlib64foobar0-1.23-4.NOREL\n'))
    def test_get_srpm_name_stub_from_spec(self, mock_popen):
        self.assertEqual(spec_rpm_mismatch.get_srpm_name_stub_from_spec('dummy.spec', 'NOREL'),
                         'foo-bar-1.23-4.NOREL')

    @mock.patch('os.popen', return_value=io.StringIO(''))
    def test_get_srpm_name_stub_from_spec_empty(self, mock_popen):
        self.assertEqual(spec_rpm_mismatch.get_srpm_name_stub_from_spec('not-spec', 'NOREL'), '')
