"""Test spec_rpm_mismatch."""

# flake8: noqa: D102

import unittest

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
