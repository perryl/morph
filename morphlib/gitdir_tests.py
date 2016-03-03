# Copyright (C) 2013-2016  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import fs.tempfs

import contextlib
import datetime
import os
import shutil
import tempfile
import time
import unittest

import morphlib


@contextlib.contextmanager
def monkeypatch(obj, attr, new_value):
    old_value = getattr(obj, attr)
    setattr(obj, attr, new_value)
    yield
    setattr(obj, attr, old_value)


def allow_nonexistant_git_repos():
    '''Disable the gitdir._ensure_is_git_repo() function.

    This is used in other unit tests to avoid needing to run 'git init' at the
    start of each test. A library like 'mock' would be a better solution for
    this problem.

    '''
    return monkeypatch(
        morphlib.gitdir.GitDirectory, '_ensure_is_git_repo', lambda x: None)


class GitDirectoryTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def empty_git_directory(self):
        os.mkdir(self.dirname)
        return morphlib.gitdir.init(self.dirname)

    def test_ensures_is_a_git_repo(self):
        self.assertRaises(OSError,
                          morphlib.gitdir.GitDirectory, self.dirname)

        os.mkdir(self.dirname)
        self.assertRaises(morphlib.gitdir.NoGitRepoError,
                          morphlib.gitdir.GitDirectory, self.dirname)

    def test_has_dirname_attribute(self):
        gitdir = self.empty_git_directory()
        self.assertEqual(gitdir.dirname, self.dirname)

    def test_can_search_for_top_directory(self):
        self.empty_git_directory()

        path_inside_working_tree = os.path.join(self.dirname, 'a', 'b', 'c')
        os.makedirs(path_inside_working_tree)

        gitdir = morphlib.gitdir.GitDirectory(
            path_inside_working_tree, search_for_root=True)
        self.assertEqual(gitdir.dirname, self.dirname)

    def test_runs_command_in_right_directory(self):
        gitdir = self.empty_git_directory()
        output = gitdir._runcmd(['pwd'])
        self.assertEqual(output.strip(), self.dirname)

    def test_sets_and_gets_configuration(self):
        gitdir = self.empty_git_directory()
        gitdir.set_config('foo.bar', 'yoyo')
        self.assertEqual(gitdir.get_config('foo.bar'), 'yoyo')

    def test_sets_and_gets_configuration_from_file(self):
        gitdir = self.empty_git_directory()
        config = morphlib.gitdir.Config(
            config_file=os.path.join(gitdir.dirname, '.git', 'config'))
        config['foo.bar'] = 'yoyo'
        self.assertEqual(config['foo.bar'], 'yoyo')

    def test_gets_index(self):
        gitdir = self.empty_git_directory()
        self.assertIsInstance(gitdir.get_index(), morphlib.gitindex.GitIndex)


class GitDirectoryAnchoredRefTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        with open(os.path.join(self.dirname, 'test_file.morph'), "w") as f:
            f.write('dummy morphology text')
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Initial commit')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_ref_anchored_in_branch(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        output = morphlib.git.gitcmd(gd._runcmd, 'rev-parse', 'HEAD')
        ref = output.strip()

        self.assertEqual(len(gd.branches_containing_sha1(ref)), 1)
        self.assertEqual(gd.branches_containing_sha1(ref)[0], 'master')

    def test_ref_not_anchored_in_branch(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        output = morphlib.git.gitcmd(gd._runcmd, 'rev-parse', 'HEAD')
        ref = output.strip()

        morphlib.git.gitcmd(gd._runcmd, 'commit', '--amend', '-m',
                            'New commit message')
        self.assertEqual(len(gd.branches_containing_sha1(ref)), 0)

class GitDirectoryContentsTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        for fn in ('foo', 'bar.morph', 'baz.morph', 'quux'):
            with open(os.path.join(self.dirname, fn), "w") as f:
                f.write('dummy morphology text')
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Initial commit')
        os.rename(os.path.join(self.dirname, 'foo'),
                  os.path.join(self.dirname, 'foo.morph'))
        self.mirror = os.path.join(self.tempdir, 'mirror')
        morphlib.git.gitcmd(gd._runcmd, 'clone', '--mirror', self.dirname,
                            self.mirror)

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

    def test_read_raises_io_error(self):
        for gitdir in (self.dirname, self.mirror):
            gd = morphlib.gitdir.GitDirectory(gitdir)
            self.assertRaises(IOError,
                              gd.read_file, 'non-existant-file', 'HEAD')

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

    def test_ref_exists(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertFalse(gd.ref_exists('non-existant-ref'))
        self.assertTrue(gd.ref_exists('master'))
        self.assertFalse(
            gd.ref_exists('0000000000000000000000000000000000000000'))

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
        timezone = time.strftime('%z')

        now_str = "683074800"
        message= 'MESSAGE'
        expected = [
            "tree %(tree)s",
            "parent %(parent)s",
            "author %(aname)s <%(aemail)s> %(now_str)s %(timezone)s",
            "committer %(cname)s <%(cemail)s> %(now_str)s %(timezone)s",
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

        morphlib.git.gitcmd(gd._runcmd, 'tag', '-a', '-m', 'Example',
                            'example', 'HEAD')
        self.assertEqual(gd.describe(), 'example-unreproducible')

        morphlib.git.gitcmd(gd._runcmd, 'reset', '--hard')
        self.assertEqual(gd.describe(), 'example')

    def test_extract_commit_into_new_directory(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)

        unpack_dir = fs.tempfs.TempFS().getsyspath('unpack-dir')
        gd.extract_commit('master', unpack_dir)
        self.assertTrue(os.path.exists(unpack_dir))

        morph_filename = os.path.join(unpack_dir, 'bar.morph')
        self.assertTrue(os.path.exists(morph_filename))


class GitDirectoryFileTypeTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        with open(os.path.join(self.dirname, 'file'), "w") as f:
            f.write('dummy morphology text')
        os.symlink('file', os.path.join(self.dirname, 'link'))
        os.symlink('no file', os.path.join(self.dirname, 'broken'))
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Initial commit')
        self.mirror = os.path.join(self.tempdir, 'mirror')
        morphlib.git.gitcmd(gd._runcmd, 'clone', '--mirror', self.dirname,
                            self.mirror)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_working_tree_symlinks(self):
        gd = morphlib.gitdir.GitDirectory(self.dirname)
        self.assertTrue(gd.is_symlink('link'))
        self.assertTrue(gd.is_symlink('broken'))
        self.assertFalse(gd.is_symlink('file'))

    def test_bare_symlinks(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        self.assertTrue(gd.is_symlink('link', 'HEAD'))
        self.assertTrue(gd.is_symlink('broken', 'HEAD'))
        self.assertFalse(gd.is_symlink('file', 'HEAD'))

    def test_is_symlink_raises_no_ref_no_work_tree(self):
        gd = morphlib.gitdir.GitDirectory(self.mirror)
        self.assertRaises(morphlib.gitdir.NoWorkingTreeError,
                          gd.is_symlink, 'file')


class GitDirectoryRefTwiddlingTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.dirname = os.path.join(self.tempdir, 'foo')
        os.mkdir(self.dirname)
        gd = morphlib.gitdir.init(self.dirname)
        with open(os.path.join(self.dirname, 'foo'), 'w') as f:
            f.write('dummy text\n')
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Initial commit')
        # Add a second commit for update_ref test, so it has another
        # commit to roll back from
        with open(os.path.join(self.dirname, 'bar'), 'w') as f:
            f.write('dummy text\n')
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Second commit')

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

        morphlib.git.gitcmd(gitdir._runcmd, 'remote', 'add', 'origin',
                            'foobar')
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
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Initial commit')
        morphlib.git.gitcmd(gd._runcmd, 'checkout', '-b', 'foo')
        with open(os.path.join(self.dirname, 'foo'), 'w') as f:
            f.write('updated text\n')
        morphlib.git.gitcmd(gd._runcmd, 'add', '.')
        morphlib.git.gitcmd(gd._runcmd, 'commit', '-m', 'Second commit')
        self.mirror = os.path.join(self.tempdir, 'mirror')
        morphlib.git.gitcmd(gd._runcmd, 'init', '--bare', self.mirror)

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
