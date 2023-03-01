'''Functions for manipulating a tree of RPM spec files

Copyright © 2014–2023 Daniel Fandrich.
This program is free software; you can redistribute it and/or modify
Licensed under GNU General Public License 2.0 or later.
Some rights reserved. See COPYING.

Usage: bad-url-report >report.html 2>errors.log
 within directory prepared by checkout-all-specs
'''

# TODO: maybe rename this module to reporting or something more specific

import collections
import enum
import glob
import os
import shlex
import stat
from logging import debug, error, info
from typing import Dict, List


# Default glob pattern to match local .srpm files
LOCAL_PACKAGE_GLOB = '*'

# Source for the maintdb
MAINTDB_URL = 'https://pkgsubmit.mageia.org/data/maintdb.txt'

# String to use for an unknown packager
UNKNOWN_PACKAGER = '?'


class SpecStyle(enum.IntEnum):
    '''The layout of the user's spec file tree.'''
    SPEC_STYLE_UNKNOWN = enum.auto()
    SPEC_STYLE_MASSIVE = enum.auto()
    SPEC_STYLE_INDIVIDUAL = enum.auto()
    SPEC_STYLE_SPEC_ONLY = enum.auto()


SPEC_STYLE_NAME = {
    SpecStyle.SPEC_STYLE_UNKNOWN: 'unknown',
    SpecStyle.SPEC_STYLE_MASSIVE: 'massive checkout',
    SpecStyle.SPEC_STYLE_INDIVIDUAL: 'individual packages',
    SpecStyle.SPEC_STYLE_SPEC_ONLY: 'spec only',
}


def get_local_package_paths(package_glob: str) -> List[str]:
    'Get a list of local package paths with spec files to check'
    spec_packages = glob.glob(package_glob)
    return [f for f in spec_packages if stat.S_ISDIR(os.stat(f).st_mode)]


def determine_spec_tree_style(package_glob: str) -> int:
    'Figure out why kind of style of SVN checkout is in use'
    package_file = glob.glob(package_glob)[-1]
    debug('Checking spec style based on %s', package_file)
    try:
        if stat.S_ISDIR(os.stat(os.path.join(package_file, 'current', 'SPECS')).st_mode):
            return SpecStyle.SPEC_STYLE_MASSIVE
    except OSError:
        pass

    try:
        if stat.S_ISDIR(os.stat(os.path.join(package_file, 'SPECS')).st_mode):
            return SpecStyle.SPEC_STYLE_INDIVIDUAL
    except OSError:
        pass

    package = os.path.basename(package_file)
    try:
        if stat.S_ISREG(os.stat(os.path.join(package_file, package + '.spec')).st_mode):
            return SpecStyle.SPEC_STYLE_SPEC_ONLY
    except OSError:
        pass

    return SpecStyle.SPEC_STYLE_UNKNOWN


def get_packagers_mgarepo() -> Dict[str, str]:
    '''Retrieve a dict containing packagers for each package

    This uses the mgarepo command to get the maintdb, but that requires a
    Mageia packager account. Although this function isn't currently used, it's
    still a working alternative in case MAINTDB_URL ever goes away.'''
    packagers = collections.defaultdict(lambda: UNKNOWN_PACKAGER)
    cmd = 'mgarepo maintdb get'
    info("Running: %s", cmd)
    with os.popen(cmd, 'r') as pipe:
        while line := pipe.readline():
            try:
                package, packager = tuple(line.strip().split())
            except ValueError:
                error('Problem getting packager on %s' % line.strip())
            else:
                packagers[package] = packager
        if pipe.close():
            error('Problem retrieving the maintdb')
    return packagers


def get_packagers() -> Dict[str, str]:
    'Retrieve a dict containing packagers for each package'
    packagers = collections.defaultdict(lambda: UNKNOWN_PACKAGER)
    cmd = 'curl -f -s --compressed ' + shlex.quote(MAINTDB_URL)
    info("Running: %s", cmd)
    with os.popen(cmd, 'r') as pipe:
        while line := pipe.readline():
            try:
                package, packager = tuple(line.strip().split())
            except ValueError:
                error('Problem getting packager on %s' % line.strip())
            else:
                packagers[package] = packager
        if pipe.close():
            error('Problem retrieving the maintdb')
    return packagers


def make_spec_path(package_file: str, spec_style: int) -> str:
    '''Creates a file path from the package name and spec tree style.'''
    package = os.path.basename(package_file)
    if spec_style == SpecStyle.SPEC_STYLE_MASSIVE:
        return os.path.join(package_file, 'current', 'SPECS', package + '.spec')
    if spec_style == SpecStyle.SPEC_STYLE_INDIVIDUAL:
        return os.path.join(package_file, 'SPECS', package + '.spec')
    if spec_style == SpecStyle.SPEC_STYLE_SPEC_ONLY:
        return os.path.join(package_file, package + '.spec')
    raise RuntimeError('Unsupported spec style %d' % spec_style)
