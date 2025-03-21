#!/usr/bin/env python3
"""Show packages whose spec files specify an RPM version that does not exist.

Copyright © 2014–2023 Daniel Fandrich.
This program is free software; you can redistribute it and/or modify
Licensed under GNU General Public License 2.0 or later.
Some rights reserved. See COPYING.

Usage: spec-rpm-mismatch >report.html 2>errors.log
 within directory prepared by checkout-all-specs

Todo:
    - fix warnings from .spec files with weird macros calling external programs
"""

from __future__ import annotations

import argparse
import concurrent.futures
import enum
import html.parser
import logging
import os
import re
import shlex
import sys
import textwrap
import time
import urllib.parse
from dataclasses import dataclass
from html import escape, unescape
from logging import debug, error, fatal, info, warning
from typing import Optional, Type, TypeVar

from spectree import spectree


# Parallelize spec parsing with a bit more than the number of available cores
PARALLEL_THREADS = int(1.5 * len(os.sched_getaffinity(0)))

# SRPM_SOURCE_TEMPLATE = 'ftp://distrib-coffee.ipsl.jussieu.fr/pub/linux/Mageia/distrib/{version}/SRPMS/{media}/{section}/'
SRPM_SOURCE_TEMPLATE = 'https://distrib-coffee.ipsl.jussieu.fr/pub/linux/Mageia/distrib/{version}/SRPMS/{media}/{section}/'
SRPM_DISTRO_RELEASE = '10'  # Default distro release number, i.e. the 10 in mga10

# Substituted into the SRPM_SOURCE_TEMPLATE and used in report titles
SRPM_VERSION = 'cauldron'
SRPM_MEDIAS = ['tainted', 'nonfree', 'core']
SRPM_SECTION = 'release'

SVNWEB_URL_TEMPLATE = 'https://svnweb.mageia.org/packages/{version}/{package}/current/SPECS/{package}.spec'

HTML_HEADER = textwrap.dedent("""\
     <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
    <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><head>
    <meta name="GENERATOR" content="spec-rpm-mismatch" />
    <title>Spec Build Report</title>
    <style type="text/css">
    /*<![CDATA[*/
      .release {
        background-color: #e0e0ff;
      }
      .distrib {
        background-color: #ffe0e0;
      }
    /*]]>*/
    </style>
    </head>
    <body>
""")

HTML_FOOTER = textwrap.dedent("""
    </body>
    </html>
""")


PACKAGE_RE = re.compile(r'^(.*)(-[\w\.+~^]+-[\w\.]+\.mga(\d+))(\.\w+)?\.src\.rpm$')


def package_name(rpm: str) -> str:
    """Determine package name from RPM file name."""
    match = PACKAGE_RE.match(rpm)
    if match:
        return match.group(1)
    return ''


def rpm_base_name(rpm: str) -> str:
    """Determine name + version + release from RPM file name."""
    match = PACKAGE_RE.match(rpm)
    if match:
        return match.group(1) + match.group(2)
    return ''


PACKAGE_BASE_RE = re.compile(r'^(.*)(-[\w\.+]+)-([\w\.]+)\.mga(\d+)')


def rpm_versions(rpm_base: str) -> tuple[str, str, str, str]:
    """Determine name, version, release from an RPM base name.

    Return: (name, version, release, distrib)
    """
    match = PACKAGE_BASE_RE.match(rpm_base)
    if match:
        return (match.group(1), match.group(2), match.group(3), match.group(4))
    return ('', '', '', '')


def retrieve_dir_contents(url: str) -> list[str]:
    """Return a directory listing of the remote URL."""
    u = urllib.parse.urlparse(url)
    if u.scheme in ('ftp', 'ftps'):
        return retrieve_dir_contents_curl(url)

    # Starting curl 8.8.0, this method can also handle file: URLs
    if u.scheme in ('http', 'https'):
        return retrieve_dir_contents_http(url)

    if u.scheme == 'file' and u.netloc in ('localhost', ''):
        return os.listdir(u.path)

    raise RuntimeError(f'SRPM URL type {url} not supported')


def retrieve_dir_contents_curl(url: str) -> list[str]:
    """Return a directory listing of the remote ftp URL.

    ftp allows a trivially-parsed directory listing.
    """
    listing = []
    cmd = 'curl -f -s -l --ftp-method SINGLECWD --ssl -- ' + shlex.quote(url)
    info('Running: %s', cmd)
    with os.popen(cmd, 'r') as pipe:
        while line := pipe.readline():
            if line := line.strip():
                listing.append(line)
        if pipe.close():
            error(f'Error retrieving files at %{url}')
    return listing


