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
import json
import os

import cliapp
import fs.memoryfs
import tempfile

import morphlib
import morphlib.gitdir_tests


class TestableRepoCache(morphlib.repocache.RepoCache):
    '''Adapts the RepoCache class for unit testing.

    All Git operations are stubbed out. You can track what Git operations have
    taken place by looking at the 'remotes' dict -- any 'clone' operations will
    set an entry in there. The 'tarballs_fetched' list tracks what tarballs
    of Git repos would have been downloaded.

    There is a single repo alias, 'example' which expands to
    git://example.com/.

    '''
    def __init__(self, update_gits=True):
        aliases = ['example=git://example.com/#example.com:%s.git']
        repo_resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)
        tarball_base_url = 'http://lorry.example.com/tarballs'
        cachedir = '/cache/gits/'
        memoryfs = fs.memoryfs.MemoryFS()

        morphlib.repocache.RepoCache.__init__(
            self, cachedir, repo_resolver, tarball_base_url=tarball_base_url,
            custom_fs=memoryfs, update_gits=update_gits)

        self.remotes = {}
        self.tarballs_fetched = []

        self._mkdtemp_count = 0

    def _mkdtemp(self, dirname):
        thing = "foo"+str(self._mkdtemp_count)
        self._mkdtemp_count += 1
        self.fs.makedir(dirname+"/"+thing)
        return thing

    def _fetch(self, url, path):
        self.tarballs_fetched.append(url)

    def _git(self, args, **kwargs):
        if args[0] == 'clone':
            assert len(args) == 5
            remote = args[3]
            local = args[4]
            self.remotes['origin'] = {'url': remote, 'updates': 0}
            self.fs.makedir(local, recursive=True)
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

    def _update_repo(self, cached_repo):
        pass


class RepoCacheTests(unittest.TestCase):

    def test_has_not_got_repo_initially(self):
        repo_cache = TestableRepoCache()
        self.assertFalse(repo_cache.has_repo('example:repo'))
        self.assertFalse(repo_cache.has_repo('git://example.com/repo'))

    def test_happily_caches_same_repo_twice(self):
        repo_cache = TestableRepoCache()
        with morphlib.gitdir_tests.allow_nonexistant_git_repos():
            repo_cache.get_updated_repo('example:repo', ref='master')
            repo_cache.get_updated_repo('example:repo', ref='master')

    def test_fails_to_cache_when_remote_does_not_exist(self):
        repo_cache = TestableRepoCache()

        def clone_fails(args, **kwargs):
            repo_cache.fs.makedir(args[4])
            raise cliapp.AppException('')
        repo_cache._git = clone_fails

        with self.assertRaises(morphlib.repocache.NoRemote):
            repo_cache.get_updated_repo('example:repo', 'master')

    def test_does_not_mind_a_missing_tarball(self):
        repo_cache = TestableRepoCache()

        def no_tarball(*args, **kwargs):
            raise cliapp.AppException('Not found')
        repo_cache._fetch = no_tarball

        with morphlib.gitdir_tests.allow_nonexistant_git_repos():
            repo_cache.get_updated_repo('example:repo', ref='master')
        self.assertEqual(repo_cache.tarballs_fetched, [])

    def test_fetches_tarball_when_it_exists(self):
        repo_url = 'git://example.com/reponame'
        repo_cache = TestableRepoCache()

        with morphlib.gitdir_tests.allow_nonexistant_git_repos():
            repo_cache.get_updated_repo(repo_url, ref='master')

        tarball_url = '%s%s.tar' % (repo_cache._tarball_base_url,
                                    repo_cache._escape(repo_url))
        self.assertEqual(repo_cache.tarballs_fetched, [tarball_url])

        # Check that the cache updated the repo after fetching the tarball.
        self.assertEqual(repo_cache.remotes['origin']['url'], repo_url)

    def test_escapes_repourl_as_filename(self):
        repo_cache = TestableRepoCache()
        escaped = repo_cache._escape('git://example.com/reponame')
        self.assertFalse('/' in escaped)

    def test_noremote_error_message_contains_repo_name(self):
        repo_url = 'git://example.com/reponame'
        e = morphlib.repocache.NoRemote(repo_url, [])
        self.assertTrue(repo_url in str(e))

    def test_avoids_caching_local_repo(self):
        repo_cache = TestableRepoCache()

        repo_cache.fs.makedir('/local/repo', recursive=True)
        with morphlib.gitdir_tests.allow_nonexistant_git_repos():
            cached = repo_cache.get_updated_repo(
                'file:///local/repo', refs='master')
        assert cached.dirname == '/local/repo'

    def test_no_git_update_setting(self):
        repo_cache = TestableRepoCache(update_gits=False)

        with self.assertRaises(morphlib.repocache.NotCached):
            repo_cache.get_updated_repo('example:repo', ref='master')


