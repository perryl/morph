# Copyright (C) 2012-2014  Codethink Limited
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


import unittest

import morphlib


class SourceTests(unittest.TestCase):

    morphology_text = '''
        {
            "name": "foo",
            "kind": "chunk"
        }
    '''

    def setUp(self):
        self.repo_name = 'foo.repo'
        self.original_ref = 'original/ref'
        self.sha1 = 'CAFEF00D'
        self.tree = 'F000000D'
        self.morphology = morphlib.morph2.Morphology(self.morphology_text)
        self.filename = 'foo.morph'
        self.source = morphlib.source.Source(
            self.repo_name, self.original_ref, self.sha1, self.tree,
            self.morphology, self.repo_name, self.original_ref, self.filename)
        self.other = morphlib.source.Source(
            self.repo_name, self.original_ref, self.sha1, self.tree,
            self.morphology, self.repo_name, self.original_ref, self.filename)

    def test_sets_repo_name(self):
        self.assertEqual(self.source.repo_name, self.repo_name)

    def test_sets_repo_to_none_initially(self):
        self.assertEqual(self.source.repo, None)

    def test_sets_original_ref(self):
        self.assertEqual(self.source.original_ref, self.original_ref)

    def test_sets_sha1(self):
        self.assertEqual(self.source.sha1, self.sha1)

    def test_sets_morphology(self):
        self.assertEqual(self.source.morphology, self.morphology)

    def test_sets_filename(self):
        self.assertEqual(self.source.filename, self.filename)