class HTMLDirParser(html.parser.HTMLParser):
    """Parse the HTML resulting from an HTTP directory request.

    This works with the output from Apache, IIS, lighttpd and nginx. The first
    link in the links attribute is the parent directory.
    Some servers support returning directories in structured formats (e.g., XML
    or JSON) but it seems to be controlled server-side and the client doesn't
    appear to be able to influence it.
    """

    class TableState(enum.IntEnum):
        """States for the HTML parser."""
        NONE = enum.auto()
        TR = enum.auto()
        TH = enum.auto()

    def __init__(self):
        super().__init__()
        self.table_state = self.TableState.NONE
        self.links = []

    def error(self, message: str):
        """Log an error message."""
        warning('%s', message)

    def handle_starttag(self, tag: str, attrs):
        """Called when an HTML tag is started."""
        if tag == 'th':
            self.table_state = self.TableState.TH

        elif tag == 'tr':
            self.table_state = self.TableState.TR

        elif tag == 'a':
            if self.table_state == self.TableState.TH:
                # Ignore links in the table header
                return
            attrdict = dict(attrs)
            href = urllib.parse.unquote(unescape(attrdict['href']))
            # Remove Apache & IIS' special column sorting links
            if not href.startswith('?'):
                self.links.append(href)
        # ignore all other tags


def retrieve_dir_contents_http(url: str) -> list[str]:
    """Return an HTML directory listing via HTTP/S."""
    htmlp = HTMLDirParser()

    cmd = 'curl -f -s --compressed -- ' + shlex.quote(url)
    info('Running: %s', cmd)
    with os.popen(cmd, 'r') as pipe:
        while data := pipe.read(1024):
            htmlp.feed(data)
        if pipe.close():
            error(f'Cannot retrieve file list at %{url}')
    htmlp.close()

    # The first link points to the parent directory which we don't need
    links = htmlp.links[1:]

    # Filter out all other directories
    return [link for link in links if not link.endswith('/') and not link.startswith('?')]


def retrieve_all_packages(srpm_source: str) -> tuple[set[str], dict[str, str]]:
    """Retrieve a list of all packages available in the distribution.

    This could be changed to use the urpmi synthesis files instead.
    """
    all_rpms = set()
    all_packages = {}

    for media in SRPM_MEDIAS:
        url = srpm_source.format(version=SRPM_VERSION, media=media, section=SRPM_SECTION)
        listing = retrieve_dir_contents(url)
        if not listing:
            raise RuntimeError('Error retrieving listing from ' + url)

        rpm_re = re.compile(r'^.*\.rpm$')
        rpms = [f for f in listing if rpm_re.match(f)]
        if not rpms:
            error('Warning: No results from ' + url)

        info('%d packages found in media %s', len(rpms), media)

        for rpm in rpms:
            package = package_name(rpm)
            if not package:
                error('Cannot determine package name for ' + rpm)
                continue
            rpm_base = rpm_base_name(rpm)
            if not rpm_base:
                error('Cannot determine base name for ' + rpm)
                continue
            all_packages[package] = rpm_base
            all_rpms.add(rpm_base)

    return all_rpms, all_packages


def get_srpm_name_stub_from_spec(spec_file: str, release: str) -> str:
    """Determine the start of the SRPM name created by the given spec file.

    This returns a name like 'foo-1.23-4'
    """
    # %dist includes the mgaX version of the current machine by default, which
    # might not match that of release, so construct the version ourselves.
    cmd = f'rpmspec -q -D"dist ."{shlex.quote(release)} --queryformat "%{{NAME}}-%{{VERSION}}-%{{RELEASE}}\\n" -- {shlex.quote(spec_file)}'
    debug('Running: %s', cmd)
    pipe = os.popen(cmd, 'r')
    # There may be many RPMs generated, but the first one is the one with the SRPM
    line = pipe.readline()
    if not line:
        return ''
    _ = pipe.read()  # ignore the rest
    if pipe.close():
        error('Cannot parse spec file %s', spec_file)
        return ''
    return line.strip()


@dataclass
class PackageResult:
    """Base class for the package result."""
    name: str  # bare package name


TypePackageResult = TypeVar('TypePackageResult', bound=PackageResult)


@dataclass
class NoSrpmFile(PackageResult):
    """Packages with no associated SRPM file on the server."""


@dataclass
class ParseError(PackageResult):
    """Packages whose .spec file could not be properly parsed."""


