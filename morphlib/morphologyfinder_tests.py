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


class MorphologyFinderTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'repo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        for fn in ('foo', 'bar.morph', 'baz.morph', 'quux'):
            with open(os.path.join(self.dirname, fn), "w") as f:
                f.write('dummy morphology text')
        gd._runcmd(['git', 'add', '.'])
        gd._runcmd(['git', 'commit', '-m', 'Initial commit'])

        # Changes for difference between commited and work tree
        newmorphpath = os.path.join(self.dirname, 'foo.morph')
        os.unlink(os.path.join(self.dirname, 'foo'))
        with open(newmorphpath, 'w') as f:
            f.write("altered morphology text")

        # Changes for bare repository
        self.mirror = os.path.join(self.tempdir, 'mirror')
        gd._runcmd(['git', 'clone', '--mirror', self.dirname, self.mirror])

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_list_morphs_in_HEAD(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd, 'HEAD')
        self.assertEqual(sorted(mf.list_morphologies()),
                         ['bar.morph', 'baz.morph'])

    def test_list_morphs_in_master(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd, 'master')
        self.assertEqual(sorted(mf.list_morphologies()),
                         ['bar.morph', 'baz.morph'])

    def test_list_morphs_raises_with_invalid_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd, 'invalid_ref')
        self.assertRaises(morphlib.gitdir.InvalidRefError,
                          mf.list_morphologies)

    def test_list_morphs_in_work_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd)
        self.assertEqual(sorted(mf.list_morphologies()),
                         ['bar.morph', 'baz.morph', 'foo.morph'])

    def test_list_morphs_raises_no_worktree_no_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd)
        self.assertRaises(morphlib.gitdir.NoWorkingTreeError,
                          mf.list_morphologies)

    def test_read_morph_in_HEAD(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd, 'HEAD')
        self.assertEqual(mf.read_morphology('bar.morph'),
                         "dummy morphology text")

    def test_read_morph_in_master(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd, 'master')
        self.assertEqual(mf.read_morphology('bar.morph'),
                         "dummy morphology text")

    def test_read_morph_raises_with_invalid_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd, 'invalid_ref')
        self.assertRaises(morphlib.gitdir.InvalidRefError,
                          mf.read_morphology, 'bar')

    def test_read_morph_in_work_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd)
        self.assertEqual(mf.read_morphology('foo.morph'),
                         "altered morphology text")

    def test_read_morph_raises_no_worktree_no_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd)
        self.assertRaises(morphlib.gitdir.NoWorkingTreeError,
                          mf.read_morphology, 'bar.morph')
