# distbuild/serialise_tests.py -- unit tests for Artifact serialisation
#
# Copyright (C) 2012, 2014-2015  Codethink Limited
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


class MockSource(object):

    build_mode = 'staging'
    prefix = '/usr'
    def __init__(self, name, kind):
        self.name = name
        self.repo = None
        self.repo_name = '%s.source.repo_name' % name
        self.original_ref = '%s.source.original_ref' % name
        self.sha1 = '%s.source.sha1' % name
        self.tree = '%s.source.tree' % name
        self.morphology = {'kind': kind}
        self.filename = '%s.source.filename' % name
        self.dependencies = []
        self.cache_id = {
            'blip': '%s.blip' % name,
            'integer': 42,
        }
        self.cache_key = '%s.cache_key' % name
        self.artifacts = {}


class MockArtifact(object):

    arch = 'testarch'

    def __init__(self, name, kind):
        self.source = MockSource(name, kind)
        self.source.artifacts = {name: self}
        self.name = name
        self.dependents = []

    def basename(self):
        return '%s.%s.%s' % (self.source.cache_key,
                             self.source.morphology['kind'],
                             self.name)

    def walk(self): # pragma: no cover
        done = set()
        
        def depth_first(a):
            if a not in done:
                done.add(a)
                for dep in a.source.dependencies:
                    for ret in depth_first(dep):
                        yield ret
                yield a

        return list(depth_first(self))


class SerialisationTests(unittest.TestCase):

    def setUp(self):
        self.art1 = MockArtifact('name1', 'stratum')
        self.art2 = MockArtifact('name2', 'chunk')
        self.art3 = MockArtifact('name3', 'chunk')
        self.art4 = MockArtifact('name4', 'chunk')

    def verify_round_trip(self, artifact):
        encoded = distbuild.serialise_artifact(artifact,
                                               artifact.source.repo_name,
                                               artifact.source.sha1)
        decoded = distbuild.deserialise_artifact(encoded)
        self.assertEqual(artifact.basename(), decoded.basename())
        
        objs = {}
        queue = [decoded]
        while queue:
            obj = queue.pop()
            k = obj.cache_key
            if k in objs:
                self.assertTrue(obj is objs[k])
            else:
                objs[k] = obj
            queue.extend(obj.dependencies)

    def test_returns_string(self):
        encoded = distbuild.serialise_artifact(self.art1,
                                               self.art1.source.repo_name,
                                               self.art1.source.sha1)
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