@dataclass
class VersionMatch(PackageResult):
    """Packages whose .spec file matches the SRPM file on the server."""
    srpm_name: str  # versioned name of srpm file


@dataclass
class VersionMismatch(PackageResult):
    """Packages whose .spec file does not match the SRPM file on the server."""
    base_name: str  # versioned name of srpm file on the server
    srpm_name: str  # versioned name of srpm file in the .spec file


class ResultCollection:
    """Class holding the result of all package processing."""
    def __init__(self):
        self.result = []  # type: list[PackageResult]
        self.sorted = True

    def add(self, package: PackageResult):
        """Add a new package to the collection."""
        self.result.append(package)
        self.sorted = False

    def _sort(self):
        self.result.sort(key=lambda x: x.name)
        self.sorted = True

    def has_matching(self, result: Type[TypePackageResult]) -> bool:
        """Returns True if any matching package is found."""
        return any(True for x in self.result if isinstance(x, result))

    def matching(self, result: Type[TypePackageResult]) -> list[TypePackageResult]:
        """Returns list of matching packages in sorted order."""
        if not self.sorted:
            self._sort()
        return [x for x in self.result if isinstance(x, result)]


class PackageProcessor:
    """Class to analyze the versions of packages in .spec files."""

    def __init__(self, all_rpms: set[str], all_packages: dict[str, str], spec_style: int,
                 release: str):
        self.all_rpms = all_rpms
        self.all_packages = all_packages
        self.spec_style = spec_style
        self.release = release
        self.result = ResultCollection()

    def process_package(self, package_file: str):
        """Process the given package.

        This method must be reentrant.
        """
        spec_path = spectree.make_spec_path(package_file, self.spec_style)
        package = os.path.basename(package_file)
        if package not in self.all_packages:
            self.result.add(NoSrpmFile(package))
            return
        srpm_name = get_srpm_name_stub_from_spec(spec_path, self.release)
        if not srpm_name:
            error('Could not determine name stub for %s', spec_path)
            self.result.add(ParseError(package))
            return
        # Some RPMs define distro_section which appends the section to the RPM
        # base name (e.g. lgeneral-1.2.3-3.mga5.nonfree). Strip this off before
        # using it so all names are canonical.
        canon_srpm_name = rpm_base_name(srpm_name + '.src.rpm')
        if not canon_srpm_name:
            error('Could not determine base name for %s.src.rpm', srpm_name)
            self.result.add(ParseError(package))
            return
        if canon_srpm_name not in self.all_rpms:
            self.result.add(VersionMismatch(package, self.all_packages[package], canon_srpm_name))
            return
        self.result.add(VersionMatch(package, canon_srpm_name))

    def print_text_report(self, packagers: dict[str, str]):
        """Print a text report after all packages have been processed."""
        print()
        print('Packages with no associated SRPM file on the server')
        for package in self.result.matching(NoSrpmFile):
            print(packagers[package.name], package.name)

        print()
        print('Could not determine version number from these packages')
        for package in self.result.matching(ParseError):
            print(packagers[package.name], package.name)

        print()
        print('Version missing on server')
        for package in self.result.matching(VersionMismatch):
            print(packagers[package.name], package.name, package.base_name, package.srpm_name)

        print()
        print('Version match on server')
        if len(self.result.matching(VersionMatch)) > 300:
            print(f'{len(self.result.matching(VersionMatch))} spec files have matching RPMs (not shown)')
        else:
            for package in self.result.matching(VersionMatch):
                print(packagers[package.name], package.srpm_name)

    def print_html_report(self, packagers: dict[str, str]):
        """Print an HTML report after all packages have been processed."""
        print(HTML_HEADER)
        print(f'<h1>{SRPM_VERSION} ({self.release}) Spec Build Report '
              f'as of {time.strftime("%Y-%m-%d")}</h1>')

        if self.result.has_matching(NoSrpmFile):
            print('<a href="#no_rpm">Missing RPMs</a><br />')

        print('<a href="#wrong_version">Wrong RPM version</a><br />')

        if self.result.has_matching(ParseError):
            print('<a href="#errors">Spec parsing errors</a><br />')

        if self.result.has_matching(VersionMatch):
            print('<a href="#match_version">Matching RPM versions</a><br />')

        if self.result.has_matching(NoSrpmFile):
            print(textwrap.dedent(f"""
                <a id="no_rpm"></a>
                <h2>Spec files with no matching RPM of any version</h2>

                There is no package SRPM in the {SRPM_VERSION} release matching the associated
                .spec file. This may be because the package was imported but never
                successfully built, or because the package has been obsoleted and
                removed from the distribution but the .spec file was never moved to
                packages/obsolete.
                <p>({len(self.result.matching(NoSrpmFile))} packages)</p>
                <!-- Extract the data in this table in CSV format with the command:
                     xmlstarlet sel -N x=http://www.w3.org/1999/xhtml -t -m '//x:table[@id="norpms"]/x:tr[x:td]' -v 'x:td[2]' -o ',' -v 'x:td[1]' -nl
                -->
                <table id="norpms">
                <tr>
                  <th>Maintainer</th>
                  <th>Package</th>
                </tr>
            """))
            for package in self.result.matching(NoSrpmFile):
                url = SVNWEB_URL_TEMPLATE.format(version=SRPM_VERSION, package=escape(package.name))
                print(textwrap.dedent(f"""
                    <tr>
                      <td>{escape(packagers[package.name])}</td>
                      <td><a href="{url}">{escape(package.name)}</a></td>
                    </tr>
                """))
            print('</table>')

        print(textwrap.dedent(f"""
            <a id="wrong_version"></a>
            <h2>Wrong RPM version</h2>

            The latest version of the SRPM does not match the version in the .spec
            file.  This may be because no-one has submitted the latest version to
            be built, or because the last attempted build failed. This section will
            be very large between the time a distro release is branched and the
            first mass build of the next release version.
            A package may also show up here as a false positive if it was
            changed or built around the same time this report was generated.
            <span class="release">Blue shaded lines</span> are packages with
            equal versions but differ only in the release number.
            <span class="distrib">Red shaded lines</span> are packages that
            haven't been rebuilt since the last distribution release.
            <p>({len(self.result.matching(VersionMismatch))} packages)</p>
            <!-- Extract the data in this table in CSV format with the command:
                 xmlstarlet sel -N x=http://www.w3.org/1999/xhtml -t -m '//x:table[@id="wrongversions"]/x:tr[x:td]' -v 'x:td[2]' -o ',' -v 'x:td[3]' -o ',' -v 'x:td[1]' -nl
            -->
            <table id="wrongversions">
            <tr>
              <th>Maintainer</th>
              <th>RPM version</th>
              <th>Spec version</th>
            </tr>
         """))
        for package in self.result.matching(VersionMismatch):
            _, have_ver, _, have_distrib = rpm_versions(package.base_name)
            _, should_have_ver, _, should_have_distrib = rpm_versions(package.srpm_name)
            match_class = ''
            if have_distrib != should_have_distrib:
                match_class = ' class="distrib"'
            elif have_ver == should_have_ver:
                match_class = ' class="release"'
            url = SVNWEB_URL_TEMPLATE.format(version=SRPM_VERSION, package=escape(package.name))
            print(textwrap.dedent(f"""
                    <tr{match_class}>
                      <td>{escape(packagers[package.name])}</td>
                      <td>{escape(package.base_name)}</td>
                      <td><a href="{url}">{escape(package.srpm_name)}</a></td>
                    </tr>
                """))
        print('</table>')

        if self.result.has_matching(ParseError):
            print(textwrap.dedent(f"""
                <a id="errors"></a>
                <h2>Could not determine version number from these packages</h2>

                This could be due to a syntax error in the .spec file, a missing
                %include file (such files are not normally available to this reporting
                script so this is expected), a missing utility used in command
                substitution (BuildRequires: are not normally available to this
                reporting script so this is expected), a mismatch between the SVN
                directory and the .spec file name, or an internal error in the script
                generating this report.
                <p>({len(self.result.matching(ParseError))} packages)</p>
                <!-- Extract the data in this table in CSV format with the command:
                     xmlstarlet sel -N x=http://www.w3.org/1999/xhtml -t -m '//x:table[@id="noversions"]/x:tr[x:td]' -v 'x:td[1]' -nl
                -->
                <table id="noversions">
                <tr>
                  <th>Package</th>
                </tr>
            """))
            for package in self.result.matching(ParseError):
                url = SVNWEB_URL_TEMPLATE.format(version=SRPM_VERSION, package=escape(package.name))
                print(textwrap.dedent(f"""
                    <tr>
                      <td><a href="{url}">{escape(package.name)}</a></td>
                    </tr>
                """))
            print('</table>')

        if self.result.has_matching(VersionMatch):
            print("""
            <a id="match_version"></a>
            <h2>Spec &amp; RPM versions match</h2>

            The version of the SRPM matches the version in the .spec file. This is
            the desired state, so these are the only packages without error.
            """)
            if len(self.result.matching(VersionMatch)) > 300:
                print(f'<p>{len(self.result.matching(VersionMatch))} spec files have matching RPMs (not shown)</p>')
            else:
                print(textwrap.dedent(f"""
                    <p>({len(self.result.matching(VersionMatch))} packages)</p>
                    <!-- Extract the data in this table in CSV format with the command:
                         xmlstarlet sel -N x=http://www.w3.org/1999/xhtml -t -m '//x:table[@id="matchingversions"]/x:tr[x:td]' -v 'x:td[2]' -o ',' -v 'x:td[1]' -nl
                    -->
                    <table id="matchingversions">
                    <tr>
                      <th>Maintainer</th>
                      <th>Spec/RPM version</th>
                    </tr>
                """))
                for package in self.result.matching(VersionMatch):
                    print(textwrap.dedent(f"""
                        <tr>
                          <td>{escape(packagers[package.name])}</td>
                          <td>{escape(package.srpm_name)}</td>
                        </tr>
                    """))
                print('</table>')

        print(HTML_FOOTER)


