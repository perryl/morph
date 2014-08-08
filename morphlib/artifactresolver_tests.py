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


import itertools
import unittest
import yaml

import morphlib


def get_chunk_morphology(name, artifact_names=[]):
    assert(isinstance(artifact_names, list))

    if artifact_names:
        # fake a list of artifacts
        artifacts = []
        for artifact_name in artifact_names:
            artifacts.append({'artifact': artifact_name,
                              'include': [artifact_name]})
        text = yaml.dump({"name": name,
                          "kind": "chunk",
                          "products": artifacts}, default_flow_style=False)
        builds_artifacts = artifact_names
    else:
        text = yaml.dump({'name': name,
                          'kind': 'chunk'}, default_flow_style=False)
        builds_artifacts = [name]

    loader = morphlib.morphloader.MorphologyLoader()
    morph = loader.load_from_string(text)
    morph.builds_artifacts = builds_artifacts
    return morph

def get_stratum_morphology(name, chunks=[], build_depends=[]):
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
    for morph in build_depends:
        build_depends_list.append({
            'morph': morph,
        })
    if chunks_list:
        text = yaml.dump({"name": name,
                          "kind": "stratum",
                          "build-depends": build_depends_list,
                          "chunks": chunks_list,}, default_flow_style=False)
    else:
        text = yaml.dump({"name": name,
                          "kind": "stratum",
                          "build-depends": build_depends_list},
                         default_flow_style=False)

    loader = morphlib.morphloader.MorphologyLoader()
    morph = loader.load_from_string(text)
    morph.builds_artifacts = [name]
    return morph


