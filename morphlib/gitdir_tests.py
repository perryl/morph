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


import datetime
import os
import shutil
import tempfile
import unittest

import morphlib


class GitDirectoryTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def fake_git_clone(self):
        os.mkdir(self.dirname)
        os.mkdir(os.path.join(self.dirname, '.git'))

    def test_has_dirname_attribute(self):
        self.fake_git_clone()
        gitdir = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertEqual(gitdir.dirname, self.dirname)

    def test_runs_command_in_right_directory(self):
        self.fake_git_clone()
        gitdir = morphlib.gitdir.GitDirectory(self.dirname)
        output = gitdir._runcmd(['pwd'])
        self.assertEqual(output.strip(), self.dirname)

    def test_sets_and_gets_configuration(self):
        os.mkdir(self.dirname)
        gitdir = morphlib.gitdir.init(self.dirname)
        gitdir.set_config('foo.bar', 'yoyo')
        self.assertEqual(gitdir.get_config('foo.bar'), 'yoyo')

    def test_gets_index(self):
        os.mkdir(self.dirname)
        gitdir = morphlib.gitdir.init(self.dirname)
        self.assertIsInstance(gitdir.get_index(), morphlib.gitindex.GitIndex)


class GitDirectoryContentsTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        for fn in ('foo', 'bar.morph', 'baz.morph', 'quux'):
            with open(os.path.join(self.dirname, fn), "w") as f:
                f.write('dummy morphology text')
        gd._runcmd(['git', 'add', '.'])
        gd._runcmd(['git', 'commit', '-m', 'Initial commit'])
        os.rename(os.path.join(self.dirname, 'foo'),
                  os.path.join(self.dirname, 'foo.morph'))
        self.mirror = os.path.join(self.tempdir, 'mirror')
        gd._runcmd(['git', 'clone', '--mirror', self.dirname, self.mirror])

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_lists_files_in_work_tree(self):
        expected = ['bar.morph', 'baz.morph', 'foo.morph', 'quux']

        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertEqual(sorted(gd.list_files()), expected)

        gd = morphlib.gitdir.GitDirectory(self.dirname + '/')
        self.assertEqual(sorted(gd.list_files()), expected)

    def test_read_file_in_work_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertEqual(gd.read_file('bar.morph'),
                         'dummy morphology text')

    def test_list_raises_no_ref_no_work_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        self.assertRaises(morphlib.gitdir.NoWorkingTreeError,
                          gd.list_files)

    def test_read_raises_no_ref_no_work_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        self.assertRaises(morphlib.gitdir.NoWorkingTreeError,
                          gd.read_file, 'bar.morph')

    def test_lists_files_in_HEAD(self):
        for gitdir in (self.dirname, self.mirror):
            gd = morphlib.gitdir.GitDirectory(gitdir)
            self.assertEqual(sorted(gd.list_files('HEAD')),
                             ['bar.morph', 'baz.morph', 'foo', 'quux'])

    def test_read_files_in_HEAD(self):
        for gitdir in (self.dirname, self.mirror):
            gd = morphlib.gitdir.GitDirectory(gitdir)
            self.assertEqual(gd.read_file('bar.morph', 'HEAD'),
                             'dummy morphology text')

    def test_lists_files_in_named_ref(self):
        for gitdir in (self.dirname, self.mirror):
            gd = morphlib.gitdir.GitDirectory(gitdir)
            self.assertEqual(sorted(gd.list_files('master')),
                             ['bar.morph', 'baz.morph', 'foo', 'quux'])

    def test_read_file_in_named_ref(self):
        for gitdir in (self.dirname, self.mirror):
            gd = morphlib.gitdir.GitDirectory(gitdir)
            self.assertEqual(gd.read_file('bar.morph', 'master'),
                             'dummy morphology text')

    def test_list_raises_invalid_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertRaises(morphlib.gitdir.InvalidRefError,
                          gd.list_files, 'no-such-ref')

    def test_read_raises_invalid_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertRaises(morphlib.gitdir.InvalidRefError,
                          gd.read_file, 'bar', 'no-such-ref')

    def test_HEAD(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertEqual(gd.HEAD, 'master')

        gd.branch('foo', 'master')
        self.assertEqual(gd.HEAD, 'master')

        gd.checkout('foo')
        self.assertEqual(gd.HEAD, 'foo')

    def test_resolve_ref(self):
        # Just tests that you get an object IDs back and that the
        # commit and tree IDs are different, since checking the actual
        # value of the commit requires foreknowledge of the result or
        # re-implementing the body in the test.
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        commit = gd.resolve_ref_to_commit(gd.HEAD)
        self.assertEqual(len(commit), 40)
        tree = gd.resolve_ref_to_tree(gd.HEAD)
        self.assertEqual(len(tree), 40)
        self.assertNotEqual(commit, tree)

    def test_store_blob_with_string(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        sha1 = gd.store_blob('test string')
        self.assertEqual('test string', gd.get_blob_contents(sha1))

    def test_store_blob_with_file(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        with open(os.path.join(self.tempdir, 'blob'), 'w') as f:
            f.write('test string')
        with open(os.path.join(self.tempdir, 'blob'), 'r') as f:
            sha1 = gd.store_blob(f)
        self.assertEqual('test string', gd.get_blob_contents(sha1))

    def test_commit_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        parent = gd.resolve_ref_to_commit(gd.HEAD)
        tree = gd.resolve_ref_to_tree(parent)
        aname = 'Author Name'
        aemail = 'author@email'
        cname = 'Committer Name'
        cemail = 'committer@email'
        pseudo_now = datetime.datetime.fromtimestamp(683074800)

        now_str = "683074800"
        message= 'MESSAGE'
        expected = [
            "tree %(tree)s",
            "parent %(parent)s",
            "author %(aname)s <%(aemail)s> %(now_str)s +0000",
            "committer %(cname)s <%(cemail)s> %(now_str)s +0000",
            "",
            "%(message)s",
            "",
        ]
        expected = [l % locals() for l in expected]
        commit = gd.commit_tree(tree, parent, message=message,
                                committer_name=cname,
                                committer_email=cemail,
                                committer_date=pseudo_now,
                                author_name=aname,
                                author_email=aemail,
                                author_date=pseudo_now,
                                )
        self.assertEqual(expected, gd.get_commit_contents(commit).split('\n'))

    def test_describe(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)

        gd._runcmd(['git', 'tag', '-a', '-m', 'Example', 'example', 'HEAD'])
        self.assertEqual(gd.describe(), 'example-unreproducible')

        gd._runcmd(['git', 'reset', '--hard'])
        self.assertEqual(gd.describe(), 'example')


class GitDirectoryRefTwiddlingTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        with open(os.path.join(self.dirname, 'foo'), 'w') as f:
            f.write('dummy text\n')
        gd._runcmd(['git', 'add', '.'])
        gd._runcmd(['git', 'commit', '-m', 'Initial commit'])
        # Add a second commit for update_ref test, so it has another
        # commit to roll back from
        with open(os.path.join(self.dirname, 'bar'), 'w') as f:
            f.write('dummy text\n')
        gd._runcmd(['git', 'add', '.'])
        gd._runcmd(['git', 'commit', '-m', 'Second commit'])

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_expects_sha1s(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertRaises(morphlib.gitdir.ExpectedSha1Error,
                          gd.add_ref, 'refs/heads/foo', 'HEAD')
        self.assertRaises(morphlib.gitdir.ExpectedSha1Error,
                          gd.update_ref, 'refs/heads/foo', 'HEAD', 'HEAD')
        self.assertRaises(morphlib.gitdir.ExpectedSha1Error,
                          gd.update_ref, 'refs/heads/master',
                          gd._rev_parse(gd.HEAD), 'HEAD')
        self.assertRaises(morphlib.gitdir.ExpectedSha1Error,
                          gd.update_ref, 'refs/heads/master',
                          'HEAD', gd._rev_parse(gd.HEAD))
        self.assertRaises(morphlib.gitdir.ExpectedSha1Error,
                          gd.delete_ref, 'refs/heads/master', 'HEAD')

    def test_add_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        head_commit = gd.resolve_ref_to_commit(gd.HEAD)
        gd.add_ref('refs/heads/foo', head_commit)
        self.assertEqual(gd.resolve_ref_to_commit('refs/heads/foo'),
                         head_commit)

    def test_add_ref_fail(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        head_commit = gd.resolve_ref_to_commit('refs/heads/master')
        self.assertRaises(morphlib.gitdir.RefAddError,
                          gd.add_ref, 'refs/heads/master', head_commit)

    def test_update_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        head_commit = gd._rev_parse('refs/heads/master')
        prev_commit = gd._rev_parse('refs/heads/master^')
        gd.update_ref('refs/heads/master', prev_commit, head_commit)
        self.assertEqual(gd._rev_parse('refs/heads/master'), prev_commit)

    def test_update_ref_fail(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        head_commit = gd._rev_parse('refs/heads/master')
        prev_commit = gd._rev_parse('refs/heads/master^')
        gd.delete_ref('refs/heads/master', head_commit)
        with self.assertRaises(morphlib.gitdir.RefUpdateError):
            gd.update_ref('refs/heads/master', prev_commit, head_commit)

    def test_delete_ref(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        head_commit = gd._rev_parse('refs/heads/master')
        gd.delete_ref('refs/heads/master', head_commit)
        self.assertRaises(morphlib.gitdir.InvalidRefError,
                          gd._rev_parse, 'refs/heads/master')

    def test_delete_ref_fail(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        prev_commit = gd._rev_parse('refs/heads/master^')
        with self.assertRaises(morphlib.gitdir.RefDeleteError):
            gd.delete_ref('refs/heads/master', prev_commit)


class GitDirectoryRemoteConfigTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_sets_urls(self):
        os.mkdir(self.dirname)
        gitdir = morphlib.gitdir.init(self.dirname)
        remote = gitdir.get_remote('origin')
        self.assertEqual(remote.get_fetch_url(), None)
        self.assertEqual(remote.get_push_url(), None)

        gitdir._runcmd(['git', 'remote', 'add', 'origin', 'foobar'])
        fetch_url = 'git://git.example.com/foo.git'
        push_url = 'ssh://git@git.example.com/foo.git'
        remote.set_fetch_url(fetch_url)
        remote.set_push_url(push_url)
        self.assertEqual(remote.get_fetch_url(), fetch_url)
        self.assertEqual(remote.get_push_url(), push_url)

    def test_nascent_remote_fetch(self):
        os.mkdir(self.dirname)
        gitdir = morphlib.gitdir.init(self.dirname)
        remote = gitdir.get_remote(None)
        self.assertEqual(remote.get_fetch_url(), None)
        self.assertEqual(remote.get_push_url(), None)

        fetch_url = 'git://git.example.com/foo.git'
        push_url = 'ssh://git@git.example.com/foo.git'
        remote.set_fetch_url(fetch_url)
        remote.set_push_url(push_url)
        self.assertEqual(remote.get_fetch_url(), fetch_url)
        self.assertEqual(remote.get_push_url(), push_url)


class RefSpecTests(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    @staticmethod
    def refspec(*args, **kwargs):
        return morphlib.gitdir.RefSpec(*args, **kwargs)

    def test_input(self):
        with self.assertRaises(morphlib.gitdir.InvalidRefSpecError):
            morphlib.gitdir.RefSpec()

    def test_rs_from_source(self):
        rs = self.refspec(source='master')
        self.assertEqual(rs.push_args, ('master:master',))

    def test_rs_from_target(self):
        rs = self.refspec(target='master')
        self.assertEqual(rs.push_args, ('%s:master' % ('0' * 40),))

    def test_rs_with_target_and_source(self):
        rs = self.refspec(source='foo', target='master')
        self.assertEqual(rs.push_args, ('foo:master',))

    def test_rs_with_source_and_force(self):
        rs = self.refspec('master', force=True)
        self.assertEqual(rs.push_args, ('+master:master',))

    def test_rs_revert_from_source(self):
        revert = self.refspec(source='master').revert()
        self.assertEqual(revert.push_args, ('%s:master' % ('0' * 40),))

    def test_rs_revert_inc_require(self):
        revert = self.refspec(source='master', require=('beef'*5)).revert()
        self.assertEqual(revert.push_args, ('%s:master' % ('beef' * 5),))

    def test_rs_double_revert(self):
        rs = self.refspec(target='master').revert().revert()
        self.assertEqual(rs.push_args, ('%s:master' % ('0' * 40),))


class GitDirectoryRemotePushTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        with open(os.path.join(self.dirname, 'foo'), 'w') as f:
            f.write('dummy text\n')
        gd._runcmd(['git', 'add', '.'])
        gd._runcmd(['git', 'commit', '-m', 'Initial commit'])
        gd._runcmd(['git', 'checkout', '-b', 'foo'])
        with open(os.path.join(self.dirname, 'foo'), 'w') as f:
            f.write('updated text\n')
        gd._runcmd(['git', 'add', '.'])
        gd._runcmd(['git', 'commit', '-m', 'Second commit'])
        self.mirror = os.path.join(self.tempdir, 'mirror')
        gd._runcmd(['git', 'init', '--bare', self.mirror])

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_push_needs_refspecs(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        r = gd.get_remote()
        r.set_push_url(self.mirror)
        self.assertRaises(morphlib.gitdir.NoRefspecsError, r.push)

    def test_push_new(self):
        push_master = morphlib.gitdir.RefSpec('master')
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        r = gd.get_remote()
        r.set_push_url(self.mirror)
        self.assertEqual(sorted(r.push(push_master)),
                         [('*', 'refs/heads/master', 'refs/heads/master',
                           '[new branch]', None)])

    def test_double_push(self):
        push_master = morphlib.gitdir.RefSpec('master')
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        r = gd.get_remote()
        r.set_push_url(self.mirror)
        r.push(push_master)
        self.assertEqual(sorted(r.push(push_master)),
                         [('=', 'refs/heads/master', 'refs/heads/master',
                           '[up to date]', None)])

    def test_push_update(self):
        push_master = morphlib.gitdir.RefSpec('master')
        push_foo = morphlib.gitdir.RefSpec(source='foo', target='master')
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        r = gd.get_remote()
        r.set_push_url(self.mirror)
        r.push(push_master)
        flag, ref_from, ref_to, summary, reason = \
            list(r.push(push_foo))[0]
        self.assertEqual((flag, ref_from, ref_to),
                         (' ', 'refs/heads/foo', 'refs/heads/master'))

    def test_rewind_fail(self):
        push_master = morphlib.gitdir.RefSpec('master')
        push_foo = morphlib.gitdir.RefSpec(source='foo', target='master')
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        r = gd.get_remote()
        r.set_push_url(self.mirror)
        r.push(push_foo)
        with self.assertRaises(morphlib.gitdir.PushFailureError) as push_fail:
            r.push(push_master)
        self.assertEqual(sorted(push_fail.exception.results),
                         [('!', 'refs/heads/master', 'refs/heads/master',
                           '[rejected]', 'non-fast-forward')])

    def test_force_push(self):
        push_master = morphlib.gitdir.RefSpec('master', force=True)
        push_foo = morphlib.gitdir.RefSpec(source='foo', target='master')
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        r = gd.get_remote()
        r.set_push_url(self.mirror)
        r.push(push_foo)
        flag, ref_from, ref_to, summary, reason = \
            list(r.push(push_master))[0]
        self.assertEqual((flag, ref_from, ref_to, reason),
                         ('+', 'refs/heads/master', 'refs/heads/master',
                          'forced update'))