def process_packages(proc: PackageProcessor, spec_packages: list[str]):
    """Process the given packages with thread parallelism."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_THREADS) as executor:
        futures = (executor.submit(proc.process_package, package) for package in spec_packages)
        for n, future in enumerate(concurrent.futures.as_completed(futures)):
            if n % 100 == 0:
                # Provide some visual feedback on progress
                info('%d/%d (%d%%)', n, len(spec_packages), 100 * n / len(spec_packages))
            future.result()  # call this so reveal any exceptions


class MgaReleaseTagAction(argparse.Action):
    """Append the option value to "mga" if numeric, otherwise verbatim."""
    def __call__(self, parser, namespace, values, option_string=None):
        """Add a prefix to the release number if missing."""
        setattr(namespace, self.dest, ('mga' if values.isdigit() else '') + values)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point to show packages whose spec files that have no RPM."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')

    parser = argparse.ArgumentParser(
        description='Show packages whose spec files specify an RPM version '
                    'that does not exist.')
    parser.add_argument(
        '-l', '--local_packages', default=spectree.LOCAL_PACKAGE_GLOB,
        help='Glob pointing to local .srpm packages')
    parser.add_argument(
        '-r', '--release', type=str, default='mga' + SRPM_DISTRO_RELEASE,
        action=MgaReleaseTagAction,
        help='Distro release tag in the files in local_packages')
    parser.add_argument(
        '-s', '--srpm_source', type=str, default=SRPM_SOURCE_TEMPLATE,
        help='URL of package source with {version} {media} and {section} replaced.')
    parser.add_argument(
        '-t', '--text_report', action='store_true',
        help='Whether to show a plain text report instead of HTML.')
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Whether to show verbose debug logs.')
    args = parser.parse_args(args=argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    info('Expected distro release: %s', args.release)
    info('Local package specs found in: %s', args.local_packages)
    info('SRPMS found in : %s', args.srpm_source)
    info('Checking version: %s', SRPM_VERSION)
    info('Checking medias: %s', ', '.join(SRPM_MEDIAS))
    info('Checking media section: %s', SRPM_SECTION)

    spec_packages = spectree.get_local_package_paths(args.local_packages)
    if not spec_packages:
        fatal('No package directories found in %s', args.local_packages)
        return 1

    spec_style = spectree.determine_spec_tree_style(args.local_packages)
    info('Spec file checkout style in use is %s',
         spectree.SPEC_STYLE_NAME[spec_style])
    if spec_style == spectree.SpecStyle.SPEC_STYLE_UNKNOWN:
        fatal('Unknown checkout style')
        return 1

    info('%d package directories found', len(spec_packages))

    all_rpms, all_packages = retrieve_all_packages(args.srpm_source)

    info('%d total SRPM packages found on server', len(all_packages))
    if not all_packages:
        fatal('No packages found. Try a different mirror.')
        return 2

    packagers = spectree.get_packagers()
    if not packagers:
        warning('Packager list could not be retrieved. Packagers will not be shown.')
    info('%d packages+packagers known', len(packagers))

    proc = PackageProcessor(all_rpms, all_packages, spec_style, args.release)

    info('Starting check of spec files')
    spec_packages.sort()

    process_packages(proc, spec_packages)

    if args.text_report:
        proc.print_text_report(packagers)
    else:
        proc.print_html_report(packagers)

    info('Report complete')

    return 0


if __name__ == '__main__':
    sys.exit(main())
