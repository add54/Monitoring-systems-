#!/usr/bin/env python

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Unit test runner, providing colourized output.
"""

import os
import sys
import unittest
from unittest import TestResult
from unittest import TextTestResult
from unittest import TextTestRunner

import psutil
from psutil.tests import TOX


HERE = os.path.abspath(os.path.dirname(__file__))
VERBOSITY = 1 if TOX else 2
GREEN = 1
RED = 2
BROWN = 94


def term_supports_colors(file=sys.stdout):
    try:
        import curses
        assert file.isatty()
        curses.setupterm()
        assert curses.tigetnum("colors") > 0
    except Exception:
        return False
    else:
        return True


def hilite(s, color, bold=False):
    """Return an highlighted version of 'string'."""
    attr = []
    if color == GREEN:
        attr.append('32')
    elif color == RED:
        attr.append('91')
    elif color == BROWN:
        attr.append('33')
    else:
        raise ValueError("unrecognized color")
    if bold:
        attr.append('1')
    return '\x1b[%sm%s\x1b[0m' % (';'.join(attr), s)


class ColouredResult(unittest.TextTestResult):

    def addSuccess(self, test):
        TestResult.addSuccess(self, test)
        self.stream.writeln(hilite("OK", GREEN))

    def addError(self, test, err):
        TestResult.addError(self, test, err)
        self.stream.writeln(hilite("ERROR", RED, bold=True))

    def addFailure(self, test, err):
        TestResult.addFailure(self, test, err)
        self.stream.writeln(hilite("FAIL", RED))

    def addSkip(self, test, reason):
        TestResult.addSkip(self, test, reason)
        self.stream.writeln(hilite("skipped: %s" % reason, BROWN))

    def printErrorList(self, flavour, errors):
        flavour = hilite(flavour, RED)
        TextTestResult.printErrorList(self, flavour, errors)


class ColouredRunner(TextTestRunner):
    resultclass = ColouredResult if term_supports_colors() else TextTestResult


def setup_tests():
    if 'PSUTIL_TESTING' not in os.environ:
        # This won't work on Windows but set_testing() below will do it.
        os.environ['PSUTIL_TESTING'] = '1'
    psutil._psplatform.cext.set_testing()


def get_suite():
    testmods = [os.path.splitext(x)[0] for x in os.listdir(HERE)
                if x.endswith('.py') and x.startswith('test_') and not
                x.startswith('test_memory_leaks')]
    if "WHEELHOUSE_UPLOADER_USERNAME" in os.environ:
        testmods = [x for x in testmods if not x.endswith((
                    "osx", "posix", "linux"))]
    suite = unittest.TestSuite()
    for tm in testmods:
        # ...so that the full test paths are printed on screen
        tm = "psutil.tests.%s" % tm
        suite.addTest(unittest.defaultTestLoader.loadTestsFromName(tm))
    return suite


def run_test_module_by_name(name):
    # testmodules = [os.path.splitext(x)[0] for x in os.listdir(HERE)
    #                if x.endswith('.py') and x.startswith('test_')]
    setup_tests()
    name = os.path.splitext(os.path.basename(name))[0]
    suite = unittest.TestSuite()
    suite.addTest(unittest.defaultTestLoader.loadTestsFromName(name))
    result = ColouredRunner(verbosity=VERBOSITY).run(suite)
    success = result.wasSuccessful()
    sys.exit(0 if success else 1)


def run_suite():
    setup_tests()
    result = ColouredRunner(verbosity=VERBOSITY).run(get_suite())
    success = result.wasSuccessful()
    sys.exit(0 if success else 1)
