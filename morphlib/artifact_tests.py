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


import copy
import unittest

import morphlib


class ArtifactTests(unittest.TestCase):

    def setUp(self):
        morph = morphlib.morph2.Morphology(
            '''
            {
                "name": "chunk",
                "kind": "chunk",
                "chunks": {
                    "chunk-runtime": [
                        "usr/bin",
                        "usr/sbin",
                        "usr/lib",
                        "usr/libexec"
                    ],
                    "chunk-devel": [
                        "usr/include"
                    ]
                }
            }
            ''')
        self.source = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        self.artifact_name = 'chunk-runtime'
        self.artifact = morphlib.artifact.Artifact(
            self.source, self.artifact_name)
        self.other = morphlib.artifact.Artifact(
            self.source, self.artifact_name)

    def test_constructor_sets_source(self):
        self.assertEqual(self.artifact.source, self.source)

    def test_constructor_sets_name(self):
        self.assertEqual(self.artifact.name, self.artifact_name)

    def test_constructor_initializes_cache_key_as_none(self):
        self.assertEqual(self.artifact.cache_key, None)

    def test_sets_dependencies_to_empty(self):
        self.assertEqual(self.artifact.dependencies, [])

    def test_sets_dependents_to_empty(self):
        self.assertEqual(self.artifact.dependents, [])

    def test_does_not_depend_on_other_initially(self):
        self.assertFalse(self.artifact.depends_on(self.other))

    def test_adds_dependency(self):
        self.artifact.add_dependency(self.other)
        self.assertEqual(self.artifact.dependencies, [self.other])
        self.assertEqual(self.other.dependents, [self.artifact])
        self.assertTrue(self.artifact.depends_on(self.other))

    def test_does_not_add_dependency_twice(self):
        self.artifact.add_dependency(self.other)
        self.artifact.add_dependency(self.other)
        self.assertEqual(self.artifact.dependencies, [self.other])
        self.assertEqual(self.other.dependents, [self.artifact])
        self.assertTrue(self.artifact.depends_on(self.other))

    def test_get_dependency_prefix(self):
        self.artifact.add_dependency(self.other)
        self.artifact.source.prefix = '/bar'
        self.other.source = copy.copy(self.artifact.source)
        self.other.source.prefix = '/foo'

        prefix_set = self.artifact.get_dependency_prefix_set()
        self.assertEqual(prefix_set, set(['/foo']))
