# Copyright (C) 2013-2015  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import os
import shutil
import tempfile
import unittest

import morphlib


class GitIndexTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        with open(os.path.join(self.dirname, 'foo'), 'w') as f:
            f.write('dummy text\n')
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Initial commit')
        self.mirror = os.path.join(self.tempdir, 'mirror')
        morphlib.git.gitcmd(gd._runcmd, 'clone', '--mirror', self.dirname,
                            self.mirror)
        self.working_dir = os.path.join(self.tempdir, 'bar')
        os.makedirs(self.working_dir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_uncommitted_changes(self):
        idx = morphlib.gitdir.GitDirectory(self.dirname).get_index()
        self.assertEqual(list(idx.get_uncommitted_changes()), [])
        os.unlink(os.path.join(self.dirname, 'foo'))
        self.assertEqual(sorted(idx.get_uncommitted_changes()),
                         [(' D', 'foo', None)])

    def test_uncommitted_alt_index(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index(os.path.join(self.tempdir, 'index'))
        self.assertEqual(sorted(idx.get_uncommitted_changes()),
                         [('D ', 'foo', None)])
        # 'D ' means not in the index, but in the working tree

    def test_set_to_tree_alt_index(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index(os.path.join(self.tempdir, 'index'))
        # Read the HEAD commit into the index, which is the same as the
        # working tree, so there are no uncommitted changes reported
        # by status
        idx.set_to_tree(gd.HEAD)
        self.assertEqual(list(idx.get_uncommitted_changes()),[])

    def test_add_files_from_index_info(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index(os.path.join(self.tempdir, 'index'))
        filepath = os.path.join(gd.dirname, 'foo')
        with open(filepath, 'r') as f:
            sha1 = gd.store_blob(f)
            idx.add_files_from_index_info(
                [(os.stat(filepath).st_mode, sha1, 'foo')])
        self.assertEqual(list(idx.get_uncommitted_changes()),[])

    def test_add_files_from_working_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index()
        idx.add_files_from_working_tree(['foo'])
        self.assertEqual(list(idx.get_uncommitted_changes()),[])

    def test_add_files_from_working_tree_fails_in_bare(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        idx = gd.get_index()
        self.assertRaises(morphlib.gitdir.NoWorkingTreeError,
                          idx.add_files_from_working_tree, ['foo'])

    def test_write_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index()
        self.assertEqual(idx.write_tree(), gd.resolve_ref_to_tree(gd.HEAD))

    def test_checkout(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index()
        idx.checkout(working_tree=self.working_dir)
        self.assertTrue(os.path.exists(os.path.join(self.working_dir, 'foo')))

    def test_checkout_without_working_dir(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        idx = gd.get_index()
        idx.checkout()
        self.assertTrue(os.path.exists(os.path.join(self.dirname, 'foo')))
