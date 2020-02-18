#!/usr/bin/env python3

# Copyright (c) 2009 Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A super simple linter to checj C syntax."""

from __future__ import print_function
import argparse
import sys


warned = False


def warn(path, line, lineno, msg):
    global warned
    warned = True
    print("%s:%s: %s" % (path, lineno, msg), file=sys.stderr)


def check_line(path, line, idx, lines):
    s = line
    lineno = idx + 1
    eof = lineno == len(lines)
    if s.endswith(' \n'):
        warn(path, line, lineno, "extra space at EOL")
    elif '\t' in line:
        warn(path, line, lineno, "line has a tab")
    elif s.endswith('\r\n'):
        warn(path, line, lineno, "Windows line ending")
    # end of global block, e.g. "}newfunction...":
    elif s == "}\n":
        if not eof:
            nextline = lines[idx + 1]
            # "#" is a pre-processor line
            if nextline != '\n' and nextline.strip()[0] != '#':
                warn(path, line, lineno, "expected 1 blank line")
    # minus initial white spaces
    s = s.lstrip()
    if s.startswith('//') and s[2] != ' ':
        warn(path, line, lineno, "no space after // comment")
    if eof:
        if lines[idx - 1] == '\n':
            warn(path, line, lineno, "blank line at EOF")


def process(path):
    with open(path, 'rt') as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        check_line(path, line, idx, lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', nargs='+', help='path(s) to a file(s)')
    args = parser.parse_args()
    for path in args.paths:
        process(path)
    if warned:
        sys.exit(1)


if __name__ == '__main__':
    main()
