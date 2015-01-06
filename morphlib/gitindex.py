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


import collections
import os

import morphlib


STATUS_UNTRACKED = '??'
STATUS_IGNORED = '!!'


class GitIndex(object):
    '''An object that represents operations on the working tree.

    Index objects can be constructed with a different path to the
    index file, which can be used to construct commits without
    altering the working tree, index or HEAD.

    The file must either be a previously initialised index, or a
    non-existant file.

    Git creates a lock file and atomically alters the index by
    renaming a temporary file into place, so `index_file` must be
    in a writable directory.

    '''

    def __init__(self, gd, index_file):
        self._gd = gd
        self._index_file = index_file

    def _run_git(self, *args, **kwargs):
        if self._index_file is not None:
            extra_env = kwargs.get('extra_env', {})
            extra_env['GIT_INDEX_FILE'] = self._index_file
            kwargs['extra_env'] = extra_env

        if 'extra_env' in kwargs:
            env = kwargs.get('env', dict(os.environ))
            env.update(kwargs['extra_env'])
            kwargs['env'] = env
            del kwargs['extra_env']

        return morphlib.git.gitcmd(self._gd._runcmd, *args, **kwargs)

    def _get_status(self):
        '''Return git status output in a Python useful format

        This runs git status such that unusual filenames are preserved
        and returns its output in a sequence of (status_code, to_path,
        from_path).

        from_path is None unless the status_code says there was a
        rename, in which case it is the path it was renamed from.

        Untracked and ignored changes are also included in the output,
        their status codes are '??' and '!!' respectively.

        '''

        # git status -z will NUL terminate paths, so we don't have to
        # unescape the paths it outputs. Unfortunately each status entry
        # can have 1 or 2 paths, so extra parsing is required.
        # To handle this, we split it into NUL delimited tokens.
        # The first token of an entry is the 2 character status code,
        # a space, then the path.
        # If our status code starts with R then it's a rename, hence
        # has a second path, requiring us to pop an extra token.
        status = self._run_git('status', '-z', '--ignored')
        tokens = collections.deque(status.split('\0'))
        while True:
            tok = tokens.popleft()
            # Status output is NUL terminated rather than delimited,
            # and split is for delimited output. A side effect of this is
            # that we get an empty token as the last output. This suits
            # us fine, as it gives us a sentinel value to terminate with.
            if not tok:
                return

            # The first token of an entry is 2 character status, a space,
            # then the path
            code = tok[:2]
            to_path = tok[3:]

            # If the code starts with R then it's a rename, and
            # the next token says where the file was renamed from
            from_path = tokens.popleft() if code[0] == 'R' else None
            yield code, to_path, from_path

    def get_uncommitted_changes(self):
        for code, to_path, from_path in self._get_status():
            if (code not in (STATUS_UNTRACKED, STATUS_IGNORED)
            or  code == (STATUS_UNTRACKED) and to_path.endswith('.morph')):
                yield code, to_path, from_path

    def set_to_tree(self, treeish):
        '''Modify the index to contain the contents of the treeish.'''
        self._run_git('read-tree', treeish)

    def add_files_from_index_info(self, infos):
        '''Add files without interacting with the working tree.

        `infos` is an iterable of (file mode string, object sha1, path)
        There are no constraints on the size of the iterable

        '''

        # update-index may take NUL terminated input lines of the entries
        # to add so we generate a string for the input, rather than
        # having many command line arguments, since for a large amount
        # of entries, this can be too many arguments to process and the
        # exec will fail.
        # Generating the input as a string uses more memory than using
        # subprocess.Popen directly and using .communicate, but is much
        # less verbose.
        feed_stdin = '\0'.join('%o %s\t%s' % (mode, sha1, path)
                               for mode, sha1, path in infos) + '\0'
        self._run_git('update-index', '--add', '-z', '--index-info',
                      feed_stdin=feed_stdin)

    def add_files_from_working_tree(self, paths):
        '''Add existing files to the index.

        Given an iterable of paths to files in the working tree,
        relative to the git repository's top-level directory,
        add the contents of the files to git's object store,
        and the index.

        This is similar to the following:

            gd = GitDirectory(...)
            idx = gd.get_index()
            for path in paths:
                fullpath = os.path.join(gd,dirname, path)
                with open(fullpath, 'r') as f:
                    sha1 = gd.store_blob(f)
                idx.add_files_from_index_info([(os.stat(fullpath).st_mode,
                                                sha1, path)])

        '''

        if self._gd.is_bare():
            raise morphlib.gitdir.NoWorkingTreeError(self._gd)
        # Handle paths in smaller chunks, so that the runcmd
        # cannot fail from exceeding command line length
        # 50 is an arbitrary limit
        for paths in morphlib.util.iter_trickle(paths, 50):
            self._run_git('add', *paths)

    def write_tree(self):
        '''Transform the index into a tree in the object store.'''
        return self._run_git('write-tree').strip()

    def checkout(self, working_tree=None):
        '''Copy files from the index to the working tree.'''
        if working_tree:
            extra_env = {'GIT_WORK_TREE': working_tree}
        else:
            extra_env = {}
        self._run_git('checkout-index', '--all', extra_env=extra_env)
