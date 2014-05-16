# distbuild/serialise_tests.py -- unit tests for Artifact serialisation
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
import json
import yaml

import morphlib
import distbuild

# TODO: these were taken from artifactresolver_tests
# they should be moved to a more sensible place so both tests
# can share these classes
class FakeChunkMorphology(morphlib.morph2.Morphology):

    def __init__(self, name, artifact_names=[]):
        assert(isinstance(artifact_names, list))

        if artifact_names:
            # fake a list of artifacts
            artifacts = []
            for artifact_name in artifact_names:
                artifacts.append({'artifact': artifact_name,
                                  'include': artifact_name})
            text = json.dumps({
                        "name": name,
                        "kind": "chunk",
                        "products": artifacts
                    })
            self.builds_artifacts = artifact_names
        else:
            text = ('''
                    {
                        "name": "%s",
                        "kind": "chunk"
                    }
                    ''' % name)
            self.builds_artifacts = [name]
        morphlib.morph2.Morphology.__init__(self, text)
        self.needs_artifact_metadata_cached = True


class FakeStratumMorphology(morphlib.morph2.Morphology):

    def __init__(self, name, chunks=[], build_depends=[]):
        assert(isinstance(chunks, list))
        assert(isinstance(build_depends, list))

        chunks_list = []
        for source_name, morph, repo, ref in chunks:
            chunks_list.append({
                'name': source_name,
                'morph': morph,
                'repo': repo,
                'ref': ref,
                'build-depends': [],
            })
        build_depends_list = []
        for morph, repo, ref in build_depends:
            build_depends_list.append({
                'morph': morph,
                'repo': repo,
                'ref': ref
            })
        if chunks_list:
            text = ('''
                    {
                        "name": "%s",
                        "kind": "stratum",
                        "build-depends": %s,
                        "chunks": %s
                    }
                    ''' % (name,
                           json.dumps(build_depends_list),
                           json.dumps(chunks_list)))
        else:
            text = ('''
                    {
                        "name": "%s",
                        "kind": "stratum",
                        "build-depends": %s
                    }
                    ''' % (name,
                           json.dumps(build_depends_list)))
        self.builds_artifacts = [name]
        morphlib.morph2.Morphology.__init__(self, text)


class MockSource(morphlib.source.Source):

    def __init__(self, name):
        self.repo_name = '%s.source.repo_name' % name
        self.original_ref = '%s.source.original_ref' % name
        self.sha1 = '%s.source.sha1' % name
        self.tree = '%s.source.tree' % name

        self.morphology = FakeChunkMorphology('%s.source.morphology' %
                                              name)

        self.filename = '%s.source.filename' % name
        self.build_mode = '%s.source.build_mode' % name
        self.prefix = '%s.source.prefix' % name

        super(MockSource, self).__init__(self.repo_name,
                                         self.original_ref,
                                         self.sha1,
                                         self.tree,
                                         self.morphology,
                                         self.filename)

class MockChunkArtifact(object):

    def __init__(self, name):
        self.source = MockSource(name)

        # This artifact also needs to be in the sources

        self.name = name
        self.arch = 'arch'
        self.cache_id = {
            'blip': '%s.blip' % name,
            'integer': 42,
        }
        self.cache_key = '%s.cache_key' % name
        self.dependencies = []


class SerialisationTests(unittest.TestCase):

    def setUp(self):
        self.art1 = morphlib.artifact('name1')
        self.art2 = morphlib.artifact('name2')
        self.art3 = morphlib.artifact('name3')
        self.art4 = morphlib.artifact('name4')

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
        self.assertEqual(len(a.dependencies), len(b.dependencies))
        for i in range(len(a.dependencies)):
            self.assertEqualArtifacts(a.dependencies[i], b.dependencies[i])

    def verify_round_trip(self, artifact):
        encoded = distbuild.serialise_artifact(artifact)
        print 'encoded: ', yaml.dump(yaml.load(encoded))

        decoded = distbuild.deserialise_artifact(encoded)
        print 'decoded: ', yaml.dump(yaml.load(decoded))

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

    def test_serialising_artifacts_for_a_system_with_two_dependent_strata(self):
        # TODO: this is duplicated in artifact resolver tests
        # (in fact it's stolen from there), we should share this code
        pool = morphlib.sourcepool.SourcePool()

        morph = FakeChunkMorphology('chunk1')
        chunk1 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = FakeStratumMorphology(
                'stratum1',
                chunks=[('chunk1', 'chunk1', 'repo', 'original/ref')])
        stratum1 = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'stratum1.morph')
        pool.add(stratum1)

        morph = morphlib.morph2.Morphology(
            '''
            {
                "name": "system",
                "kind": "system",
                "strata": [
                    {
                         "repo": "repo",
                         "ref": "ref",
                         "morph": "stratum1"
                    },
                    {
                         "repo": "repo",
                         "ref": "ref",
                         "morph": "stratum2"
                    }
                ]
            }
            ''')
        morph.builds_artifacts = ['system-rootfs']
        system = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'system.morph')
        pool.add(system)

        morph = FakeChunkMorphology('chunk2')
        chunk2 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk2.morph')
        pool.add(chunk2)

        morph = FakeStratumMorphology(
            'stratum2',
            chunks=[('chunk2', 'chunk2', 'repo', 'original/ref')],
            build_depends=[('stratum1', 'repo', 'ref')])
        stratum2 = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'stratum2.morph')
        pool.add(stratum2)

        artifacts = self.resolver.resolve_artifacts(pool)

        root_artifact = artifacts[0]

        self.verify_round_trip(root_artifact)


    def test_returns_string(self):
        encoded = distbuild.serialise_artifact(self.art1)
        self.assertEqual(type(encoded), str)

    #def test_works_without_dependencies(self):
    #    self.verify_round_trip(self.art1)

    #def test_works_with_single_dependency(self):
    #    # You can no longer add dependencies directly,
    #    # need to user artifact.add_dependency
    #    #self.art1.dependencies = [self.art2]
    #    self.art1.add_dependency(art2)
    #    self.verify_round_trip(self.art1)

    #def test_works_with_two_dependencies(self):
    #    self.art1.dependencies = [self.art2, self.art3]
    #    self.verify_round_trip(self.art1)

    #def test_works_with_two_levels_of_dependencies(self):
    #    self.art2.dependencies = [self.art4]
    #    self.art1.dependencies = [self.art2, self.art3]
    #    self.verify_round_trip(self.art1)

    #def test_works_with_dag(self):
    #    self.art2.dependencies = [self.art4]
    #    self.art3.dependencies = [self.art4]
    #    self.art1.dependencies = [self.art2, self.art3]
    #    self.verify_round_trip(self.art1)