class RemoteRepoCacheTests(unittest.TestCase):
    def _resolve_ref_for_repo_url(self, repo_url, ref):
        return self.sha1s[repo_url][ref]

    def _cat_file_for_repo_url(self, repo_url, sha1, filename):
        try:
            return self.files[repo_url][sha1][filename]
        except KeyError:
            raise urllib2.HTTPError(url='', code=404, msg='Not found',
                                    hdrs={}, fp=None)

    def _ls_tree_for_repo_url(self, repo_url, sha1):
        return json.dumps({
            'repo': repo_url,
            'ref': sha1,
            'tree': self.files[repo_url][sha1]
        })

    def setUp(self):
        self.sha1s = {
            'git://gitorious.org/baserock/morph': {
                'master': 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9'
            }
        }
        self.files = {
            'git://gitorious.org/baserock-morphs/linux': {
                'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9': {
                    'linux.morph': 'linux morphology'
                }
            }
        }
        self.server_url = 'http://foo.bar'
        aliases = [
            'upstream=git://gitorious.org/baserock-morphs/#foo',
            'baserock=git://gitorious.org/baserock/#foo'
        ]
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)
        self.cache = morphlib.repocache.RemoteRepoCache(
            self.server_url, resolver)
        self.cache._resolve_ref_for_repo_url = self._resolve_ref_for_repo_url
        self.cache._cat_file_for_repo_url = self._cat_file_for_repo_url
        self.cache._ls_tree_for_repo_url = self._ls_tree_for_repo_url

    def test_sets_server_url(self):
        self.assertEqual(self.cache.server_url, self.server_url)

    def test_resolve_existing_ref_for_existing_repo(self):
        sha1 = self.cache.resolve_ref('baserock:morph', 'master')
        self.assertEqual(
            sha1,
            self.sha1s['git://gitorious.org/baserock/morph']['master'])

    def test_fail_resolving_existing_ref_for_non_existent_repo(self):
        self.assertRaises(morphlib.repocache.RemoteResolveRefError,
                          self.cache.resolve_ref, 'non-existent-repo',
                          'master')

    def test_fail_resolving_non_existent_ref_for_existing_repo(self):
        self.assertRaises(morphlib.repocache.RemoteResolveRefError,
                          self.cache.resolve_ref, 'baserock:morph',
                          'non-existent-ref')

    def test_fail_resolving_non_existent_ref_for_non_existent_repo(self):
        self.assertRaises(morphlib.repocache.RemoteResolveRefError,
                          self.cache.resolve_ref, 'non-existent-repo',
                          'non-existent-ref')

    def test_cat_existing_file_in_existing_repo_and_ref(self):
        content = self.cache.cat_file(
            'upstream:linux', 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
            'linux.morph')
        self.assertEqual(content, 'linux morphology')

    def test_fail_cat_file_using_invalid_sha1(self):
        self.assertRaises(morphlib.repocache.RemoteCatFileError,
                          self.cache.cat_file, 'upstream:linux', 'blablabla',
                          'linux.morph')

    def test_fail_cat_non_existent_file_in_existing_repo_and_ref(self):
        self.assertRaises(morphlib.repocache.RemoteCatFileError,
                          self.cache.cat_file, 'upstream:linux',
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          'non-existent-file')

    def test_fail_cat_file_in_non_existent_ref_in_existing_repo(self):
        self.assertRaises(morphlib.repocache.RemoteCatFileError,
                          self.cache.cat_file, 'upstream:linux',
                          'ecd7a325095a0d19b8c3d76f578d85b979461d41',
                          'linux.morph')

    def test_fail_cat_file_in_non_existent_repo(self):
        self.assertRaises(morphlib.repocache.RemoteCatFileError,
                          self.cache.cat_file, 'non-existent-repo',
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          'some-file')

    def test_ls_tree_in_existing_repo_and_ref(self):
        content = self.cache.ls_tree(
            'upstream:linux', 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
        self.assertEqual(content, ['linux.morph'])

    def test_fail_ls_tree_using_invalid_sha1(self):
        self.assertRaises(morphlib.repocache.RemoteLsTreeError,
                          self.cache.ls_tree, 'upstream:linux', 'blablabla')

    def test_fail_ls_file_in_non_existent_ref_in_existing_repo(self):
        self.assertRaises(morphlib.repocache.RemoteLsTreeError,
                          self.cache.ls_tree, 'upstream:linux',
                          'ecd7a325095a0d19b8c3d76f578d85b979461d41')

    def test_fail_ls_tree_in_non_existent_repo(self):
        self.assertRaises(morphlib.repocache.RemoteLsTreeError,
                          self.cache.ls_tree, 'non-existent-repo',
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')

