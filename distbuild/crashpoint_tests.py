# distbuild/crashpoint_tests.py -- unit tests for crashpoint.py
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


import unittest

import crashpoint


class CrashConditionTests(unittest.TestCase):

    def setUp(self):
        self.c = crashpoint.CrashCondition('bar', 'foofunc', 0)
        
    def test_matches_exact_filename(self):
        self.assertTrue(self.c.matches('bar', 'foofunc'))
    
    def test_matches_basename(self):
        self.assertTrue(self.c.matches('dir/bar', 'foofunc'))
    
    def test_matches_partial_basename(self):
        self.assertTrue(self.c.matches('dir/bar.py', 'foofunc'))
    
    def test_matches_dirname(self):
        self.assertTrue(self.c.matches('bar/something.py', 'foofunc'))
    
    def test_doesnt_match_wrong_function_name(self):
        self.assertFalse(self.c.matches('bar', 'foo'))

    def test_triggered_first_time_with_zero_count(self):
        c = crashpoint.CrashCondition('bar', 'foofunc', 0)
        self.assertTrue(c.triggered('bar', 'foofunc'))

    def test_triggered_first_time_with_zero_count(self):
        c = crashpoint.CrashCondition('bar', 'foofunc', 0)
        self.assertTrue(c.triggered('bar', 'foofunc'))

    def test_triggered_second_time_with_zero_count(self):
        c = crashpoint.CrashCondition('bar', 'foofunc', 0)
        self.assertTrue(c.triggered('bar', 'foofunc'))
        self.assertTrue(c.triggered('bar', 'foofunc'))

    def test_triggered_first_time_with_count_of_one(self):
        c = crashpoint.CrashCondition('bar', 'foofunc', 1)
        self.assertTrue(c.triggered('bar', 'foofunc'))

    def test_triggered_second_time_with_count_of_two(self):
        c = crashpoint.CrashCondition('bar', 'foofunc', 2)
        self.assertFalse(c.triggered('bar', 'foofunc'))
        self.assertTrue(c.triggered('bar', 'foofunc'))

    def test_not_triggered_if_not_matched(self):
        c = crashpoint.CrashCondition('bar', 'foofunc', 0)
        self.assertFalse(c.triggered('bar', 'otherfunc'))


class CrashConditionsListTests(unittest.TestCase):

    def setUp(self):
        crashpoint.clear_crash_conditions()

    def test_no_conditions_initially(self):
        self.assertEqual(crashpoint.crash_conditions, [])

    def test_adds_condition(self):
        crashpoint.add_crash_condition('foo.py', 'bar', 0)
        self.assertEqual(len(crashpoint.crash_conditions), 1)
        c = crashpoint.crash_conditions[0]
        self.assertEqual(c.filename, 'foo.py')
        self.assertEqual(c.funcname, 'bar')
        self.assertEqual(c.max_calls, 0)

    def test_adds_conditions_from_list_of_strings(self):
        crashpoint.add_crash_conditions(['foo.py:bar:0'])
        self.assertEqual(len(crashpoint.crash_conditions), 1)
        c = crashpoint.crash_conditions[0]
        self.assertEqual(c.filename, 'foo.py')
        self.assertEqual(c.funcname, 'bar')
        self.assertEqual(c.max_calls, 0)


class CrashPointTests(unittest.TestCase):

    def setUp(self):
        crashpoint.clear_crash_conditions()
        crashpoint.add_crash_condition('foo.py', 'bar', 0)

    def test_triggers_crash(self):
        self.assertRaises(
            SystemExit,
            crashpoint.crash_point, frame=('foo.py', 123, 'bar', 'text'))

    def test_does_not_trigger_crash(self):
        self.assertEqual(crashpoint.crash_point(), None)

