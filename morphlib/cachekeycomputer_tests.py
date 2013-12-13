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


class DummyBuildEnvironment:
    '''Fake build environment class that doesn't need
       settings to pick the environment, it just gets passed
       a dict representing it
    '''
    def __init__(self, env, arch):
        self.env = env


class CacheKeyComputerTests(unittest.TestCase):

    def setUp(self):
        self.source_pool = morphlib.sourcepool.SourcePool()
        for name, text in {
            'chunk.morph': '''{
                "name": "chunk",
                "kind": "chunk"
            }''',
            'chunk2.morph': '''{
                "name": "chunk2",
                "kind": "chunk"
            }''',
            'chunk3.morph': '''{
                "name": "chunk3",
                "kind": "chunk"
            }''',
            'stratum.morph': '''{
                "name": "stratum",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "chunk",
                        "repo": "repo",
                        "ref": "original/ref",
                        "build-depends": []
                    }
                ]
            }''',
            'stratum2.morph': '''{
                "name": "stratum2",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "chunk2",
                        "repo": "repo",
                        "ref": "original/ref",
                        "build-depends": []
                    },
                    {
                        "name": "chunk3",
                        "repo": "repo",
                        "ref": "original/ref",
                        "build-depends": []
                    }
                ]
            }''',
            'system.morph': '''{
                "name": "system",
                "kind": "system",
                "strata": [
                    {
                        "morph": "stratum",
                        "repo": "repo",
                        "ref": "original/ref"
                    },
                    {
                        "morph": "stratum2",
                        "repo": "repo",
                        "ref": "original/ref"
                    }
                ]
            }''',
        }.iteritems():
            source = morphlib.source.Source(
                'repo', 'original/ref', 'sha', 'tree',
                morphlib.morph2.Morphology(text), name)
            self.source_pool.add(source)
            # FIXME: This should use MorphologyFactory
            m = source.morphology
            if m['kind'] == 'system':
                m.builds_artifacts = [m['name'] + '-rootfs']
            elif m['kind'] == 'stratum':
                m.builds_artifacts = [m['name']]
            elif m['kind'] == 'chunk':
                m.builds_artifacts = [m['name']]
        self.build_env = DummyBuildEnvironment({
            "LOGNAME": "foouser",
            "MORPH_ARCH": "dummy",
            "TARGET": "dummy-baserock-linux-gnu",
            "TARGET_STAGE1": "dummy-baserock-linux-gnu",
            "USER": "foouser",
            "USERNAME": "foouser"}, 'dummy')
        self.artifact_resolver = morphlib.artifactresolver.ArtifactResolver()
        self.artifacts = self.artifact_resolver.resolve_artifacts(
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
        self.ckc.compute_key(artifact)

        self.assertNotEqual(runcount['thing'], 0)
        self.assertNotEqual(runcount['dict'], 0)
        self.assertNotEqual(runcount['list'], 0)
        self.assertNotEqual(runcount['tuple'], 0)

    def _valid_sha256(self, s):
        validchars = '0123456789abcdef'
        return len(s) == 64 and all([c in validchars for c in s])

    def test_compute_key_returns_sha256(self):
        artifact = self._find_artifact('system-rootfs')
        self.assertTrue(self._valid_sha256(
                        self.ckc.compute_key(artifact)))

    def test_different_env_gives_different_key(self):
        artifact = self._find_artifact('system-rootfs')
        oldsha = self.ckc.compute_key(artifact)
        build_env = copy.deepcopy(self.build_env)
        build_env.env["USER"] = "brian"
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        self.assertNotEqual(oldsha, ckc.compute_key(artifact))

    def test_same_morphology_text_but_changed_sha1_gives_same_cache_key(self):
        old_artifact = self._find_artifact('system-rootfs')
        morphology = old_artifact.source.morphology
        new_source = morphlib.source.Source('repo', 'original/ref', 'newsha',
                                            'tree', morphology,
                                            old_artifact.source.filename)
        sp = morphlib.sourcepool.SourcePool()
        for source in self.source_pool:
            if source == old_artifact.source:
                sp.add(new_source)
            else:
                sp.add(source)
        artifacts = self.artifact_resolver.resolve_artifacts(sp)
        for new_artifact in artifacts:
            if new_artifact.source == new_source:
                break
        else:
            self.assertTrue(False)

        old_sha = self.ckc.compute_key(old_artifact)
        new_sha = self.ckc.compute_key(new_artifact)
        self.assertEqual(old_sha, new_sha)

    def test_same_morphology_added_to_source_pool_only_appears_once(self):
        m = morphlib.morph2.Morphology('{"name": "chunk", "kind": "chunk"}')
        src = morphlib.source.Source('repo', 'original/ref', 'sha', 'tree', m,
                                     'chunk.morph')
        sp = morphlib.sourcepool.SourcePool()
        sp.add(src)
        sp.add(src)
        self.assertEqual(1, len([s for s in sp if s == src]))
