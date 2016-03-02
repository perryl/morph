# Copyright (C) 2012-2016  Codethink Limited
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


import json
import os
import StringIO
import unittest

import morphlib
import morphlib.gitdir_tests


class FakeBuildSystem(object):

    def __init__(self):
        self.build_commands = ['buildsys-it']


class FakeApp(object):
    def __init__(self, runcmd=None):
        self.runcmd = runcmd


class FakeStagingArea(object):

    def __init__(self, runcmd, build_env):
        self.runcmd = runcmd
        self.env = build_env.env


class FakeSource(object):

    def __init__(self):
        self.morphology = {
            'name': 'a',
            'kind': 'b',
            'description': 'c',
        }
        self.name = 'a'

        with morphlib.gitdir_tests.allow_nonexistant_git_repos():
            self.repo = morphlib.repocache.CachedRepo(
                'path', 'repo', 'url')
        self.repo_name = 'url'
        self.original_ref = 'e'
        self.sha1 = 'f'
        self.filename = 'g'


class FakeArtifact(object):

    def __init__(self, name):
        self.name = name
        self.source = FakeSource()
        self.cache_key = 'blahblah'
        self.cache_id = {}


class FakeBuildEnv(object):

    def __init__(self):
        self.arch = 'le-arch'
        self.env = {
            'PATH': '/le-bin:/le-bon:/le-bin-bon',
        }


class FakeFileHandle(object):

    def __init__(self, cache, key):
        self._string = ""
        self._cache = cache
        self._key = key

    def __enter__(self):
        return self

    def _writeback(self):
        self._cache._cached[self._key] = self._string

    def __exit__(self, type, value, traceback):
        self._writeback()

    def close(self):
        self._writeback()

    def write(self, string):
        self._string += string


class FakeArtifactCache(object):

    def __init__(self):
        self._cached = {}

    def put(self, artifact):
        return FakeFileHandle(self, (artifact.cache_key, artifact.name))

    def put_artifact_metadata(self, artifact, name):
        return FakeFileHandle(self, (artifact.cache_key, artifact.name, name))

    def put_source_metadata(self, source, cachekey, name):
        return FakeFileHandle(self, (cachekey, name))

    def get(self, artifact):
        return StringIO.StringIO(
            self._cached[(artifact.cache_key, artifact.name)])

    def get_artifact_metadata(self, artifact, name):
        return StringIO.StringIO(
            self._cached[(artifact.cache_key, artifact.name, name)])

    def get_source_metadata(self, source, cachekey, name):
        return StringIO.StringIO(self._cached[(cachekey, name)])

    def has(self, artifact):
        return (artifact.cache_key, artifact.name) in self._cached

    def has_artifact_metadata(self, artifact, name):
        return (artifact.cache_key, artifact.name, name) in self._cached

    def has_source_metadata(self, source, cachekey, name):
        return (cachekey, name) in self._cached


class BuilderBaseTests(unittest.TestCase):

    def fake_runcmd(self, argv, *args, **kwargs):
        self.commands_run.append(argv)

    def setUp(self):
        self.commands_run = []
        self.app = FakeApp(self.fake_runcmd)
        self.staging_area = FakeStagingArea(self.fake_runcmd, FakeBuildEnv())
        self.artifact_cache = FakeArtifactCache()
        self.artifact = FakeArtifact('le-artifact')
        self.repo_cache = None
        self.build_env = FakeBuildEnv()
        self.max_jobs = 1
        self.builder = morphlib.builder.BuilderBase(self.app,
                                                     self.staging_area,
                                                     self.artifact_cache,
                                                     None,
                                                     self.artifact,
                                                     self.repo_cache,
                                                     self.max_jobs,
                                                     False)

    def test_runs_desired_command(self):
        self.builder.runcmd(['foo', 'bar'])
        self.assertEqual(self.commands_run, [['foo', 'bar']])

    def test_writes_build_times(self):
        with self.builder.build_watch('nothing'):
            pass
        self.builder.save_build_times()
        self.assertTrue(self.artifact_cache.has_source_metadata(
            self.artifact.source, self.artifact.cache_key, 'meta'))

    def test_watched_events_in_cache(self):
        events = ["configure", "build", "install"]
        for event in events:
            with self.builder.build_watch(event):
                pass
        self.builder.save_build_times()
        meta = json.load(self.artifact_cache.get_source_metadata(
            self.artifact.source, self.artifact.cache_key, 'meta'))
        self.assertEqual(sorted(events),
                         sorted(meta['build-times'].keys()))

    def test_downloads_depends(self):
        lac = FakeArtifactCache()
        rac = FakeArtifactCache()
        afacts = [FakeArtifact(name) for name in ('a', 'b', 'c')]
        for a in afacts:
            fh = rac.put(a)
            fh.write(a.name)
            fh.close()
        morphlib.builder.download_depends(afacts, lac, rac)
        self.assertTrue(all(lac.has(a) for a in afacts))

    def test_downloads_depends_metadata(self):
        lac = FakeArtifactCache()
        rac = FakeArtifactCache()
        afacts = [FakeArtifact(name) for name in ('a', 'b', 'c')]
        for a in afacts:
            fh = rac.put(a)
            fh.write(a.name)
            fh.close()
            fh = rac.put_artifact_metadata(a, 'meta')
            fh.write('metadata')
            fh.close()
        morphlib.builder.download_depends(afacts, lac, rac, ('meta',))
        self.assertTrue(all(lac.has(a) for a in afacts))
        self.assertTrue(all(lac.has_artifact_metadata(a, 'meta')
                            for a in afacts))


class ChunkBuilderTests(unittest.TestCase):

    def setUp(self):
        self.app = FakeApp()
        self.build = morphlib.builder.ChunkBuilder(self.app, None, None,
                                                    None, None, None, 1, False)
