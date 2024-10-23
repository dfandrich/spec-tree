#!/usr/bin/env python3
"""Check URLs in spec files.

Copyright © 2023 Daniel Fandrich.
This program is free software; you can redistribute it and/or modify
Licensed under GNU General Public License 2.0 or later.
Some rights reserved. See COPYING.

Usage: bad-url-report >report.html 2>errors.log
 within directory prepared by checkout-all-specs

Todo:
- check http: links and see if the corresponding https: one works
- maybe do a recheck of TIMEOUT and BAD_HOST error URLs as well in case they're also temporary
"""

from __future__ import annotations

import argparse
import concurrent.futures
import enum
import logging
import os
import re
import shlex
import sys
import textwrap
import time
from dataclasses import dataclass
from html import escape
from logging import debug, error, fatal, info, warning
from typing import Callable, Iterable, Optional
from urllib.parse import quote

from spectree import spectree


# Match what looks like an actual URL
URL_MATCH_RE = re.compile(r'([-+.a-zA-Z0-9]+)://')

# Parallelize spec parsing with a bit more than the number of available cores
PARALLEL_SPEC_THREADS = int(1.5 * len(os.sched_getaffinity(0)))

# Massively parallelize URL checking since this is normally bandwidth limited,
# not CPU limited. But, keep this low enough so that servers don't throttle us,
# especially SourceForge.
PARALLEL_URL_THREADS = 5

# Maximum number of URLs to check at a time. This is to improve efficiency by
# checking several URLs in the same OS process and reusing the network
# connection when possible.
URL_BATCHES = 20

# Smallest batch size, used when the number of URLs to check is low. A minimum
# larger than 1 can actually be faster since less connection setup needs to be
# done when several URLs are checked on the same host.
URL_BATCHES_MIN = 3

# Time in seconds to wait for each individual URL
# An unfortunate situation results if this is >7, since SourceForge seems to
# kill a connection at 7.6 seconds without responding, making it look to the
# heuristics like a DNS failure.
URL_TIMEOUT = 7

# Time in seconds to wait for each URL when redirects are followed
URL_TIMEOUT_REDIRECT = 25

