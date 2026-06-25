"""Test spectree."""

# flake8: noqa: D102

from dataclasses import dataclass
import stat
import unittest
from unittest import mock

from .context import spectree  # noqa: F401

from spectree import spectree as spectreesut  # noqa: I100


@dataclass
class FakeStat:
    st_mode: int = 0


class TestGetLocalPackagePaths(unittest.TestCase):
    """Test get_local_package_paths."""

    @mock.patch('glob.glob', side_effect=[['regularfile', 'anotherfile', 'adir', 'moredir']])
    @mock.patch('os.stat', side_effect=lambda fn: FakeStat(stat.S_IFDIR) if fn.endswith('dir') else FakeStat(stat.S_IFREG))
    def test_get_local_package_paths(self, mock_stat, mock_glob):
        self.assertCountEqual(spectreesut.get_local_package_paths('*'),
                              ['adir', 'moredir'])


class TestDetermineSpecTreeStyle(unittest.TestCase):
    """Test determine_spec_tree_style."""

    @mock.patch('glob.glob', side_effect=[['massivepackage']])
    @mock.patch('os.stat', side_effect=lambda fn: FakeStat(stat.S_IFDIR) if fn == 'massivepackage/current/SPECS' else mock.Mock(side_effect=OSError)())
    def test_get_local_package_paths_massive(self, mock_stat, mock_glob):
        self.assertEqual(spectreesut.determine_spec_tree_style('*'),
                         spectreesut.SpecStyle.SPEC_STYLE_MASSIVE)

    @mock.patch('glob.glob', side_effect=[['individualpackage']])
    @mock.patch('os.stat', side_effect=lambda fn: FakeStat(stat.S_IFDIR) if fn == 'individualpackage/SPECS' else mock.Mock(side_effect=OSError)())
    def test_get_local_package_paths_individual(self, mock_stat, mock_glob):
        self.assertEqual(spectreesut.determine_spec_tree_style('*'),
                         spectreesut.SpecStyle.SPEC_STYLE_INDIVIDUAL)

    @mock.patch('glob.glob', side_effect=[['speconlypackage']])
    @mock.patch('os.stat', side_effect=lambda fn: FakeStat(stat.S_IFREG) if fn == 'speconlypackage/speconlypackage.spec' else mock.Mock(side_effect=OSError)())
    def test_get_local_package_paths_speconly(self, mock_stat, mock_glob):
        self.assertEqual(spectreesut.determine_spec_tree_style('*'),
                         spectreesut.SpecStyle.SPEC_STYLE_SPEC_ONLY)

    @mock.patch('glob.glob', side_effect=[['unknown']])
    @mock.patch('os.stat', side_effect=OSError)
    def test_get_local_package_paths_unknown(self, mock_stat, mock_glob):
        self.assertEqual(spectreesut.determine_spec_tree_style('*'),
                         spectreesut.SpecStyle.SPEC_STYLE_UNKNOWN)


class TestMakeSpecPath(unittest.TestCase):
    """Test make_spec_path."""

    def test_make_spec_path_massive(self):
        self.assertEqual(spectreesut.make_spec_path('/path/to/mypackage',
                                                    spectreesut.SpecStyle.SPEC_STYLE_MASSIVE),
                         '/path/to/mypackage/current/SPECS/mypackage.spec')

    def test_make_spec_path_individual(self):
        self.assertEqual(spectreesut.make_spec_path('/path/to/myindividualpackage',
                                                    spectreesut.SpecStyle.SPEC_STYLE_INDIVIDUAL),
                         '/path/to/myindividualpackage/SPECS/myindividualpackage.spec')

    def test_make_spec_path_speconly(self):
        self.assertEqual(spectreesut.make_spec_path('/path/to/myspeconlypackage',
                                                    spectreesut.SpecStyle.SPEC_STYLE_SPEC_ONLY),
                         '/path/to/myspeconlypackage/myspeconlypackage.spec')
