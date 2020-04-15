# spec-tree

## Overview

This package contains tools to manage a large set of RPM .spec files, tailored
for the Mageia Linux distribution.  The scripts allow you to check out all the
possible spec files in order to perform large-scale refactoring or changes, to
search all the spec files, or to perform analysis on them.

The spec files are all found within directories under a top directory, one per
package. For example:

    TOP/apackage/apackage.spec
    TOP/coolprogram/coolprogram.spec
    TOP/greatcode/greatcode.spec

This is what you would get when using `mgarepo co -s X` for each packages. Some
scripts also support the standard format which looks like:

    TOP/apackage/SPECS/apackage.spec
    TOP/coolprogram/SPECS/coolprogram.spec
    TOP/greatcode/SPECS/greatcode.spec

## Usage

Populate a new, empty TOP directory like this:

    mkdir TOP
    cd TOP
    checkout-all-specs

To update the spec files later, run this:

    cd TOP
    delete-obsolete-specs
    update-all-specs
    checkout-new-specs

The spec files are checked out anonymously, for speed, which means that you
can't check in a change to a spec file directly. Instead, use the
`commit-from-anon-repo` script like this:

    commit-from-anon-repo -m 'The commit message' TOP/apackage/apackage.spec TOP/greatcode/greatcode.spec

This script operates by temporarily changing the repo URL from an anonymous one
to a SSH one, checking in the file, then changing the URL back. If something
goes wrong during the check-in, this might leave the repo with the SSH URL
which you should manually fix for speed and consistency.

The `list-unclean-repo` script goes through all checked-out directories and
lists those that have local changes that haven't yet been checked-in:

    cd TOP
    list-unclean-repo

`match-spec-maintainer` lists all packages whose spec files match a perl-style
regular expression and lists them along with their maintainer's user ID:

    cd TOP
    match-spec-maintainer 'python2|py2'

`spec-rpm-mismatch` generates a report of packages that have no matching source
RPM available at the specific version. By default, it matches against Cauldron
and hard-codes one Mageia mirror site but it supports a number of options to
change that (run it with `-h` to see them). Run it like this:

    cd TOP
    spec-rpm-mismatch >/tmp/report.html 2>/tmp/errors.log