HTML_HEADER = textwrap.dedent("""\
     <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
    <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><head>
    <meta name="GENERATOR" content="spec-url-check" />
    <title>Spec URL Report</title>
    <style type="text/css">
    /*<![CDATA[*/
      .shaded {
        background-color: #f0f0f0;
      }
      .nowrap {
        min-width: 1%;
        white-space: nowrap;
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


class UrlType(enum.IntEnum):
    """What the URL is used for in the spec file."""
    URL = enum.auto()
    SOURCE = enum.auto()
    PATCH = enum.auto()


URL_TYPE_NAME = {
    UrlType.URL: 'URL',
    UrlType.SOURCE: 'Source',
    UrlType.PATCH: 'Patch'
}


class UrlStatus(enum.IntEnum):
    """Whether the URL works."""
    UNCHECKED = enum.auto()        # URL has not yet been checked
    UNSUPPORTED = enum.auto()      # scheme is not supported
    VALID = enum.auto()            # URL is A-OK
    REDIRECT = enum.auto()         # URL was redirected elsewhere & not checked
    BAD_HOST = enum.auto()         # host does not exist
    BAD_CERTIFICATE = enum.auto()  # encryption certificate is not valid
    NOT_FOUND = enum.auto()        # 404 not found (or similar)
    AUTHENTICATE = enum.auto()     # requires authentication
    TIMEOUT = enum.auto()          # request timed out
    TEMPORARY_ERR = enum.auto()    # temporary error; try again later


URL_STATUS_NAME = {
    UrlStatus.UNCHECKED: 'Unknown processing Error',
    UrlStatus.UNSUPPORTED: 'Unsupported URL',
    UrlStatus.VALID: 'Valid',
    UrlStatus.REDIRECT: 'Redirected',
    UrlStatus.BAD_HOST: 'Host name does not exist',
    UrlStatus.BAD_CERTIFICATE: 'TLS certificate problem',
    UrlStatus.NOT_FOUND: 'File not found',
    UrlStatus.AUTHENTICATE: 'URL requires authentication',
    UrlStatus.TIMEOUT: 'Request timed out',
    UrlStatus.TEMPORARY_ERR: 'Temporary server error'
}


@dataclass
class UrlResult:
    """Base class for the package result."""
    name: str          # bare package name
    use: UrlType       # what the URL is for
    url: str           # syntactically-valid URL
    status: UrlStatus  # whether the URL works or not


def get_urls_from_spec(spec_file: str) -> set[str]:
    """Extracts the URL: fields defined in the given spec file.

    This returns zero or more syntactically-valid URLs in a set which de-dupes
    them.
    """
    cmd = f'rpmspec -q --queryformat "%{{URL}}\\n" -- {shlex.quote(spec_file)}'
    debug('Running: %s', cmd)
    urls = set()
    with os.popen(cmd, 'r') as pipe:
        # There is one URL generated per package type
        while line := pipe.readline():
            # rpmspec returns (none) if no Url: line is found
            if (url := line.strip()) and url != '(none)':
                if URL_MATCH_RE.match(url):
                    urls.add(url)
                else:
                    warning(f'Not a valid URL in spec file; skipping: {url}')
        if pipe.close():
            error('Cannot parse spec file %s', spec_file)
    return urls


def get_sources_from_spec(spec_file: str) -> tuple[set[str], set[str]]:
    """Extracts the SourceN: and PatchN: lines defined in the given spec file.

    This returns a tuple with a set of syntactically-valid source URLs and a
    set of syntactically-valid patch URLs.
    """
    cmd = f'spectool -- {shlex.quote(spec_file)}'
    debug('Running: %s', cmd)
    sources = set()
    patches = set()
    with os.popen(cmd, 'r') as pipe:
        # There is one URL generated per package type
        while line := pipe.readline():
            key, url = line.strip().split(maxsplit=1)
            if key.lower().startswith('source'):
                if URL_MATCH_RE.match(url):
                    sources.add(url)
            elif key.lower().startswith('patch'):
                if URL_MATCH_RE.match(url):
                    patches.add(url)
            else:
                info('Not a source or patch type: %s', key)
        if pipe.close():
            error('Cannot parse spec file %s', spec_file)
    return (sources, patches)


class PackageProcessor:
    """Class to check the URLs in .spec files."""

    def __init__(self, spec_style: int):
        self.spec_style = spec_style
        self.result = []  # type: list[UrlResult]

    def process_package(self, package_file: str):
        """Process the spec files to extract URLs.

        This method must be thread safe.
        """
        spec_path = spectree.make_spec_path(package_file, self.spec_style)
        urls = get_urls_from_spec(spec_path)
        for url in urls:
            self.result.append(UrlResult(package_file, UrlType.URL, url, UrlStatus.UNCHECKED))

        sources, patches = get_sources_from_spec(spec_path)
        for url in sources:
            self.result.append(UrlResult(package_file, UrlType.SOURCE, url, UrlStatus.UNCHECKED))
        for url in patches:
            self.result.append(UrlResult(package_file, UrlType.PATCH, url, UrlStatus.UNCHECKED))

    def update_url_status(self, statuses: dict[str, UrlStatus]):
        """Update each url result with its status."""
        for entry in self.result:
            if entry.url in statuses:
                entry.status = statuses[entry.url]
            else:
                if entry.url[-1] != '/' and entry.url + '/' in statuses:
                    # The URL was probably rewritten with a trailing slash, but
                    # was checked in a batch alongside the slash version so it
                    # wasn't corrected there. Assume this is what happened and
                    # use the non-slash status.
                    entry.status = statuses[entry.url + '/']

                else:
                    # If the URL is not in the list, it means it's unsupported
                    entry.status = UrlStatus.UNSUPPORTED

    def print_text_report(self, packagers: dict[str, str]):
        """Print a text report after all URLs have been processed."""
        # Sort on name, use, url
        self.result.sort(key=lambda x: f'{x.name}|{int(x.use)}|{x.url}')
        # The text report just dumps everything for all URLs
        for specurl in self.result:
            print(packagers[specurl.name], specurl.name, specurl.use, specurl.status, specurl.url)

    def print_html_report(self, packagers: dict[str, str]):
        """Print a HTML report after all URLs have been processed."""
        # Sort on name, use, url
        self.result.sort(key=lambda x: f'{x.name}|{int(x.use)}|{x.url}')
        print(HTML_HEADER)
        print(f'<h1>Spec URL Check Report as of {time.strftime("%Y-%m-%d")}</h1>')
        print(textwrap.dedent(f"""
            {len(self.result)} URLs were checked<br />
            {len([x for x in self.result
                    if x.status != UrlStatus.VALID])} URLs were bad<br />
            {len([x for x in self.result
                    if URL_MATCH_RE.match(x.url).group(1).lower()
                       not in ('https', 'ftps')])} URLs were insecure<br />"""))

        print(textwrap.dedent("""
            <br />
            <a href="#bad_urls">Bad URLs</a><br />
            <a href="#insecure_urls">Insecure URLs</a><br />"""))

        # Build a hash table of project URLs for quick access
        home_pages = {entry.name: entry.url for entry in self.result if entry.use == UrlType.URL}

        print(textwrap.dedent(r"""
            <a id="bad_urls"></a>
            <h2>Spec files with bad URLs</h2>
            <!-- Extract the data in this table in CSV format with the command:
                 xmlstarlet sel -N x=http://www.w3.org/1999/xhtml -t -m '//x:table[@id="badurls"]/x:tr[x:td]' -v 'x:td[1]' -o ',' -v 'x:td[2]' -o ',' -v 'x:td[3]' -o ',' -v 'x:td[4]' -o ',' -v 'x:td[6]' -nl
            -->
            <table id="badurls" summary="Package URLs that were determined to be bad in some way along with ownership, use and additional information.">
                <tr>
                  <th title="The registered maintainer of the package" class="shaded nowrap">Maintainer</th>
                  <th title="The package spec name" class="nowrap">Package</th>
                  <th title="Whether the URL was used for the package home page, a source or a patch" class="shaded nowrap">URL Use</th>
                  <th title="What went wrong when checking the URL" class="nowrap">Error</th>
                  <th title="Links to information sources regarding this package" class="shaded nowrap">Info</th>
                  <th title="The URL that was checked">URL</th>
                </tr>"""))

        for specurl in self.result:

            if specurl.status == UrlStatus.VALID:
                continue

            https_link = (f'<a href="https{escape(specurl.url[specurl.url.find(":"):])}">https</a>'
                          if URL_MATCH_RE.match(specurl.url).group(1).lower() != 'https' else '')

            project_link = (f'<a href="{escape(home_pages[specurl.name])}">home</a>'
                            if specurl.use != UrlType.URL and specurl.name in home_pages else '')

            print(textwrap.dedent(f"""
                <tr>
                  <td class="shaded nowrap">{escape(packagers[specurl.name])}</td>
                  <td class="nowrap">{escape(specurl.name)}</td>
                  <td class="shaded nowrap">{URL_TYPE_NAME[specurl.use]}</td>
                  <td class="nowrap">{URL_STATUS_NAME[specurl.status]}</td>
                  <td class="shaded nowrap">
                      <a href="https://svnweb.mageia.org/packages/cauldron/{quote(specurl.name)}/current/SPECS/{quote(specurl.name)}.spec?view=markup">SVN</a>
                      <a href="https://release-monitoring.org/projects/search/?pattern={quote(specurl.name)}">RM</a>
                      <a href="https://directory.fsf.org/wiki?search={quote(specurl.name)}">FSD</a>
                      <a href="https://web.archive.org/web/*/{escape(specurl.url)}">Arc</a>
                      {project_link}
                      {https_link}
                  </td>
                  <td><a href="{escape(specurl.url)}">{escape(specurl.url)}</a></td>
                </tr>"""))
        print('</table>')

        print(textwrap.dedent(r"""
            <a id="insecure_urls"></a>
            <h2>Spec files with insecure URLs</h2>
            <!-- Extract the data in this table in CSV format with the command:
                 xmlstarlet sel -N x=http://www.w3.org/1999/xhtml -t -m '//x:table[@id="insecureurls"]/x:tr[x:td]' -v 'x:td[1]' -o ',' -v 'x:td[2]' -o ',' -v 'x:td[3]' -o ',' -v 'x:td[5]' -nl
            -->
            <table id="insecureurls" summary="Package URLs that point to unencrypted resources.">
                <tr>
                  <th title="The registered maintainer of the package" class="shaded nowrap">Maintainer</th>
                  <th title="The package spec name" class="nowrap">Package</th>
                  <th title="Whether the URL was used for the package home page, a source or a patch" class="shaded nowrap">URL Use</th>
                  <th title="Links to information sources regarding this package" class="shaded nowrap">Info</th>
                  <th title="The URL in question">URL</th>
                </tr>"""))

        for specurl in self.result:

            if URL_MATCH_RE.match(specurl.url).group(1).lower() in frozenset(('https', 'ftps')):
                continue

            project_link = (f'<a href="{escape(home_pages[specurl.name])}">home</a>'
                            if specurl.use != UrlType.URL and specurl.name in home_pages else '')

            print(textwrap.dedent(f"""
                <tr>
                  <td class="shaded nowrap">{escape(packagers[specurl.name])}</td>
                  <td class="nowrap">{escape(specurl.name)}</td>
                  <td class="shaded nowrap">{URL_TYPE_NAME[specurl.use]}</td>
                  <td class="shaded nowrap">
                    {project_link}
                    <a href="https{escape(specurl.url[specurl.url.find(":"):])}">https</a>
                  </td>
                  <td><a href="{escape(specurl.url)}">{escape(specurl.url)}</a></td>
                </tr>"""))
        print('</table>')

        print(HTML_FOOTER)


def process_packages(proc: PackageProcessor, spec_packages: list[str]):
    """Process the given packages with thread parallelism."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_SPEC_THREADS) as executor:
        futures = (executor.submit(proc.process_package, package) for package in spec_packages)
        for n, future in enumerate(concurrent.futures.as_completed(futures)):
            if n % 100 == 0:
                # Provide some visual feedback on progress
                info('%d/%d (%d%%)', n, len(spec_packages), 100 * n / len(spec_packages))
            future.result()  # call this to reveal any exceptions


def process_urls(checker: Callable, batches: list[set[str]],
                 redirect: bool) -> dict[str, UrlStatus]:
    """Process the given packages in batches with thread parallelism."""
    total_urls = sum(len(b) for b in batches)
    url_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_URL_THREADS) as executor:
        futures = (executor.submit(checker, package, redirect) for package in batches)
        for n, future in enumerate(concurrent.futures.as_completed(futures)):
            result = future.result()  # call this to reveal any exceptions
            # TODO: for Python>=3.9 use | syntax to merge dicts
            url_results = {**url_results, **result}
            if n % 4 == 0:
                # Provide some visual feedback on progress
                info('%d/%d (%d%%)', len(url_results), total_urls, 100 * len(url_results) / total_urls)
    return url_results


