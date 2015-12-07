# Copyright (C) 2012-2015  Codethink Limited
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
# with this program.  If not, see <http://www.gnu.org/licenses/>.


import copy
import unittest

import morphlib


class DummyBuildEnvironment:
    '''Fake build environment class that doesn't need
       settings to pick the environment, it just gets passed
       a dict representing it
    '''
    def __init__(self, env, arch):
        self.env = env


default_split_rules = {
    'chunk': morphlib.artifactsplitrule.EMPTY_RULES,
    'stratum': morphlib.artifactsplitrule.EMPTY_RULES,
}


class CacheKeyComputerTests(unittest.TestCase):

    def setUp(self):
        loader = morphlib.morphloader.MorphologyLoader()
        self.source_pool = morphlib.sourcepool.SourcePool()
        for name, text in {
            'chunk.morph': '''
                name: chunk
                kind: chunk
                description: A test chunk
            ''',
            'chunk2.morph': '''
                name: chunk2
                kind: chunk
                description: A test chunk
            ''',
            'chunk3.morph': '''
                name: chunk3
                kind: chunk
                description: A test chunk
            ''',
            'stratum.morph': '''
                name: stratum
                kind: stratum
                build-depends: []
                chunks:
                    - name: chunk
                      morph: chunk.morph
                      repo: repo
                      ref: original/ref
                      build-depends: []
            ''',
            'stratum2.morph': '''
                name: stratum2
                kind: stratum
                build-depends: []
                chunks:
                    - name: chunk2
                      morph: chunk2.morph
                      repo: repo
                      ref: original/ref
                      build-depends: []
                    - name: chunk3
                      morph: chunk3.morph
                      repo: repo
                      ref: original/ref
                      build-depends: []
            ''',
            'system.morph': '''
                name: system
                kind: system
                arch: testarch
                strata:
                    - morph: stratum
                    - morph: stratum2
            ''',
        }.iteritems():
            morph = loader.load_from_string(text)
            sources = morphlib.source.make_sources(
                'repo', 'original/ref', name, 'sha1', 'tree', morph,
                default_split_rules=default_split_rules)
            for source in sources:
                self.source_pool.add(source)
        self.build_env = DummyBuildEnvironment({
            "LOGNAME": "foouser",
            "MORPH_ARCH": "dummy",
            "TARGET": "dummy-baserock-linux-gnu",
            "TARGET_STAGE1": "dummy-baserock-linux-gnu",
            "USER": "foouser",
            "USERNAME": "foouser"}, 'dummy')
        self.artifact_resolver = morphlib.artifactresolver.ArtifactResolver()
        self.artifacts = self.artifact_resolver._resolve_artifacts(
            self.source_pool)
        self.ckc = morphlib.cachekeycomputer.CacheKeyComputer(self.build_env)

    def _find_artifact(self, name):
        for artifact in self.artifacts:
            if artifact.name == name:
                return artifact

    def test_compute_key_hashes_all_types(self):
        runcount = {'thing': 0, 'dict': 0, 'list': 0, 'tuple': 0}

        def inccount(func, name):
            def f(sha, item):
                runcount[name] = runcount[name] + 1
                func(sha, item)
            return f

        self.ckc._hash_thing = inccount(self.ckc._hash_thing, 'thing')
        self.ckc._hash_dict = inccount(self.ckc._hash_dict, 'dict')
        self.ckc._hash_list = inccount(self.ckc._hash_list, 'list')
        self.ckc._hash_tuple = inccount(self.ckc._hash_tuple, 'tuple')

        artifact = self._find_artifact('system-rootfs')
        self.ckc.compute_key(artifact.source)

        self.assertNotEqual(runcount['thing'], 0)
        self.assertNotEqual(runcount['dict'], 0)
        self.assertNotEqual(runcount['list'], 0)
        self.assertNotEqual(runcount['tuple'], 0)

    def _valid_sha256(self, s):
        validchars = '0123456789abcdef'
        return len(s) == 64 and all([c in validchars for c in s])

    def test_compute_twice_same_key(self):
        artifact = self._find_artifact('system-rootfs')
        self.assertEqual(self.ckc.compute_key(artifact.source),
                         self.ckc.compute_key(artifact.source))

    def test_compute_twice_same_id(self):
        artifact = self._find_artifact('system-rootfs')
        id1 = self.ckc.get_cache_id(artifact.source)
        id2 = self.ckc.get_cache_id(artifact.source)
        hash1 = self.ckc._hash_id(id1)
        hash2 = self.ckc._hash_id(id2)
        self.assertEqual(hash1, hash2)

    def test_compute_key_returns_sha256(self):
        artifact = self._find_artifact('system-rootfs')
        self.assertTrue(self._valid_sha256(
                        self.ckc.compute_key(artifact.source)))

    def test_different_env_gives_different_key(self):
        artifact = self._find_artifact('system-rootfs')
        oldsha = self.ckc.compute_key(artifact.source)
        build_env = copy.deepcopy(self.build_env)
        build_env.env["USER"] = "brian"
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        self.assertNotEqual(oldsha, ckc.compute_key(artifact.source))
