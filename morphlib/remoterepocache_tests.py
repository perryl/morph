# Copyright (C) 2012-2013  Codethink Limited
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


import json
import unittest

import morphlib


class RemoteRepoCacheTests(unittest.TestCase):

    def _resolve_ref_for_repo_url(self, repo_url, ref):
        return self.sha1s[repo_url][ref]

    def _resolve_refs_for_repo_urls(self, tuples, urls):
        if self.fail_resolving:
            raise Exception('Failed')
        data = {}
        for n in xrange(0, len(tuples)):
            data[tuples[n]] = {
                'repo': tuples[n][0],
                'repo-url': urls[n],
                'ref': tuples[n][1],
            }
            if tuples[n][0] == 'upstream:foo':
                data[tuples[n]]['error'] = 'Failed'
            else:
                data[tuples[n]]['sha1'] = self.sha1s[urls[n]][tuples[n][1]]
                data[tuples[n]]['tree'] = self.trees[urls[n]][tuples[n][1]]
        return data

    def _cat_file_for_repo_url(self, repo_url, sha1, filename):
        return self.files[repo_url][sha1][filename]

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
            },
            'git://gitorious.org/baserock-morphs/linux': {
                'foo/bar': 'aa363025d0b699b4251ee80aeec2b863e57dd7ec'
            }
        }
        self.trees = {
            'git://gitorious.org/baserock/morph': {
                'master': 'f99e30eb68c28ea8bc2ca7710e2894c49bbaedbe'
            },
            'git://gitorious.org/baserock-morphs/linux': {
                'foo/bar': '4c7b6184fe12775ceb83cefb405921e961495e9c'
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
        self.cache = morphlib.remoterepocache.RemoteRepoCache(
            self.server_url, resolver)
        self.cache._resolve_ref_for_repo_url = self._resolve_ref_for_repo_url
        self.cache._resolve_refs_for_repo_urls = \
                self._resolve_refs_for_repo_urls
        self.cache._cat_file_for_repo_url = self._cat_file_for_repo_url
        self.cache._ls_tree_for_repo_url = self._ls_tree_for_repo_url
        self.fail_resolving = False

    def test_sets_server_url(self):
        self.assertEqual(self.cache.server_url, self.server_url)

    def test_resolve_existing_ref_for_existing_repo(self):
        sha1 = self.cache.resolve_ref('baserock:morph', 'master')
        self.assertEqual(
            sha1,
            self.sha1s['git://gitorious.org/baserock/morph']['master'])

    def test_fail_resolving_existing_ref_for_non_existent_repo(self):
        self.assertRaises(morphlib.remoterepocache.ResolveRefError,
                          self.cache.resolve_ref, 'non-existent-repo',
                          'master')

    def test_fail_resolving_non_existent_ref_for_existing_repo(self):
        self.assertRaises(morphlib.remoterepocache.ResolveRefError,
                          self.cache.resolve_ref, 'baserock:morph',
                          'non-existent-ref')

    def test_fail_resolving_non_existent_ref_for_non_existent_repo(self):
        self.assertRaises(morphlib.remoterepocache.ResolveRefError,
                          self.cache.resolve_ref, 'non-existent-repo',
                          'non-existent-ref')

    def test_resolves_multiple_existing_refs(self):
        sha1s = self.cache.resolve_refs(
                [('baserock:morph', 'master'), ('upstream:linux', 'foo/bar')])
        self.assertEqual(
                sha1s[('baserock:morph', 'master')],
                {
                    'repo': 'baserock:morph',
                    'repo-url': 'git://gitorious.org/baserock/morph',
                    'ref': 'master',
                    'sha1': 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                    'tree': 'f99e30eb68c28ea8bc2ca7710e2894c49bbaedbe'
                })
        self.assertEqual(
                sha1s[('upstream:linux', 'foo/bar')],
                {
                    'repo': 'upstream:linux',
                    'repo-url': 'git://gitorious.org/baserock-morphs/linux',
                    'ref': 'foo/bar',
                    'sha1': 'aa363025d0b699b4251ee80aeec2b863e57dd7ec',
                    'tree': '4c7b6184fe12775ceb83cefb405921e961495e9c'
                })

    def test_throws_exception_when_failing_to_resolve_refs_entirely(self):
        self.fail_resolving = True
        self.assertRaises(
                morphlib.remoterepocache.ResolveRefsError,
                self.cache.resolve_refs,
                [('baserock:morph', 'master'), ('upstream:linux', 'foo/bar')])

    def test_fills_error_fields_when_failing_to_resolve_some_refs(self):
        sha1s = self.cache.resolve_refs(
                [('baserock:morph', 'master'), ('upstream:foo', 'bar')])
        self.assertEqual(
                sha1s[('baserock:morph', 'master')],
                {
                    'repo': 'baserock:morph',
                    'repo-url': 'git://gitorious.org/baserock/morph',
                    'ref': 'master',
                    'sha1': 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                    'tree': 'f99e30eb68c28ea8bc2ca7710e2894c49bbaedbe'
                })
        self.assertEqual(
                sha1s[('upstream:foo', 'bar')],
                {
                    'repo': 'upstream:foo',
                    'repo-url': 'git://gitorious.org/baserock-morphs/foo',
                    'ref': 'bar',
                    'error': 'Failed',
                })

    def test_cat_existing_file_in_existing_repo_and_ref(self):
        content = self.cache.cat_file(
            'upstream:linux', 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
            'linux.morph')
        self.assertEqual(content, 'linux morphology')

    def test_fail_cat_file_using_invalid_sha1(self):
        self.assertRaises(morphlib.remoterepocache.CatFileError,
                          self.cache.cat_file, 'upstream:linux', 'blablabla',
                          'linux.morph')

    def test_fail_cat_non_existent_file_in_existing_repo_and_ref(self):
        self.assertRaises(morphlib.remoterepocache.CatFileError,
                          self.cache.cat_file, 'upstream:linux',
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          'non-existent-file')

    def test_fail_cat_file_in_non_existent_ref_in_existing_repo(self):
        self.assertRaises(morphlib.remoterepocache.CatFileError,
                          self.cache.cat_file, 'upstream:linux',
                          'ecd7a325095a0d19b8c3d76f578d85b979461d41',
                          'linux.morph')

    def test_fail_cat_file_in_non_existent_repo(self):
        self.assertRaises(morphlib.remoterepocache.CatFileError,
                          self.cache.cat_file, 'non-existent-repo',
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          'some-file')

    def test_ls_tree_in_existing_repo_and_ref(self):
        content = self.cache.ls_tree(
            'upstream:linux', 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
        self.assertEqual(content, ['linux.morph'])

    def test_fail_ls_tree_using_invalid_sha1(self):
        self.assertRaises(morphlib.remoterepocache.LsTreeError,
                          self.cache.ls_tree, 'upstream:linux', 'blablabla')

    def test_fail_ls_file_in_non_existent_ref_in_existing_repo(self):
        self.assertRaises(morphlib.remoterepocache.LsTreeError,
                          self.cache.ls_tree, 'upstream:linux',
                          'ecd7a325095a0d19b8c3d76f578d85b979461d41')

    def test_fail_ls_tree_in_non_existent_repo(self):
        self.assertRaises(morphlib.remoterepocache.LsTreeError,
                          self.cache.ls_tree, 'non-existent-repo',
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