def status_from_response_code(response_code: int, url: str) -> UrlStatus:
    """Return a URL status give the URL and response code.

    Response codes for different URL schemes use different namespaces, and
    they're sorted out here.
    """
    scheme = URL_MATCH_RE.match(url).group(1).lower()
    if scheme in frozenset(('http', 'https')):
        if 200 <= response_code < 300:
            return UrlStatus.VALID
        if response_code in frozenset((423, 429)):
            # Rate limiting response
            return UrlStatus.TEMPORARY_ERR
        if response_code in frozenset((401, 402, 403)):
            return UrlStatus.AUTHENTICATE
        if 300 <= response_code < 400:
            return UrlStatus.REDIRECT
        if 400 <= response_code < 500:
            return UrlStatus.NOT_FOUND
        if 500 <= response_code < 600:
            return UrlStatus.TEMPORARY_ERR
        error('Unknown HTTP error reason for %s', url)
    elif scheme in frozenset(('ftp', 'ftps')):
        if response_code in frozenset((250, 257, 350)):
            return UrlStatus.VALID
        if response_code in frozenset((530, 430)):
            return UrlStatus.AUTHENTICATE
        if response_code in frozenset((221, 230)):
            # These can happen if the connection is terminated
            # by timeout before the end
            return UrlStatus.TEMPORARY_ERR
        if 400 <= response_code < 500:
            return UrlStatus.TEMPORARY_ERR
        if 500 <= response_code < 600:
            return UrlStatus.NOT_FOUND
        error('Unknown FTP error reason for %s', url)
    return UrlStatus.UNSUPPORTED


