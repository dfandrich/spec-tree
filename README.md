# Spec Tree

## Overview

This package contains tools to manage a large set of RPM .spec files, tailored
for the Mageia Linux distribution.  The scripts allow you to check out all the
possible spec files in order to perform large-scale refactoring or changes, to
search all the spec files, or to perform analysis on them.

The spec files are all found within directories under a top directory, one per
package (the "spec only" style). For example:

    TOP/apackage/apackage.spec
    TOP/coolprogram/coolprogram.spec
    TOP/greatcode/greatcode.spec

This is what you would get when using `mgarepo co -s X` for each package.

All scripts other than `checkout-all-specs` and `update-all-specs` also
support the standard checkout format (a.k.a. "individual packages") which looks
like:

    TOP/apackage/SPECS/apackage.spec
    TOP/coolprogram/SPECS/coolprogram.spec
    TOP/greatcode/SPECS/greatcode.spec

Many scripts also support the "massive checkout" style, which looks like:

    TOP/apackage/current/SPECS/apackage.spec
    TOP/coolprogram/current/SPECS/coolprogram.spec
    TOP/greatcode/current/SPECS/greatcode.spec

## Usage

### checkout-all-specs

Populate a new, empty TOP directory like this:

    mkdir TOP
    cd TOP
    checkout-all-specs

This generates a "spec only" style spec tree.  To make some of the other
scripts easier to use, set the `SPEC_TREE` environment variable to this path.
If you don't do this, you'll need to change to this TOP directory first for the
remaining scripts to work.

This script only supports a "spec only" style tree.

### update-all-specs

To update the spec files later, run this:

    update-all-specs

This will delete obsolete directories, checkout new ones and update existing
ones. To skip the delete and checkout new steps, use the `--update-only`
option. If it seems like there are a lot of directories to delete, the program
will abort, just in case this is due to a bug. To have it delete them anyway,
re-run it with the --max-delete option, giving a number that is at least as
large as the number to delete.

This script works only in a spec tree created by `checkout-all-specs` (the
"spec only" style).

### commit-from-anon-repo

The spec files are checked out by `checkout-all-specs` anonymously, for speed,
which means that you can't check in a change to a spec file directly. Instead,
use the `commit-from-anon-repo` script like this:

    commit-from-anon-repo -m 'The commit message' /path/to/TOP/apackage/apackage.spec /path/to/TOP/greatcode/greatcode.spec

This script operates by temporarily changing the repo URL for the given file
from an anonymous svn one to a SSH one, checking in the file, then changing the
URL back. If something goes wrong during the check-in, this might leave the
repo with the SSH URL which you should manually fix for speed and consistency.
The arguments are designed to come straight from a `grep -l …` command, and
everything in the containing repo will be submitted, not just the given file
alone. If the repo already had an SSH URL, it will be switched to an anonymous
svn one after submission.

Instead of absolute paths to files in the repo, the arguments can be bare repo
names, like this:

    commit-from-anon-repo -m 'The commit message' apackage greatcode

This script does not support a "massive checkout" style tree.

### list-unclean-repo

The `list-unclean-repo` script goes through all checked-out directories and
lists those that have local changes that haven't yet been checked-in:

    list-unclean-repo

This script does not support a "massive checkout" style tree.

### findspec

The `findspec` script searches through all the .spec files in the tree using
a perl-style regex. Command-line arguments are passed through to grep so, for
example, `-l` can be used to list matching files or `-i` can be used to
perform a case-insensitive search:

    findspec -il 'BuildRequires:.*cmake'

### match-spec-maintainer

`match-spec-maintainer` lists all packages whose spec files match a perl-style
regular expression (like `findspec`) and but lists the package names along with
their maintainer's user ID in a tab-separated format:

    match-spec-maintainer 'python2|py2'

### spec-rpm-mismatch

`spec-rpm-mismatch` generates a report of packages that have no matching source
RPM available at the specific version. By default, it matches against Cauldron
and hard-codes one Mageia mirror site but it supports a number of options to
change that (run it with `-h` to see them). Run it like this:

    cd TOP
    spec-rpm-mismatch >/tmp/report.html 2>/tmp/errors.log

## Workflows

`spec-tree` is intended for mass changes to spec files. A typical workflow
might look like this.

1. First, create a spec tree with all spec files using `checkout-all-specs`.
   This only needs to be done once, as afterward you use `update-all-specs` to
   bring them back up-to-date. Set the `SPEC_TREE` environment variable to the
   location of the tree.

2. Next, identify spec files that need to be changed. This can be done with
   `findspec` or whatever other means you have. For example:

    `findspec -l "https://www\.example\.com" >/tmp/files`

3. Change the spec files you've identified as needing updates.  Limit your
   changes so that a single commit message will apply to all of them.  This can
   done with a custom script, or you might be able to do it with a simple
   command like this one, which replaces one string with another in all the
   files identified in the previous step:

    `xargs sed -i 's@https://www\.example\.com@https://www.example.net@g' </tmp/files`

4. Check that the changes were made correctly. You can use `list-unclean-repo`
   to see which repos have changes, and spot-check the changes (by going to a
   few and running `svn diff`) to make sure there weren't any bugs in your
   update scripts.

5. Check in the changes to svn. Write a commit message that is appropriate for
   all changed files. Consider prefixing it with `SILENT:` if the change
   wouldn't be interesting to the end-user, which will be the case for many of
   the mechanical kinds of changes spec-tree is designed to handle. Submit them
   like this:

    `xargs commit-from-anon-repo -m 'Change URL domain example.com to example.net' </tmp/files`

6. Once the submission is complete, make sure all repos were submitted without
   error by ensuring there is no output when running:

    `list-unclean-repo`

## Author

Daniel Fandrich <dan@coneharvesters.com>

See more info at the
[project home page](https://github.com/dfandrich/spec-tree/).

This program is Copyright © 2014–2022 Daniel Fandrich. It is distributed under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version. See [COPYING](COPYING) for details.
