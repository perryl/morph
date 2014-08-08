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


import logging
import os
import unittest

import fs.tempfs
import cliapp

import morphlib


class CachedRepoTests(unittest.TestCase):

    EXAMPLE_MORPH = '''{
        "name": "foo",
        "kind": "chunk"
    }'''

    known_commit = 'a4da32f5a81c8bc6d660404724cedc3bc0914a75'
    bad_sha1_known_to_rev_parse = 'cafecafecafecafecafecafecafecafecafecafe'

    def rev_parse(self, ref):
        output = {
            self.bad_sha1_known_to_rev_parse: self.bad_sha1_known_to_rev_parse,
            'a4da32f5a81c8bc6d660404724cedc3bc0914a75':
                    'a4da32f5a81c8bc6d660404724cedc3bc0914a75',
            'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9':
                    'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
            'master': 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
            'baserock/morph': '8b780e2e6f102fcf400ff973396566d36d730501'
        }
        try:
            return output[ref]
        except KeyError:
            raise cliapp.AppException('git rev-parse --verify %s' % ref)

    def show_tree_hash(self, absref):
        output = {
            'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9':
              'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
            '8b780e2e6f102fcf400ff973396566d36d730501':
              'ffffffffffffffffffffffffffffffffffffffff',
            'a4da32f5a81c8bc6d660404724cedc3bc0914a75':
              'dddddddddddddddddddddddddddddddddddddddd'
        }
        try:
            return output[absref]
        except KeyError:
            raise cliapp.AppException('git log -1 --format=format:%%T %s' %
                                      absref)

    def cat_file(self, ref, filename):
        output = {
            'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9:foo.morph':
            self.EXAMPLE_MORPH
        }
        try:
            return output['%s:%s' % (ref, filename)]
        except KeyError:
            raise cliapp.AppException(
                'git cat-file blob %s:%s' % (ref, filename))

    def copy_repository(self, source_dir, target_dir):
        if target_dir.endswith('failed-checkout'):
            raise morphlib.cachedrepo.CopyError(self.repo, target_dir)

    def checkout_ref(self, ref, target_dir):
        if ref == 'a4da32f5a81c8bc6d660404724cedc3bc0914a75':
            raise morphlib.cachedrepo.CloneError(self.repo, target_dir)
        elif ref == '079bbfd447c8534e464ce5d40b80114c2022ebf4':
            raise morphlib.cachedrepo.CheckoutError(self.repo, ref, target_dir)
        else:
            with open(os.path.join(target_dir, 'foo.morph'), 'w') as f:
                f.write('contents of foo.morph')

    def ls_tree(self, ref):
        output = {
            'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9':
            ['foo.morph']
        }
        try:
            return output[ref]
        except KeyError:
            raise cliapp.AppException('git ls-tree --name-only %s' % (ref))

    def clone_into(self, target_dir, ref):
        if target_dir.endswith('failed-checkout'):
            raise morphlib.cachedrepo.CloneError(self.repo, target_dir)
        self.clone_target = target_dir
        self.clone_ref = ref

    def update_successfully(self):
        pass

    def update_with_failure(self):
        raise cliapp.AppException('git remote update origin')

    def setUp(self):
        self.repo_name = 'foo'
        self.repo_url = 'git://foo.bar/foo.git'
        self.repo_path = '/tmp/foo'
        self.repo = morphlib.cachedrepo.CachedRepo(
            object(), self.repo_name, self.repo_url, self.repo_path)
        self.repo._rev_parse = self.rev_parse
        self.repo._show_tree_hash = self.show_tree_hash
        self.repo._cat_file = self.cat_file
        self.repo._copy_repository = self.copy_repository
        self.repo._checkout_ref = self.checkout_ref
        self.repo._ls_tree = self.ls_tree
        self.repo._clone_into = self.clone_into
        self.tempfs = fs.tempfs.TempFS()

    def test_constructor_sets_name_and_url_and_path(self):
        self.assertEqual(self.repo.original_name, self.repo_name)
        self.assertEqual(self.repo.url, self.repo_url)
        self.assertEqual(self.repo.path, self.repo_path)

    def test_ref_exists(self):
        self.assertEqual(self.repo.ref_exists('master'), True)

    def test_ref_does_not_exist(self):
        self.assertEqual(self.repo.ref_exists('non-existant-ref'), False)

    def test_resolve_named_ref_master(self):
        sha1, tree = self.repo.resolve_ref('master')
        self.assertEqual(sha1, 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
        self.assertEqual(tree, 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee')

    def test_resolve_named_ref_baserock_morph(self):
        sha1, tree = self.repo.resolve_ref('baserock/morph')
        self.assertEqual(sha1, '8b780e2e6f102fcf400ff973396566d36d730501')
        self.assertEqual(tree, 'ffffffffffffffffffffffffffffffffffffffff')

    def test_fail_resolving_invalid_named_ref(self):
        self.assertRaises(morphlib.cachedrepo.InvalidReferenceError,
                          self.repo.resolve_ref, 'foo/bar')

    def test_resolve_sha1_ref(self):
        sha1, tree = self.repo.resolve_ref(
            'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
        self.assertEqual(sha1, 'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
        self.assertEqual(tree, 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee')

    def test_fail_resolving_an_invalid_sha1_ref(self):
        self.assertRaises(morphlib.cachedrepo.InvalidReferenceError,
                          self.repo.resolve_ref,
                          self.bad_sha1_known_to_rev_parse)

    def test_cat_existing_file_in_existing_ref(self):
        data = self.repo.cat('e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                             'foo.morph')
        self.assertEqual(data, self.EXAMPLE_MORPH)

    def test_fail_cat_file_in_invalid_ref(self):
        self.assertRaises(
            morphlib.cachedrepo.InvalidReferenceError, self.repo.cat,
            '079bbfd447c8534e464ce5d40b80114c2022ebf4',
            'doesnt-matter-whether-this-file-exists')

    def test_fail_cat_non_existent_file_in_existing_ref(self):
        self.assertRaises(IOError, self.repo.cat,
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          'file-that-does-not-exist')

    def test_fail_cat_non_existent_file_in_invalid_ref(self):
        self.assertRaises(
            morphlib.cachedrepo.InvalidReferenceError, self.repo.cat,
            '079bbfd447c8534e464ce5d40b80114c2022ebf4',
            'file-that-does-not-exist')

    def test_fail_because_cat_in_named_ref_is_not_allowed(self):
        self.assertRaises(morphlib.cachedrepo.UnresolvedNamedReferenceError,
                          self.repo.cat, 'master', 'doesnt-matter')

    def test_fail_clone_checkout_into_existing_directory(self):
        self.assertRaises(morphlib.cachedrepo.CheckoutDirectoryExistsError,
                          self.repo.clone_checkout,
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          self.tempfs.root_path)

    def test_fail_checkout_due_to_clone_error(self):
        self.assertRaises(
            morphlib.cachedrepo.CloneError, self.repo.clone_checkout,
            'a4da32f5a81c8bc6d660404724cedc3bc0914a75',
            self.tempfs.getsyspath('failed-checkout'))

    def test_fail_checkout_due_to_copy_error(self):
        self.assertRaises(morphlib.cachedrepo.CopyError, self.repo.checkout,
                          'a4da32f5a81c8bc6d660404724cedc3bc0914a75',
                          self.tempfs.getsyspath('failed-checkout'))

    def test_fail_checkout_from_invalid_ref(self):
        self.assertRaises(
            morphlib.cachedrepo.CheckoutError, self.repo.checkout,
            '079bbfd447c8534e464ce5d40b80114c2022ebf4',
            self.tempfs.getsyspath('checkout-from-invalid-ref'))

    def test_checkout_from_existing_ref_into_new_directory(self):
        unpack_dir = self.tempfs.getsyspath('unpack-dir')
        self.repo.checkout('e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                           unpack_dir)
        self.assertTrue(os.path.exists(unpack_dir))

        morph_filename = os.path.join(unpack_dir, 'foo.morph')
        self.assertTrue(os.path.exists(morph_filename))

    def test_ls_tree_in_existing_ref(self):
        data = self.repo.ls_tree('e28a23812eadf2fce6583b8819b9c5dbd36b9fb9')
        self.assertEqual(data, ['foo.morph'])

    def test_fail_ls_tree_in_invalid_ref(self):
        self.assertRaises(
            morphlib.cachedrepo.InvalidReferenceError, self.repo.ls_tree,
            '079bbfd447c8534e464ce5d40b80114c2022ebf4')

    def test_fail_because_ls_tree_in_named_ref_is_not_allowed(self):
        self.assertRaises(morphlib.cachedrepo.UnresolvedNamedReferenceError,
                          self.repo.ls_tree, 'master')

    def test_successful_update(self):
        self.repo._update = self.update_successfully
        self.repo.update()

    def test_failing_update(self):
        self.repo._update = self.update_with_failure
        self.assertRaises(morphlib.cachedrepo.UpdateError, self.repo.update)

    def test_no_update_if_local(self):
        self.repo = morphlib.cachedrepo.CachedRepo(
            object(), 'local:repo', 'file:///local/repo/', '/local/repo/')
        self.repo._update = self.update_with_failure
        self.assertFalse(self.repo.requires_update_for_ref(self.known_commit))
        self.repo.update()

    def test_clone_checkout(self):
        self.repo.clone_checkout('master', '/.DOES_NOT_EXIST')
        self.assertEqual(self.clone_target, '/.DOES_NOT_EXIST')
        self.assertEqual(self.clone_ref, 'master')

    def test_no_need_to_update_repo_for_existing_sha1(self):
        # If the SHA1 is present locally already there's no need to update.
        # If it's a named ref then it might have changed in the remote, so we
        # must still update.
        self.assertFalse(self.repo.requires_update_for_ref(self.known_commit))
        self.assertTrue(self.repo.requires_update_for_ref('named_ref'))

    def test_no_need_to_update_repo_if_already_updated(self):
        self.repo._update = self.update_successfully

        self.assertTrue(self.repo.requires_update_for_ref('named_ref'))
        self.repo.update()
        self.assertFalse(self.repo.requires_update_for_ref('named_ref'))