def get_curl_timeout_factor() -> int:
    """Determine what units curl returns for timeouts."""
    cmd = 'curl -V'
    with os.popen(cmd, 'r') as pipe:
        line = pipe.readline()
        if line:
            parts = line.split(maxsplit=3)
            if len(parts) >= 2 and parts[1] == '7.74.0':
                # This version of curl had a bug that returned microseconds
                # instead of seconds
                return 1
    return 1000000


def check_url_batch(batch: set[str], redirect: bool) -> dict[str, UrlStatus]:
    """Check a batch of URLs.

    redirect - True to follow redirects

    This must be thread safe.
    """
    results = {}
    debug(f'checking batch of {len(batch)} URLs')

    # We must order the URLs so we can associate the results with the original
    # URL since they aren't available in unmodified form from curl
    urls = list(batch)
    urls.sort()

    timeout = URL_TIMEOUT_REDIRECT if redirect else URL_TIMEOUT
    timeout_factor = get_curl_timeout_factor()

    # Can't use --parallel here because the output lines from several URLs
    # can (probably) get interleaved, and we can't associate the ordered
    # results with the original URL. Parallelism is done at a higher level,
    # using threads instead.
    # The ||true at the end guarantees a 0 exit code, even if some URLs failed.
    # url_effective is only used for debugging
    cmd = ('curl --ssl -s --ftp-method singlecwd '
           f"-m {timeout} -I {'-L --max-redirs 10' if redirect else ''} "
           '--write-out "%{response_code} %{ssl_verify_result} %{time_connect} '
           '%{time_total} %{num_connects} %{url_effective}\\n" '
           f"-o /dev/null {' -o /dev/null '.join(shlex.quote(url) for url in urls)} "
           '|| true')
    debug('Running: %s', cmd)
    with os.popen(cmd, 'r') as pipe:
        while line := pipe.readline():
            debug('RESULTS: %s', line.strip())
            # curl 7.74.0 returned microseconds instead of seconds.
            # This will need to be updated to work on that version.
            response_code, ssl_verify_result, time_connect, time_total, num_connects, _ = line.strip().split(maxsplit=5)
            response_code, ssl_verify_result, time_connect, time_total, num_connects = (
                int(response_code), int(ssl_verify_result), int(float(time_connect) * timeout_factor), int(float(time_total) * timeout_factor), int(num_connects))
            # Get the URL corresponding to this result
            url = urls.pop(0)

            # We don't get the CURLcode result, so we need to infer the
            # reason based on some other codes. That sometimes goes wrong
            # (especially when handling redirects) but it's still going to show
            # an error of some sort.
            # TODO: This is fixed in curl 7.75.0 with the addition of %{exitcode}
            status = UrlStatus.UNSUPPORTED
            if time_total >= timeout * 1000000 * 0.99:
                # Total time is no more than 1% less than the timeout
                # This trumps everything else, because we can't trust the
                # codes if curl aborts in the middle of a transfer
                status = UrlStatus.TIMEOUT
            elif ssl_verify_result:
                status = UrlStatus.BAD_CERTIFICATE
            elif response_code == 0:
                if time_connect == 0 and num_connects == 0:
                    # This is just a guess
                    status = UrlStatus.BAD_HOST
                else:
                    error('Unknown error reason for %s', url)
            else:
                status = status_from_response_code(response_code, url)

            results[url] = status

        if pipe.close():
            error('Cannot check URL batch')

    return results