class ArtifactResolverTests(unittest.TestCase):

    def setUp(self):
        self.resolver = morphlib.artifactresolver.ArtifactResolver()

    def test_resolve_artifacts_using_an_empty_pool(self):
        pool = morphlib.sourcepool.SourcePool()
        artifacts = self.resolver.resolve_artifacts(pool)
        self.assertEqual(len(artifacts), 0)

    def test_resolve_single_chunk_with_no_subartifacts(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk')
        source = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        pool.add(source)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        for artifact in artifacts:
            self.assertEqual(artifact.source, source)
            self.assertTrue(artifact.name.startswith('chunk'))
            self.assertEqual(artifact.dependencies, [])
            self.assertEqual(artifact.dependents, [])

    def test_resolve_single_chunk_with_one_new_artifact(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk', ['chunk-foobar'])
        source = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        pool.add(source)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        foobartifact, = (a for a in artifacts if a.name == 'chunk-foobar')
        self.assertEqual(foobartifact.source, source)
        self.assertEqual(foobartifact.dependencies, [])
        self.assertEqual(foobartifact.dependents, [])

    def test_resolve_single_chunk_with_two_new_artifacts(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk', ['chunk-baz', 'chunk-qux'])
        source = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        pool.add(source)

        artifacts = self.resolver.resolve_artifacts(pool)
        artifacts.sort(key=lambda a: a.name)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        for name in ('chunk-baz', 'chunk-qux'):
            artifact, = (a for a in artifacts if a.name == name)
            self.assertEqual(artifact.source, source)
            self.assertEqual(artifact.dependencies, [])
            self.assertEqual(artifact.dependents, [])

    def test_resolve_stratum_and_chunk(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk')
        chunk = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        pool.add(chunk)

        morph = get_stratum_morphology(
            'stratum', chunks=[('chunk', 'chunk', 'repo', 'ref')])
        stratum = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'stratum.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        stratum_artifacts = set(a for a in artifacts if a.source == stratum)
        chunk_artifacts = set(a for a in artifacts if a.source == chunk)

        for stratum_artifact in stratum_artifacts:
            self.assertTrue(stratum_artifact.name.startswith('stratum'))
            self.assertEqual(stratum_artifact.dependents, [])
            self.assertTrue(any(dep in chunk_artifacts
                                for dep in stratum_artifact.dependencies))

        for chunk_artifact in chunk_artifacts:
            self.assertTrue(chunk_artifact.name.startswith('chunk'))
            self.assertEqual(chunk_artifact.dependencies, [])
            self.assertTrue(any(dep in stratum_artifacts
                                for dep in chunk_artifact.dependents))

    def test_resolve_stratum_and_chunk_with_two_new_artifacts(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk', ['chunk-foo', 'chunk-bar'])
        chunk = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        pool.add(chunk)

        morph = get_stratum_morphology(
            'stratum',
            chunks=[
                ('chunk', 'chunk', 'repo', 'ref'),
            ])
        stratum = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'stratum.morph')
        pool.add(stratum)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        stratum_artifacts = set(a for a in artifacts if a.source == stratum)
        chunk_artifacts = set(a for a in artifacts if a.source == chunk)

        for stratum_artifact in stratum_artifacts:
            self.assertTrue(stratum_artifact.name.startswith('stratum'))
            self.assertEqual(stratum_artifact.dependents, [])
            self.assertTrue(any(dep in chunk_artifacts
                                for dep in stratum_artifact.dependencies))

        for chunk_artifact in chunk_artifacts:
            self.assertTrue(chunk_artifact.name.startswith('chunk'))
            self.assertEqual(chunk_artifact.dependencies, [])
            self.assertTrue(any(dep in stratum_artifacts
                                for dep in chunk_artifact.dependents))

    def test_resolving_artifacts_for_a_system_with_two_dependent_strata(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk1')
        chunk1 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = get_stratum_morphology(
                'stratum1',
                chunks=[('chunk1', 'chunk1', 'repo', 'original/ref')])
        stratum1 = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'stratum1.morph')
        pool.add(stratum1)

        loader = morphlib.morphloader.MorphologyLoader()
        morph = loader.load_from_string(
            '''
                name: system
                kind: system
                arch: testarch
                strata:
                    - morph: stratum1
                    - morph: stratum2
            ''')
        morph.builds_artifacts = ['system-rootfs']
        system = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'system.morph')
        pool.add(system)

        morph = get_chunk_morphology('chunk2')
        chunk2 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk2.morph')
        pool.add(chunk2)

        morph = get_stratum_morphology(
            'stratum2',
            chunks=[('chunk2', 'chunk2', 'repo', 'original/ref')],
            build_depends=['stratum1'])
        stratum2 = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'stratum2.morph')
        pool.add(stratum2)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        system_artifacts = set(a for a in artifacts if a.source == system)
        stratum1_artifacts = set(a for a in artifacts if a.source == stratum1)
        chunk1_artifacts = set(a for a in artifacts if a.source == chunk1)
        stratum2_artifacts = set(a for a in artifacts if a.source == stratum2)
        chunk2_artifacts = set(a for a in artifacts if a.source == chunk2)

        def assert_depended_on_by_some(artifact, parents):
            self.assertNotEqual(len(artifact.dependents), 0)
            self.assertTrue(any(a in artifact.dependents for a in parents))

        def assert_depended_on_by_all(artifact, parents):
            self.assertNotEqual(len(artifact.dependents), 0)
            self.assertTrue(all(a in artifact.dependents for a in parents))

        def assert_depends_on_some(artifact, children):
            self.assertNotEqual(len(artifact.dependencies), 0)
            self.assertTrue(any(a in children for a in artifact.dependencies))

        def assert_depends_on_all(artifact, children):
            self.assertNotEqual(len(artifact.dependencies), 0)
            self.assertTrue(all(a in children for a in artifact.dependencies))

        for c1_a in chunk1_artifacts:
            self.assertEqual(c1_a.dependencies, [])
            assert_depended_on_by_some(c1_a, stratum1_artifacts)

        for st1_a in stratum1_artifacts:
            assert_depends_on_some(st1_a, chunk1_artifacts)
            assert_depended_on_by_all(st1_a, chunk2_artifacts)
            assert_depended_on_by_some(st1_a, system_artifacts)

        for c2_a in chunk2_artifacts:
            assert_depends_on_all(c2_a, stratum1_artifacts)
            assert_depended_on_by_some(c2_a, stratum2_artifacts)

        for st2_a in stratum2_artifacts:
            assert_depends_on_some(st2_a, chunk2_artifacts)
            assert_depended_on_by_some(st2_a, system_artifacts)

        for sy_a in system_artifacts:
            self.assertEqual(sy_a.dependents, [])
            assert_depends_on_some(sy_a, stratum1_artifacts)
            assert_depends_on_some(sy_a, stratum2_artifacts)

    def test_resolving_stratum_with_explicit_chunk_dependencies(self):
        pool = morphlib.sourcepool.SourcePool()

        loader = morphlib.morphloader.MorphologyLoader()
        morph = loader.load_from_string(
            '''
                name: stratum
                kind: stratum
                build-depends: []
                chunks:
                    - name: chunk1
                      repo: repo
                      ref: original/ref
                      build-depends: []
                    - name: chunk2
                      repo: repo
                      ref: original/ref
                      build-depends: []
                    - name: chunk3
                      repo: repo
                      ref: original/ref
                      build-depends:
                          - chunk1
                          - chunk2
            ''')
        morph.builds_artifacts = ['stratum']
        stratum = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'stratum.morph')
        pool.add(stratum)

        morph = get_chunk_morphology('chunk1')
        chunk1 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = get_chunk_morphology('chunk2')
        chunk2 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk2.morph')
        pool.add(chunk2)

        morph = get_chunk_morphology('chunk3')
        chunk3 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk3.morph')
        pool.add(chunk3)

        artifacts = self.resolver.resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        stratum_artifacts = set(a for a in artifacts if a.source == stratum)
        chunk_artifacts = [set(a for a in artifacts if a.source == source)
                           for source in (chunk1, chunk2, chunk3)]
        all_chunks = set(itertools.chain.from_iterable(chunk_artifacts))

        for st_a in stratum_artifacts:
            self.assertEqual(st_a.dependents, [])
            # This stratum depends on some chunk artifacts
            self.assertTrue(any(a in st_a.dependencies for a in all_chunks))

        for ca in chunk_artifacts[2]:
            # There's a stratum dependent on this artifact
            self.assertTrue(any(a in stratum_artifacts for a in ca.dependents))
            # chunk3's artifacts depend on chunk1 and chunk2's artifacts
            self.assertEqual(set(ca.dependencies),
                             chunk_artifacts[0] | chunk_artifacts[1])

        for ca in itertools.chain.from_iterable(chunk_artifacts[0:1]):
            self.assertEqual(ca.dependencies, [])
            # There's a stratum dependent on this artifact
            self.assertTrue(any(a in stratum_artifacts for a in ca.dependents))
            # All chunk3's artifacts depend on this artifact
            self.assertTrue(all(c3a in ca.dependents
                                for c3a in chunk_artifacts[2]))

    def test_detection_of_mutual_dependency_between_two_strata(self):
        loader = morphlib.morphloader.MorphologyLoader()
        pool = morphlib.sourcepool.SourcePool()

        chunk = get_chunk_morphology('chunk1')
        chunk1 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', chunk, 'chunk1.morph')
        pool.add(chunk1)

        morph = get_stratum_morphology(
            'stratum1',
            chunks=[(loader.save_to_string(chunk), 'chunk1.morph',
                     'repo', 'original/ref')],
            build_depends=['stratum2'])
        stratum1 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'stratum1.morph')
        pool.add(stratum1)

        chunk = get_chunk_morphology('chunk2')
        chunk2 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', chunk, 'chunk2.morph')
        pool.add(chunk2)

        morph = get_stratum_morphology(
            'stratum2',
            chunks=[(loader.save_to_string(chunk), 'chunk2.morph',
                     'repo', 'original/ref')],
            build_depends=['stratum1'])
        stratum2 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'stratum2.morph')
        pool.add(stratum2)

        self.assertRaises(morphlib.artifactresolver.MutualDependencyError,
                          self.resolver.resolve_artifacts, pool)

    def test_detection_of_chunk_dependencies_in_invalid_order(self):
        pool = morphlib.sourcepool.SourcePool()

        loader = morphlib.morphloader.MorphologyLoader()
        morph = loader.load_from_string(
            '''
                name: stratum
                kind: stratum
                build-depends: []
                chunks:
                    - name: chunk1
                      repo: repo
                      ref: original/ref
                      build-depends:
                          - chunk2
                    - name: chunk2
                      repo: repo
                      ref: original/ref
                      build-depends: []
            ''')
        morph.builds_artifacts = ['stratum']
        stratum = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'stratum.morph')
        pool.add(stratum)

        morph = get_chunk_morphology('chunk1')
        chunk1 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk1.morph')
        pool.add(chunk1)

        morph = get_chunk_morphology('chunk2')
        chunk2 = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk2.morph')
        pool.add(chunk2)

        self.assertRaises(morphlib.artifactresolver.DependencyOrderError,
                          self.resolver.resolve_artifacts, pool)

    def test_detection_of_invalid_build_depends_format(self):
        pool = morphlib.sourcepool.SourcePool()

        loader = morphlib.morphloader.MorphologyLoader()
        morph = loader.load_from_string(
            '''
                name: stratum
                kind: stratum
                build-depends: []
                chunks:
                    - name: chunk
                      repo: repo
                      ref: original/ref
                      build-depends: whatever
            ''')
        morph.builds_artifacts = ['stratum']
        stratum = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'stratum.morph')
        pool.add(stratum)

        morph = get_chunk_morphology('chunk')
        chunk = morphlib.source.Source(
            'repo', 'original/ref', 'sha1', 'tree', morph, 'chunk.morph')
        pool.add(chunk)

        self.assertRaises(morphlib.artifactresolver.DependencyFormatError,
                          self.resolver.resolve_artifacts, pool)


# TODO: Expand test suite to include better dependency checking, many
#       tests were removed due to the fundamental change in how artifacts
#       and dependencies are constructed
