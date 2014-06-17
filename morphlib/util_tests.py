# Copyright (C) 2011-2014  Codethink Limited
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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import os
import shutil
import tempfile
import unittest

import morphlib


class IndentTests(unittest.TestCase):

    def test_returns_empty_string_for_empty_string(self):
        self.assertEqual(morphlib.util.indent(''), '')

    def test_indents_single_line(self):
        self.assertEqual(morphlib.util.indent('foo'), '    foo')

    def test_obeys_spaces_setting(self):
        self.assertEqual(morphlib.util.indent('foo', spaces=2), '  foo')

    def test_indents_multiple_lines(self):
        self.assertEqual(morphlib.util.indent('foo\nbar\n'),
                         '    foo\n    bar')


class SanitiseMorphologyPathTests(unittest.TestCase):

    def test_appends_morph_to_string(self):
        self.assertEqual(morphlib.util.sanitise_morphology_path('a'),
                         'a.morph')

    def test_returns_morph_when_given_a_filename(self):
        self.assertEqual(morphlib.util.sanitise_morphology_path('a.morph'),
                            'a.morph')

    def test_returns_morph_when_given_a_path(self):
        self.assertEqual('stratum/a.morph',
            morphlib.util.sanitise_morphology_path('stratum/a.morph'))


class MakeConcurrencyTests(unittest.TestCase):

    def test_returns_2_for_1_core(self):
        self.assertEqual(morphlib.util.make_concurrency(cores=1), 2)

    def test_returns_3_for_2_cores(self):
        self.assertEqual(morphlib.util.make_concurrency(cores=2), 3)

    def test_returns_5_for_3_cores(self):
        self.assertEqual(morphlib.util.make_concurrency(cores=3), 5)

    def test_returns_6_for_4_cores(self):
        self.assertEqual(morphlib.util.make_concurrency(cores=4), 6)


class FindParentOfTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tempdir, 'a', 'b', 'c'))
        self.a = os.path.join(self.tempdir, 'a')
        self.b = os.path.join(self.tempdir, 'a', 'b')
        self.c = os.path.join(self.tempdir, 'a', 'b', 'c')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_find_root_finds_starting_directory(self):
        os.mkdir(os.path.join(self.a, '.magic'))
        self.assertEqual(morphlib.util.find_root(self.a, '.magic'), self.a)

    def test_find_root_finds_ancestor(self):
        os.mkdir(os.path.join(self.a, '.magic'))
        self.assertEqual(morphlib.util.find_root(self.c, '.magic'), self.a)

    def test_find_root_returns_none_if_not_found(self):
        self.assertEqual(morphlib.util.find_root(self.c, '.magic'), None)

    def test_find_leaf_finds_starting_directory(self):
        os.mkdir(os.path.join(self.a, '.magic'))
        self.assertEqual(morphlib.util.find_leaf(self.a, '.magic'), self.a)

    def test_find_leaf_finds_child(self):
        os.mkdir(os.path.join(self.c, '.magic'))
        self.assertEqual(morphlib.util.find_leaf(self.a, '.magic'), self.c)

    def test_find_leaf_returns_none_if_not_found(self):
        self.assertEqual(morphlib.util.find_leaf(self.a, '.magic'), None)


class ParseEnvironmentPairsTests(unittest.TestCase):

    def test_parse_environment_pairs_adds_key(self):
        ret = morphlib.util.parse_environment_pairs({}, ["foo=bar"])
        self.assertEqual(ret.get("foo"), "bar")

    def test_parse_environment_does_not_alter_passed_dict(self):
        d = {}
        morphlib.util.parse_environment_pairs(d, ["foo=bar"])
        self.assertTrue("foo" not in d)

    def test_parse_environment_raises_on_duplicates(self):
        self.assertRaises(
            morphlib.util.EnvironmentAlreadySetError,
            morphlib.util.parse_environment_pairs,
            {"foo": "bar"},
            ["foo=bar"])

    def test_sanitize_environment(self):
        d = { 'a': 1 }
        morphlib.util.sanitize_environment(d)
        self.assertTrue(isinstance(d['a'], str))

class IterTrickleTests(unittest.TestCase):

    def test_splits(self):
        self.assertEqual(list(morphlib.util.iter_trickle("foobarbazqux", 3)),
                         [["f", "o", "o"], ["b", "a", "r"],
                          ["b", "a", "z"], ["q", "u", "x"]])

    def test_truncated_final_sequence(self):
        self.assertEqual(list(morphlib.util.iter_trickle("barquux", 3)),
                         [["b", "a", "r"], ["q", "u", "u"], ["x"]])