def check_urls(urls: Iterable[str], redirect: bool = False) -> dict[str, UrlStatus]:
    """Check each URL to see if it's valid.

    redirect - True to follow redirects

    Do this in parallel for speed.
    """
    all_urls = []
    for url in urls:
        if not (m := URL_MATCH_RE.match(url)):
            warning(f'Not a valid URL; skipping: {url}')
            # Not an actual URL; skip it & drop it from the results
            continue
        if m.group(1).lower() not in frozenset(
                ('http', 'https', 'ftp', 'ftps')):
            warning(f'Not a supported URL; skipping: {url}')
            # Unsupported URL; skip it & drop it from the results
            continue
        all_urls.append(url)
    del urls

    # Set the batch size to correspond to the number of URLs and threads
    batch_size = (URL_BATCHES if len(all_urls) >= URL_BATCHES * PARALLEL_URL_THREADS
                  else max(int(len(all_urls) / PARALLEL_URL_THREADS), URL_BATCHES_MIN))

    # Sorting provides the nice property that requests to the same server
    # would be batched together and could take advantage of a persistent
    # network connection to the same server. Unfortunately, some servers (e.g.
    # github.com and sourceforge.net) are in thousands of URLs and start
    # throwing rate-limiting 429 responses after too many requests in a row
    # (too many looks like about 70 for sourceforge.net and 700 for
    # github.com). By not sorting, we rely on the pseudo-random ordering that
    # a set provides which should distribute requests from many servers into
    # a batch and slow down the number of requests to any given server. If the
    # number of requests is small, sort anyway because it won't make any real
    # difference to the rate of requests.
    if len(all_urls) < 100:
        all_urls.sort()

    batches = []
    while all_urls:
        batch = set()
        for _ in range(batch_size):
            if not all_urls:
                break
            batch.add(all_urls.pop(0))
        batches.append(batch)

    return process_urls(check_url_batch, batches, redirect)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point to check URLs in spec files."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')

    parser = argparse.ArgumentParser(
        description='Show bad URLs mentioned in packages')
    parser.add_argument(
        '-l', '--local_packages', default=spectree.LOCAL_PACKAGE_GLOB,
        help='Glob pointing to local .srpm packages')
    parser.add_argument(
        '-c', '--skip_url_check', action='store_true',
        help="Don't actually check the URLs")
    parser.add_argument(
        '-t', '--text_report', action='store_true',
        help='Whether to show a plain text report instead of HTML.')
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Whether to show verbose debug logs.')
    args = parser.parse_args(args=argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    info('Local package specs found in: %s', args.local_packages)

    spec_packages = spectree.get_local_package_paths(args.local_packages)
    if not spec_packages:
        fatal('No package directories found in %s', args.local_packages)
        return 1

    spec_style = spectree.determine_spec_tree_style(args.local_packages)
    info('Spec file checkout style in use is %s', spectree.SPEC_STYLE_NAME[spec_style])
    if spec_style == spectree.SpecStyle.SPEC_STYLE_UNKNOWN:
        fatal('Unknown checkout style')
        return 1

    info('%d package directories found', len(spec_packages))

    packagers = spectree.get_packagers()
    if not packagers:
        warning('Packager list could not be retrieved. Packagers will not be shown.')
    info('%d packages+packagers known', len(packagers))

    proc = PackageProcessor(spec_style)

    info('Starting reading of spec files')
    spec_packages.sort()
    process_packages(proc, spec_packages)

    # First, all unique URLs to be checked are checked, then some rechecks are
    # done. When completely done, update the status of all the URLs attached to
    # the packages.

    if not args.skip_url_check:
        info('Starting checking %d URLs', len(proc.result))
        # De-dupe the URLs then check them all
        checked_urls = check_urls({entry.url for entry in proc.result})

        # Check REDIRECT entries again, but redirecting this time.
        recheck_urls = {u for u, s in checked_urls.items() if s == UrlStatus.REDIRECT}
        if recheck_urls:
            info('Starting checking %d redirected URLs', len(recheck_urls))
            rechecked_urls = check_urls(recheck_urls, redirect=True)
            checked_urls = {**checked_urls, **rechecked_urls}

        # Check TEMPORARY_ERR entries again.
        recheck_urls = {u for u, s in checked_urls.items() if s == UrlStatus.TEMPORARY_ERR}
        if recheck_urls:
            info('Starting rechecking %d temporary error URLs', len(recheck_urls))
            rechecked_urls = check_urls(recheck_urls, redirect=True)
            checked_urls = {**checked_urls, **rechecked_urls}

        # Update the status of all the original URLs with what was discovered
        proc.update_url_status(checked_urls)
    else:
        info('Skipping checking of URLs')

    if args.text_report:
        proc.print_text_report(packagers)
    else:
        proc.print_html_report(packagers)

    info('Report complete')
    return 0


if __name__ == '__main__':
    sys.exit(main())
