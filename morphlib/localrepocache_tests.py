# Copyright (C) 2012-2016 Codethink Limited
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


import unittest
import urllib2
import os

import cliapp
import fs.memoryfs

import morphlib
import morphlib.gitdir_tests


class FakeApplication(object):

    def __init__(self):
        self.settings = {
            'debug': True,
            'verbose': True,
            'no-git-update': False,
        }

    def status(self, **kwargs):
        pass


class LocalRepoCacheTests(unittest.TestCase):

    def setUp(self):
        aliases = ['upstream=git://example.com/#example.com:%s.git']
        repo_resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)
        tarball_base_url = 'http://lorry.example.com/tarballs/'
        self.reponame = 'upstream:reponame'
        self.repourl = 'git://example.com/reponame'
        escaped_url = 'git___example_com_reponame'
        self.tarball_url = '%s%s.tar' % (tarball_base_url, escaped_url)
        self.cachedir = '/cache/dir'
        self.cache_path = '%s/%s' % (self.cachedir, escaped_url)
        self.remotes = {}
        self.fetched = []
        self.lrc = morphlib.localrepocache.LocalRepoCache(
            FakeApplication(), self.cachedir, repo_resolver, tarball_base_url)
        self.lrc.fs = fs.memoryfs.MemoryFS()
        self.lrc._git = self.fake_git
        self.lrc._fetch = self.not_found
        self.lrc._mkdtemp = self.fake_mkdtemp
        self.lrc._new_cached_repo_instance = self.new_cached_repo_instance
        self._mkdtemp_count = 0

    def fake_git(self, args, **kwargs):
        if args[0] == 'clone':
            self.assertEqual(len(args), 5)
            remote = args[3]
            local = args[4]
            self.remotes['origin'] = {'url': remote, 'updates': 0}
            self.lrc.fs.makedir(local, recursive=True)
        elif args[0:2] == ['remote', 'set-url']:
            remote = args[2]
            url = args[3]
            self.remotes[remote] = {'url': url}
        elif args[0:2] == ['config', 'remote.origin.url']:
            remote = 'origin'
            url = args[2]
            self.remotes[remote] = {'url': url}
        elif args[0:2] == ['config', 'remote.origin.mirror']:
            remote = 'origin'
        elif args[0:2] == ['config', 'remote.origin.fetch']:
            remote = 'origin'
        else:
            raise NotImplementedError()

    def fake_mkdtemp(self, dirname):
        thing = "foo"+str(self._mkdtemp_count)
        self._mkdtemp_count += 1
        self.lrc.fs.makedir(dirname+"/"+thing)
        return thing

    def new_cached_repo_instance(self, *args):
        with morphlib.gitdir_tests.allow_nonexistant_git_repos():
            repo = morphlib.cachedrepo.CachedRepo(
                FakeApplication(), *args)
            repo.update = lambda: None
            return repo

    def not_found(self, url, path):
        raise cliapp.AppException('Not found')

    def test_has_not_got_shortened_repo_initially(self):
        self.assertFalse(self.lrc.has_repo(self.reponame))

    def test_has_not_got_absolute_repo_initially(self):
        self.assertFalse(self.lrc.has_repo(self.repourl))

    def test_cachedir_does_not_exist_initially(self):
        self.assertFalse(self.lrc.fs.exists(self.cachedir))

    def test_creates_cachedir_if_missing(self):
        self.lrc.get_updated_repo(self.repourl, ref='master')
        self.assertTrue(self.lrc.fs.exists(self.cachedir))

    def test_happily_caches_same_repo_twice(self):
        self.lrc.get_updated_repo(self.repourl, ref='master')
        self.lrc.get_updated_repo(self.repourl, ref='master')

    def test_fails_to_cache_when_remote_does_not_exist(self):
        def fail(args, **kwargs):
            self.lrc.fs.makedir(args[4])
            raise cliapp.AppException('')
        self.lrc._git = fail
        self.assertRaises(morphlib.localrepocache.NoRemote,
                          self.lrc.get_updated_repo, self.repourl, 'master')

    def test_does_not_mind_a_missing_tarball(self):
        self.lrc.get_updated_repo(self.repourl, ref='master')
        self.assertEqual(self.fetched, [])

    def test_fetches_tarball_when_it_exists(self):
        self.lrc._fetch = lambda url, path: self.fetched.append(url)

        with morphlib.gitdir_tests.monkeypatch(
                morphlib.cachedrepo.CachedRepo, 'update', lambda self: None):
            self.lrc.get_updated_repo(self.repourl, ref='master')

        self.assertEqual(self.fetched, [self.tarball_url])
        self.assertFalse(self.lrc.fs.exists(self.cache_path + '.tar'))
        self.assertEqual(self.remotes['origin']['url'], self.repourl)

    def test_escapes_repourl_as_filename(self):
        escaped = self.lrc._escape(self.repourl)
        self.assertFalse('/' in escaped)

    def test_noremote_error_message_contains_repo_name(self):
        e = morphlib.localrepocache.NoRemote(self.repourl, [])
        self.assertTrue(self.repourl in str(e))

    def test_avoids_caching_local_repo(self):
        self.lrc.fs.makedir('/local/repo', recursive=True)
        cached = self.lrc.get_updated_repo('file:///local/repo', refs='master')
        assert cached.path == '/local/repo'
