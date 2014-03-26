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


import cliapp
import os
import shutil
import tempfile
import unittest

import morphlib


class SystemBranchDirectoryTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.root_directory = os.path.join(self.tempdir, 'rootdir')
        self.root_repository_url = 'test:morphs'
        self.system_branch_name = 'foo/bar'

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def create_fake_cached_repo(self):

        class FakeCachedRepo(object):

            def __init__(self, url, path):
                self.app = self
                self.settings = {
                    'repo-alias': [],
                }
                self.original_name = url
                self.url = 'git://blahlbah/blah/blahblahblah.git'
                self.path = path

                os.mkdir(self.path)
                cliapp.runcmd(['git', 'init', self.path])
                with open(os.path.join(self.path, 'filename'), 'w') as f:
                    f.write('this is a file\n')
                cliapp.runcmd(['git', 'add', 'filename'], cwd=self.path)
                cliapp.runcmd(
                    ['git', 'commit', '-m', 'initial'], cwd=self.path)

            def clone_checkout(self, ref, target_dir):
                cliapp.runcmd(
                    ['git', 'clone', '-b', ref, self.path, target_dir])

        subdir = tempfile.mkdtemp(dir=self.tempdir)
        path = os.path.join(subdir, 'foo')
        return FakeCachedRepo(self.root_repository_url, path)

    def test_creates_system_branch_directory(self):
        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)
        self.assertEqual(sb.root_directory, self.root_directory)
        self.assertEqual(sb.root_repository_url, self.root_repository_url)
        self.assertEqual(sb.system_branch_name, self.system_branch_name)

        magic_dir = os.path.join(self.root_directory, '.morph-system-branch')
        self.assertTrue(os.path.isdir(self.root_directory))
        self.assertTrue(os.path.isdir(magic_dir))
        self.assertTrue(os.path.isfile(os.path.join(magic_dir, 'config')))
        self.assertEqual(
            sb.get_config('branch.root'), self.root_repository_url)
        self.assertEqual(
            sb.get_config('branch.name'), self.system_branch_name)
        self.assertTrue(sb.get_config('branch.uuid'))

    def test_opens_system_branch_directory(self):
        morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)
        sb = morphlib.sysbranchdir.open(self.root_directory)
        self.assertEqual(sb.root_directory, self.root_directory)
        self.assertEqual(sb.root_repository_url, self.root_repository_url)
        self.assertEqual(sb.system_branch_name, self.system_branch_name)

    def test_opens_system_branch_directory_from_a_subdirectory(self):
        morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)
        subdir = os.path.join(self.root_directory, 'a', 'b', 'c')
        os.makedirs(subdir)
        sb = morphlib.sysbranchdir.open_from_within(subdir)
        self.assertEqual(sb.root_directory, self.root_directory)
        self.assertEqual(sb.root_repository_url, self.root_repository_url)
        self.assertEqual(sb.system_branch_name, self.system_branch_name)

    def test_fails_opening_system_branch_directory_when_none_exists(self):
        self.assertRaises(
            morphlib.sysbranchdir.NotInSystemBranch,
            morphlib.sysbranchdir.open_from_within,
            self.tempdir)

    def test_opens_system_branch_directory_when_it_is_the_only_child(self):
        deep_root = os.path.join(self.tempdir, 'a', 'b', 'c')
        morphlib.sysbranchdir.create(
            deep_root,
            self.root_repository_url,
            self.system_branch_name)
        sb = morphlib.sysbranchdir.open(deep_root)
        self.assertEqual(sb.root_directory, deep_root)
        self.assertEqual(sb.root_repository_url, self.root_repository_url)
        self.assertEqual(sb.system_branch_name, self.system_branch_name)

    def test_fails_to_create_if_directory_already_exists(self):
        os.mkdir(self.root_directory)
        self.assertRaises(
            morphlib.sysbranchdir.SystemBranchDirectoryAlreadyExists,
            morphlib.sysbranchdir.create,
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)

    def test_sets_and_gets_configuration_values(self):
        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)
        sb.set_config('foo.key', 'foovalue')

        sb2 = morphlib.sysbranchdir.open(self.root_directory)
        self.assertEqual(sb2.get_config('foo.key'), 'foovalue')

    def test_reports_correct_name_for_git_directory_from_aliases_url(self):
        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)
        self.assertEqual(
            sb.get_git_directory_name('baserock:baserock/morph'),
            os.path.join(self.root_directory, 'baserock/baserock/morph'))

    def test_reports_correct_name_for_git_directory_from_real_url(self):
        stripped = 'git.baserock.org/baserock/baserock/morph'
        url = 'git://%s.git' % stripped
        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            url,
            self.system_branch_name)
        self.assertEqual(
            sb.get_git_directory_name(url),
            os.path.join(self.root_directory, stripped))

    def test_reports_correct_path_for_file_in_repository(self):
        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)
        self.assertEqual(
            sb.get_filename('test:chunk', 'foo'),
            os.path.join(self.root_directory, 'test/chunk/foo'))

    def test_reports_correct_name_for_git_directory_from_file_url(self):
        stripped = 'foobar/morphs'
        url = 'file:///%s.git' % stripped
        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            url,
            self.system_branch_name)
        self.assertEqual(
            sb.get_git_directory_name(url),
            os.path.join(self.root_directory, stripped))

    def test_clones_git_repository(self):

        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)

        cached_repo = self.create_fake_cached_repo()
        gd = sb.clone_cached_repo(cached_repo, 'master')

        self.assertEqual(
            gd.dirname,
            sb.get_git_directory_name(cached_repo.original_name))

    def test_lists_git_directories(self):

        def fake_git_clone(dirname, url, branch):
            os.mkdir(dirname)
            subdir = os.path.join(dirname, '.git')
            os.mkdir(subdir)

        sb = morphlib.sysbranchdir.create(
            self.root_directory,
            self.root_repository_url,
            self.system_branch_name)

        sb._git_clone = fake_git_clone

        cached_repo = self.create_fake_cached_repo()
        sb.clone_cached_repo(cached_repo, 'master')

        gd_list = list(sb.list_git_directories())
        self.assertEqual(len(gd_list), 1)
        self.assertEqual(
            gd_list[0].dirname,
            sb.get_git_directory_name(cached_repo.original_name))

