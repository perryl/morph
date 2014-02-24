# distbuild/stringbuffer_tests.py -- unit tests
#
# Copyright 2012 Codethink Limited
# All rights reserved.


import unittest

import distbuild


class StringBufferTests(unittest.TestCase):

    def setUp(self):
        self.buf = distbuild.StringBuffer()

    def test_is_empty_initially(self):
        self.assertEqual(self.buf.peek(), '')
        self.assertEqual(len(self.buf), 0)

    def test_adds_a_string(self):
        s = 'foo'
        self.buf.add(s)
        self.assertEqual(self.buf.peek(), s)
        self.assertEqual(len(self.buf), len(s))

    def test_adds_a_second_string(self):
        s = 'foo'
        t = 'bar'
        self.buf.add(s)
        self.buf.add(t)
        self.assertEqual(self.buf.peek(), s + t)
        self.assertEqual(len(self.buf), len(s + t))


class StringBufferRemoveTests(unittest.TestCase):

    def setUp(self):
        self.buf = distbuild.StringBuffer()
        self.first = 'foo'
        self.second = 'bar'
        self.all = self.first + self.second
        self.buf.add(self.first)
        self.buf.add(self.second)

    def test_removes_part_of_first_string(self):
        self.assertTrue(len(self.first) > 1)
        self.buf.remove(1)
        self.assertEqual(self.buf.peek(), self.all[1:])
        self.assertEqual(len(self.buf), len(self.all) - 1)

    def test_removes_all_of_first_string(self):
        self.buf.remove(len(self.first))
        self.assertEqual(self.buf.peek(), self.second)
        self.assertEqual(len(self.buf), len(self.second))

    def test_removes_more_than_first_string(self):
        self.assertTrue(len(self.first) > 1)
        self.assertTrue(len(self.second) > 1)
        self.buf.remove(len(self.first) + 1)
        self.assertEqual(self.buf.peek(), self.second[1:])
        self.assertEqual(len(self.buf), len(self.second) - 1)

    def test_removes_all_strings(self):
        self.buf.remove(len(self.all))
        self.assertEqual(self.buf.peek(), '')
        self.assertEqual(len(self.buf), 0)

    def test_removes_more_than_all_strings(self):
        self.buf.remove(len(self.all) + 1)
        self.assertEqual(self.buf.peek(), '')
        self.assertEqual(len(self.buf), 0)


class StringBufferReadTests(unittest.TestCase):

    def setUp(self):
        self.buf = distbuild.StringBuffer()

    def test_returns_empty_string_for_empty_buffer(self):
        self.assertEqual(self.buf.read(100), '')
        self.assertEqual(self.buf.peek(), '')

    def test_returns_partial_string_for_short_buffer(self):
        self.buf.add('foo')
        self.assertEqual(self.buf.read(100), 'foo')
        self.assertEqual(self.buf.peek(), 'foo')

    def test_returns_catenated_strings(self):
        self.buf.add('foo')
        self.buf.add('bar')
        self.assertEqual(self.buf.read(100), 'foobar')
        self.assertEqual(self.buf.peek(), 'foobar')

    def test_returns_requested_amount_when_available(self):
        self.buf.add('foo')
        self.buf.add('bar')
        self.assertEqual(self.buf.read(4), 'foob')
        self.assertEqual(self.buf.peek(), 'foobar')


class StringBufferReadlineTests(unittest.TestCase):

    def setUp(self):
        self.buf = distbuild.StringBuffer()

    def test_returns_None_on_empty_buffer(self):
        self.assertEqual(self.buf.readline(), None)

    def test_returns_None_on_incomplete_line_in_buffer(self):
        self.buf.add('foo')
        self.assertEqual(self.buf.readline(), None)
        
    def test_extracts_complete_line(self):
        self.buf.add('foo\n')
        self.assertEqual(self.buf.readline(), 'foo\n')
        self.assertEqual(self.buf.peek(), '')

    def test_extracts_only_the_initial_line_and_leaves_rest_of_buffer(self):
        self.buf.add('foo\nbar\n')
        self.assertEqual(self.buf.readline(), 'foo\n')
        self.assertEqual(self.buf.peek(), 'bar\n')

    def test_extracts_only_the_initial_line_and_leaves_partial_line(self):
        self.buf.add('foo\nbar')
        self.assertEqual(self.buf.readline(), 'foo\n')
        self.assertEqual(self.buf.peek(), 'bar')

    def test_extracts_only_the_initial_line_from_multiple_pieces(self):
        self.buf.add('foo\n')
        self.buf.add('bar\n')
        self.assertEqual(self.buf.readline(), 'foo\n')
        self.assertEqual(self.buf.peek(), 'bar\n')

    def test_extracts_only_the_initial_line_from_multiple_pieces_incomp(self):
        self.buf.add('foo\n')
        self.buf.add('bar')
        self.assertEqual(self.buf.readline(), 'foo\n')
        self.assertEqual(self.buf.peek(), 'bar')

