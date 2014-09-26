# distbuild/serialise_tests.py -- unit tests for Artifact serialisation
#
# Copyright (C) 2012, 2014  Codethink Limited
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

import distbuild
import morphlib


class MockMorphology(object):

    def __init__(self, name, kind):
        self.dict = {
            'name': name,
            'kind': kind,
        }
        self.needs_staging_area = None
        self.needs_artifact_metadata_cached = None
        
    def keys(self):
        return self.dict.keys()
        
    def __getitem__(self, key):
        return self.dict[key]


class MockSource(object):

    def __init__(self, name, kind):
        self.name = name
        self.repo = None
        self.repo_name = '%s.source.repo_name' % name
        self.original_ref = '%s.source.original_ref' % name
        self.sha1 = '%s.source.sha1' % name
        self.tree = '%s.source.tree' % name
        self.morphology = MockMorphology(name, kind)
        self.filename = '%s.source.filename' % name
        self.cache_id = {
            'blip': '%s.blip' % name,
            'integer': 42,
        }
        self.cache_key = '%s.cache_key' % name
        self.dependencies = []

        if kind == 'chunk':
            self.build_mode = '%s.source.build_mode' % name
            self.prefix = '%s.source.prefix' % name



def mock_artifact(name, kind):
    source = MockSource(name, kind)
    artifact = morphlib.artifact.Artifact(source, name)
    source.artifacts = {name: artifact}
    return artifact


class SerialisationTests(unittest.TestCase):

    def setUp(self):
        self.art1 = mock_artifact('name1', 'chunk')
        self.art2 = mock_artifact('name2', 'chunk')
        self.art3 = mock_artifact('name3', 'stratum')
        self.art4 = mock_artifact('name4', 'system')

    def assertEqualMorphologies(self, a, b):
        self.assertEqual(sorted(a.keys()), sorted(b.keys()))
        keys = sorted(a.keys())
        a_values = [a[k] for k in keys]
        b_values = [b[k] for k in keys]
        self.assertEqual(a_values, b_values)
        self.assertEqual(a.needs_staging_area, b.needs_staging_area)
        self.assertEqual(a.needs_artifact_metadata_cached, 
                         b.needs_artifact_metadata_cached)
        self.assertEqual(a.needs_staging_area, 
                         b.needs_staging_area)

    def assertEqualSources(self, a, b):
        self.assertEqual(a.repo, b.repo)
        self.assertEqual(a.repo_name, b.repo_name)
        self.assertEqual(a.original_ref, b.original_ref)
        self.assertEqual(a.sha1, b.sha1)
        self.assertEqual(a.tree, b.tree)
        self.assertEqualMorphologies(a.morphology, b.morphology)
        self.assertEqual(a.filename, b.filename)

    def assertEqualArtifacts(self, a, b):
        self.assertEqualSources(a.source, b.source)
        self.assertEqual(a.name, b.name)
        self.assertEqual(a.cache_id, b.cache_id)
        self.assertEqual(a.cache_key, b.cache_key)
        self.assertEqual(len(a.source.dependencies),
                         len(b.source.dependencies))
        for i in range(len(a.source.dependencies)):
            self.assertEqualArtifacts(a.source.dependencies[i],
                                      b.source.dependencies[i])

    def verify_round_trip(self, artifact):
        encoded = distbuild.serialise_artifact(artifact)
        decoded = distbuild.deserialise_artifact(encoded)
        self.assertEqualArtifacts(artifact, decoded)
        
        def key(a):
            return a.cache_key
        
        objs = {}
        queue = [decoded]
        while queue:
            obj = queue.pop()
            k = key(obj)
            if k in objs:
                self.assertTrue(obj is objs[k])
            else:
                objs[k] = obj
            queue.extend(obj.dependencies)

    def test_returns_string(self):
        encoded = distbuild.serialise_artifact(self.art1)
        self.assertEqual(type(encoded), str)

    def test_works_without_dependencies(self):
        self.verify_round_trip(self.art1)

    def test_works_with_single_dependency(self):
        self.art1.source.dependencies = [self.art2]
        self.verify_round_trip(self.art1)

    def test_works_with_two_dependencies(self):
        self.art1.source.dependencies = [self.art2, self.art3]
        self.verify_round_trip(self.art1)

    def test_works_with_two_levels_of_dependencies(self):
        self.art2.source.dependencies = [self.art4]
        self.art1.source.dependencies = [self.art2, self.art3]
        self.verify_round_trip(self.art1)

    def test_works_with_dag(self):
        self.art2.source.dependencies = [self.art4]
        self.art3.source.dependencies = [self.art4]
        self.art1.source.dependencies = [self.art2, self.art3]
        self.verify_round_trip(self.art1)

