# distbuild/crashpoint.py -- user-controlled crashing
#
# Copyright (C) 2014  Codethink Limited
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA..


'''Crash the application.

For crash testing, it's useful to easily induce crashes, to see how the
rest of the system manages. This module implements user-controllable
crashes. The code will be sprinkled with calls to the ``crash_point``
function, which crashes the process if call matches a set of user-defined
criteria.

The criteria consist of:

* a filename
* a function name
* a maximum call count

The criterion is fullfilled if ``crash_point`` is called from the named
function defined in the named file more than the given number of times.
Filename matching is using substrings (a filename pattern ``foo.py``
matches an actual source file path of 
``/usr/lib/python2.7/site-packages/distbuild/foo.py``), but function
names must match exactly. It is not possible to match on class names
(since that information is not available from a traceback).

'''


import logging
import os
import sys
import traceback


detailed_logging = False


def debug(msg): # pragma: no cover
    if detailed_logging:
        logging.debug(msg)


class CrashCondition(object):

    def __init__(self, filename, funcname, max_calls):
        self.filename = filename
        self.funcname = funcname
        self.max_calls = max_calls
        self.called = 0
        
    def matches(self, filename, funcname):
        if self.filename not in filename:
            debug(
                'crashpoint: filename mismatch: %s not in %s' %
                    (repr(self.filename), repr(filename)))
            return False

        if self.funcname != funcname:
            debug(
                'crashpoint: funcname mismatch: %s != %s' %
                    (self.funcname, funcname))
            return False

        debug('crashpoint: matches: %s %s' % (filename, funcname))
        return True
        
    def triggered(self, filename, funcname):
        if self.matches(filename, funcname):
            self.called += 1
            return self.called >= self.max_calls
        else:
            return False


crash_conditions = []


def add_crash_condition(filename, funcname, max_calls):
    crash_conditions.append(CrashCondition(filename, funcname, max_calls))


def add_crash_conditions(strings):
    for s in strings:
        words = s.split(':')
        if len(words) != 3: # pragma: no cover
            logging.error('Ignoring malformed crash condition: %s' % repr(s))
        else:
            add_crash_condition(words[0], words[1], int(words[2]))


def clear_crash_conditions():
    del crash_conditions[:]
    
    
def crash_point(frame=None):
    if frame is None:
        frames = traceback.extract_stack(limit=2)
        frame = frames[0]

    filename, lineno, funcname, text = frame
    
    for condition in crash_conditions:
        if condition.triggered(filename, funcname):
            logging.critical(
                'Crash triggered from %s:%s:%s' % (filename, lineno, funcname))
            sys.exit(255)
        else:
            debug(
                'Crash not triggered by %s:%s:%s' %
                    (filename, lineno, funcname))

