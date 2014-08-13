# Copyright (C) 2013-2014  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import unittest

import morphlib


class MorphologyTests(unittest.TestCase):

    def setUp(self):
        self.morph = morphlib.morphology.Morphology()

    def test_has_repo_url_attribute(self):
        self.assertEqual(self.morph.repo_url, None)
        self.morph.repo_url = 'foo'
        self.assertEqual(self.morph.repo_url, 'foo')

    def test_has_ref_attribute(self):
        self.assertEqual(self.morph.ref, None)
        self.morph.ref = 'foo'
        self.assertEqual(self.morph.ref, 'foo')

    def test_has_filename_attribute(self):
        self.assertEqual(self.morph.filename, None)
        self.morph.filename = 'foo'
        self.assertEqual(self.morph.filename, 'foo')

    def test_has_dirty_attribute(self):
        self.assertEqual(self.morph.dirty, None)
        self.morph.dirty = True
        self.assertEqual(self.morph.dirty, True)
