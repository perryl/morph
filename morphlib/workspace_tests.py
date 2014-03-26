# Copyright (C) 2013-2014  Codethink Limited
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


class WorkspaceTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.workspace_dir = os.path.join(self.tempdir, 'workspace')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def assertIsWorkspace(self, dirname):
        self.assertTrue(os.path.isdir(dirname))
        self.assertTrue(os.path.isdir(os.path.join(dirname, '.morph')))

    def create_it(self):
        morphlib.workspace.create(self.workspace_dir)

    def test_creates_workspace(self):
        ws = morphlib.workspace.create(self.workspace_dir)
        self.assertIsWorkspace(self.workspace_dir)
        self.assertEqual(ws.root, self.workspace_dir)

    def test_create_initialises_existing_but_empty_directory(self):
        os.mkdir(self.workspace_dir)
        ws = morphlib.workspace.create(self.workspace_dir)
        self.assertIsWorkspace(self.workspace_dir)
        self.assertEqual(ws.root, self.workspace_dir)

    def test_fails_to_create_workspace_when_dir_exists_and_is_not_empty(self):
        os.mkdir(self.workspace_dir)
        os.mkdir(os.path.join(self.workspace_dir, 'somedir'))
        self.assertRaises(
            morphlib.workspace.WorkspaceDirExists,
            morphlib.workspace.create, self.workspace_dir)

    def test_fails_to_recreate_workspace(self):
        # Create it once.
        morphlib.workspace.create(self.workspace_dir)
        # Creating it again must fail.
        self.assertRaises(
            morphlib.workspace.WorkspaceDirExists,
            morphlib.workspace.create, self.workspace_dir)

    def test_opens_workspace_when_given_its_root(self):
        self.create_it()
        ws = morphlib.workspace.open(self.workspace_dir)
        self.assertEqual(ws.root, self.workspace_dir)

    def test_opens_workspace_when_given_subdirectory(self):
        self.create_it()
        subdir = os.path.join(self.workspace_dir, 'subdir')
        os.mkdir(subdir)
        ws = morphlib.workspace.open(subdir)
        self.assertEqual(ws.root, self.workspace_dir)

    def test_fails_to_open_workspace_when_no_workspace_anywhere(self):
        self.assertRaises(
            morphlib.workspace.NotInWorkspace,
            morphlib.workspace.open, self.tempdir)

    def test_invents_appropriate_name_for_system_branch_directory(self):
        self.create_it()
        ws = morphlib.workspace.open(self.workspace_dir)
        branch = 'foo/bar'
        self.assertEqual(
            ws.get_default_system_branch_directory_name(branch),
            os.path.join(self.workspace_dir, branch))

    def test_creates_system_branch_directory(self):
        self.create_it()
        ws = morphlib.workspace.open(self.workspace_dir)
        url = 'test:morphs'
        branch = 'my/new/thing'
        sb = ws.create_system_branch_directory(url, branch)
        self.assertEqual(type(sb), morphlib.sysbranchdir.SystemBranchDirectory)

    def test_lists_created_system_branches(self):
        self.create_it()
        ws = morphlib.workspace.open(self.workspace_dir)

        branches = ["branch/1", "branch/2"]
        for branch in branches:
            ws.create_system_branch_directory('test:morphs', branch)
        self.assertEqual(sorted(sb.system_branch_name
                                for sb in ws.list_system_branches()),
                         branches)
