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


class FakeApplication(object):

    def __init__(self):
        self.settings = {
            'verbose': True
        }


class CachedRepoTests(unittest.TestCase):

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
        ref = ref.rstrip('^{commit}')
        try:
            return output[ref]
        except KeyError:
            raise cliapp.AppException('git rev-parse --verify %s' % ref)

    def copy_repository(self, source_dir, target_dir):
        if target_dir.endswith('failed-checkout'):
            raise morphlib.cachedrepo.CopyError(self.repo, target_dir)

    def checkout_ref(self, ref, target_dir):
        if ref == '079bbfd447c8534e464ce5d40b80114c2022ebf4':
            raise morphlib.cachedrepo.CheckoutError(self.repo, ref, target_dir)
        else:
            with open(os.path.join(target_dir, 'foo.morph'), 'w') as f:
                f.write('contents of foo.morph')

    def clone_into(self, target_dir, ref):
        if target_dir.endswith('failed-checkout'):
            raise morphlib.cachedrepo.CloneError(self.repo, target_dir)
        self.clone_target = target_dir
        self.clone_ref = ref

    def update_successfully(self, **kwargs):
        pass

    def update_with_failure(self, **kwargs):
        raise cliapp.AppException('git remote update origin')

    def setUp(self):
        self.repo_name = 'foo'
        self.repo_url = 'git://foo.bar/foo.git'
        self.repo_path = '/tmp/foo'
        self.repo = morphlib.cachedrepo.CachedRepo(
            FakeApplication(), self.repo_name, self.repo_url, self.repo_path)
        self.tempfs = fs.tempfs.TempFS()

    def test_constructor_sets_name_and_url_and_path(self):
        self.assertEqual(self.repo.original_name, self.repo_name)
        self.assertEqual(self.repo.url, self.repo_url)
        self.assertEqual(self.repo.path, self.repo_path)

    def test_fail_clone_checkout_into_existing_directory(self):
        self.repo._gitdir.checkout = self.checkout_ref
        self.repo._clone_into = self.clone_into

        self.assertRaises(morphlib.cachedrepo.CheckoutDirectoryExistsError,
                          self.repo.clone_checkout,
                          'e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                          self.tempfs.root_path)

    def test_fail_checkout_due_to_clone_error(self):
        self.repo._gitdir._rev_parse = self.rev_parse
        self.repo._clone_into = self.clone_into

        self.assertRaises(
            morphlib.cachedrepo.CloneError, self.repo.clone_checkout,
            'a4da32f5a81c8bc6d660404724cedc3bc0914a75',
            self.tempfs.getsyspath('failed-checkout'))

    def test_fail_checkout_due_to_copy_error(self):
        self.repo._gitdir._rev_parse = self.rev_parse
        self.repo._copy_repository = self.copy_repository

        self.assertRaises(morphlib.cachedrepo.CopyError, self.repo.checkout,
                          'a4da32f5a81c8bc6d660404724cedc3bc0914a75',
                          self.tempfs.getsyspath('failed-checkout'))

    def test_fail_checkout_from_invalid_ref(self):
        self.repo._gitdir._rev_parse = self.rev_parse
        self.repo._copy_repository = self.copy_repository
        self.repo._checkout_ref_in_clone = self.checkout_ref

        self.assertRaises(
            morphlib.cachedrepo.CheckoutError, self.repo.checkout,
            '079bbfd447c8534e464ce5d40b80114c2022ebf4',
            self.tempfs.getsyspath('checkout-from-invalid-ref'))

    def test_checkout_from_existing_ref_into_new_directory(self):
        self.repo._gitdir._rev_parse = self.rev_parse
        self.repo._copy_repository = self.copy_repository
        self.repo._checkout_ref_in_clone = self.checkout_ref

        unpack_dir = self.tempfs.getsyspath('unpack-dir')
        self.repo.checkout('e28a23812eadf2fce6583b8819b9c5dbd36b9fb9',
                           unpack_dir)
        self.assertTrue(os.path.exists(unpack_dir))

        morph_filename = os.path.join(unpack_dir, 'foo.morph')
        self.assertTrue(os.path.exists(morph_filename))

    def test_successful_update(self):
        self.repo._gitdir.update_remotes = self.update_successfully
        self.repo.update()

    def test_failing_update(self):
        self.repo._gitdir.update_remotes = self.update_with_failure
        self.assertRaises(morphlib.cachedrepo.UpdateError, self.repo.update)

    def test_no_update_if_local(self):
        self.repo = morphlib.cachedrepo.CachedRepo(
            object(), 'local:repo', 'file:///local/repo/', '/local/repo/')
        self.repo._gitdir.update_remotes = self.update_with_failure
        self.repo._gitdir._rev_parse = self.rev_parse

        self.assertFalse(self.repo.requires_update_for_ref(self.known_commit))
        self.repo.update()

    def test_clone_checkout(self):
        self.repo._gitdir._rev_parse = self.rev_parse
        self.repo._clone_into = self.clone_into

        self.repo.clone_checkout('master', '/.DOES_NOT_EXIST')
        self.assertEqual(self.clone_target, '/.DOES_NOT_EXIST')
        self.assertEqual(self.clone_ref, 'master')

    def test_no_need_to_update_repo_for_existing_sha1(self):
        # If the SHA1 is present locally already there's no need to update.
        # If it's a named ref then it might have changed in the remote, so we
        # must still update.
        self.repo._gitdir._rev_parse = self.rev_parse

        self.assertFalse(self.repo.requires_update_for_ref(self.known_commit))
        self.assertTrue(self.repo.requires_update_for_ref('named_ref'))

    def test_no_need_to_update_repo_if_already_updated(self):
        self.repo._gitdir.update_remotes = self.update_successfully
        self.repo._gitdir._rev_parse = self.rev_parse

        self.assertTrue(self.repo.requires_update_for_ref('named_ref'))
        self.repo.update()
        self.assertFalse(self.repo.requires_update_for_ref('named_ref'))
