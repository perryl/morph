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
    else:
        text = yaml.dump({'name': name,
                          'kind': 'chunk'}, default_flow_style=False)

    loader = morphlib.morphloader.MorphologyLoader()
    morph = loader.load_from_string(text)
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
    return morph


class ArtifactResolverTests(unittest.TestCase):

    def setUp(self):
        self.resolver = morphlib.artifactresolver.ArtifactResolver()

    def test_resolve_artifacts_using_an_empty_pool(self):
        pool = morphlib.sourcepool.SourcePool()
        artifacts = self.resolver._resolve_artifacts(pool)
        self.assertEqual(len(artifacts), 0)

    def test_resolve_single_chunk_with_no_subartifacts(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk')
        sources = morphlib.source.make_sources('repo', 'ref',
                                               'chunk.morph', 'sha1',
                                               'tree', morph)
        for source in sources:
            pool.add(source)

        artifacts = self.resolver._resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        for artifact in artifacts:
            self.assertEqual(artifact.source, source)
            self.assertTrue(artifact.name.startswith('chunk'))
            self.assertEqual(source.dependencies, [])
            self.assertEqual(artifact.dependents, [])

    def test_resolve_single_chunk_with_one_new_artifact(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk', ['chunk-foobar'])
        sources = morphlib.source.make_sources('repo', 'ref',
                                               'chunk.morph', 'sha1',
                                               'tree', morph)
        for source in sources:
            pool.add(source)

        artifacts = self.resolver._resolve_artifacts(pool)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        foobartifact, = (a for a in artifacts if a.name == 'chunk-foobar')
        self.assertEqual(foobartifact.source, source)
        self.assertEqual(foobartifact.source.dependencies, [])
        self.assertEqual(foobartifact.dependents, [])

    def test_resolve_single_chunk_with_two_new_artifacts(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk', ['chunk-baz', 'chunk-qux'])
        sources = morphlib.source.make_sources('repo', 'ref',
                                               'chunk.morph', 'sha1',
                                               'tree', morph)
        for source in sources:
            pool.add(source)

        artifacts = self.resolver._resolve_artifacts(pool)
        artifacts.sort(key=lambda a: a.name)

        self.assertEqual(len(artifacts),
                         sum(len(s.split_rules.artifacts) for s in pool))

        for name in ('chunk-baz', 'chunk-qux'):
            artifact, = (a for a in artifacts if a.name == name)
            self.assertEqual(artifact.source, source)
            self.assertEqual(artifact.source.dependencies, [])
            self.assertEqual(artifact.dependents, [])

    def test_resolve_stratum_and_chunk(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk')
        sources = morphlib.source.make_sources('repo', 'ref',
                                               'chunk.morph', 'sha1',
                                               'tree', morph)
        for chunk in sources:
            pool.add(chunk)

        morph = get_stratum_morphology(
            'stratum', chunks=[('chunk', 'chunk', 'repo', 'ref')])
        stratum_sources = set(morphlib.source.make_sources('repo', 'ref',
                                                           'stratum.morph',
                                                           'sha1', 'tree',
                                                           morph))
        for stratum in stratum_sources:
            pool.add(stratum)

        artifacts = self.resolver._resolve_artifacts(pool)

        all_artifacts = set()
        for s in pool: all_artifacts.update(s.split_rules.artifacts)

        self.assertEqual(set(a.name for a in artifacts), all_artifacts)
        self.assertEqual(len(artifacts),
                         len(all_artifacts))


        stratum_artifacts = set(a for a in artifacts
                                if a.source in stratum_sources)
        chunk_artifacts = set(a for a in artifacts if a.source == chunk)

        for stratum_artifact in stratum_artifacts:
            self.assertTrue(stratum_artifact.name.startswith('stratum'))
            self.assertEqual(stratum_artifact.dependents, [])
            self.assertTrue(
                any(dep in chunk_artifacts
                    for dep in stratum_artifact.source.dependencies))

        for chunk_artifact in chunk_artifacts:
            self.assertTrue(chunk_artifact.name.startswith('chunk'))
            self.assertEqual(chunk_artifact.source.dependencies, [])
            self.assertTrue(any(dep in stratum_sources
                                for dep in chunk_artifact.dependents))

    def test_resolve_stratum_and_chunk_with_two_new_artifacts(self):
        pool = morphlib.sourcepool.SourcePool()

        morph = get_chunk_morphology('chunk', ['chunk-foo', 'chunk-bar'])
        sources = morphlib.source.make_sources('repo', 'ref',
                                               'chunk.morph', 'sha1',
                                               'tree', morph)
        for chunk in sources:
            pool.add(chunk)

        morph = get_stratum_morphology(
            'stratum',
            chunks=[
                ('chunk', 'chunk', 'repo', 'ref'),
            ])
        stratum_sources = set(morphlib.source.make_sources('repo', 'ref',
                                                           'stratum.morph',
                                                           'sha1', 'tree',
                                                           morph))
        for stratum in stratum_sources:
            pool.add(stratum)

        artifacts = self.resolver._resolve_artifacts(pool)

        self.assertEqual(
            set(artifacts),
            set(itertools.chain.from_iterable(
                    s.artifacts.itervalues()
                    for s in pool)))

        stratum_artifacts = set(a for a in artifacts
                                if a.source in stratum_sources)
        chunk_artifacts = set(a for a in artifacts if a.source == chunk)

        for stratum_artifact in stratum_artifacts:
            self.assertTrue(stratum_artifact.name.startswith('stratum'))
            self.assertEqual(stratum_artifact.dependents, [])
            self.assertTrue(
                any(dep in chunk_artifacts
                    for dep in stratum_artifact.source.dependencies))

        for chunk_artifact in chunk_artifacts:
            self.assertTrue(chunk_artifact.name.startswith('chunk'))
            self.assertEqual(chunk_artifact.source.dependencies, [])
            self.assertTrue(any(dep in stratum_sources
                                for dep in chunk_artifact.dependents))

    def test_detection_of_mutual_dependency_between_two_strata(self):
        loader = morphlib.morphloader.MorphologyLoader()
        pool = morphlib.sourcepool.SourcePool()

        chunk = get_chunk_morphology('chunk1')
        chunk1, = morphlib.source.make_sources(
            'repo', 'original/ref', 'chunk1.morph', 'sha1', 'tree', chunk)
        pool.add(chunk1)

        morph = get_stratum_morphology(
            'stratum1',
            chunks=[(loader.save_to_string(chunk), 'chunk1.morph',
                     'repo', 'original/ref')],
            build_depends=['stratum2'])
        sources = morphlib.source.make_sources('repo', 'original/ref',
                                               'stratum1.morph', 'sha1',
                                               'tree', morph)
        for stratum1 in sources:
            pool.add(stratum1)

        chunk = get_chunk_morphology('chunk2')
        chunk2, = morphlib.source.make_sources(
            'repo', 'original/ref', 'chunk2.morph', 'sha1', 'tree', chunk)
        pool.add(chunk2)

        morph = get_stratum_morphology(
            'stratum2',
            chunks=[(loader.save_to_string(chunk), 'chunk2.morph',
                     'repo', 'original/ref')],
            build_depends=['stratum1'])
        sources = morphlib.source.make_sources('repo', 'original/ref',
                                               'stratum2.morph', 'sha1',
                                               'tree', morph)
        for stratum2 in sources:
            pool.add(stratum2)

        self.assertRaises(morphlib.artifactresolver.MutualDependencyError,
                          self.resolver._resolve_artifacts, pool)

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
        sources = morphlib.source.make_sources('repo', 'original/ref',
                                               'stratum.morph', 'sha1',
                                               'tree', morph)
        for stratum in sources:
            pool.add(stratum)

        morph = get_chunk_morphology('chunk1')
        sources = morphlib.source.make_sources('repo', 'original/ref',
                                               'chunk1.morph', 'sha1',
                                               'tree', morph)
        for chunk1 in sources:
            pool.add(chunk1)

        morph = get_chunk_morphology('chunk2')
        sources = morphlib.source.make_sources('repo', 'original/ref',
                                               'chunk2.morph', 'sha1',
                                               'tree', morph)
        for chunk2 in sources:
            pool.add(chunk2)

        self.assertRaises(morphlib.artifactresolver.DependencyOrderError,
                          self.resolver._resolve_artifacts, pool)


# TODO: Expand test suite to include better dependency checking, many
#       tests were removed due to the fundamental change in how artifacts
#       and dependencies are constructed
