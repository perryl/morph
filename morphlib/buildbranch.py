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
# with this program.  If not, see <http://www.gnu.org/licenses/>.


import collections
import contextlib
import os
import urlparse

import cliapp
import fs.tempfs

import morphlib


class BuildBranchCleanupError(cliapp.AppException):
    def __init__(self, bb, exceptions):
        self.bb = bb
        self.exceptions = exceptions
        ex_nr = len(exceptions)
        cliapp.AppException.__init__(
            self, '%(ex_nr)d exceptions caught when cleaning up build branch'
                  % locals())


class BuildBranch(object):
    '''Represent the sources modified in a definitions repo.

    This provides the ability to add uncommitted changes to a temporary build
    branch.

    '''

    def __init__(self, build_ref_prefix, build_uuid, definitions_repo):
        self._build_uuid = build_uuid
        self._repo = definitions_repo
        self._cleanup = collections.deque()
        self._td = fs.tempfs.TempFS()
        self._register_cleanup(self._td.close)

        self._build_ref = os.path.join(
                'refs/heads', build_ref_prefix, self._repo.HEAD, build_uuid)

        self._index = self._repo.get_index(self._td.getsyspath('index'))
        self._index.set_to_tree(
                self._repo.resolve_ref_to_tree(self._repo.HEAD))

    def _register_cleanup(self, func, *args, **kwargs):
        self._cleanup.append((func, args, kwargs))

    def stage_uncommited_changes(self, add_cb):
        '''Add any uncommitted changes to a temporary GitIndex'''

        changed = [to_path for code, to_path, from_path
                   in self._index.get_uncommitted_changes()]
        if changed:
            add_cb(gd=self._repo, build_ref=self._build_ref,
                   changed=changed)
            self._index.add_files_from_working_tree(changed)
        return bool(changed)

    def commit_staged_changes(self, author_name, author_email, commit_cb):
        '''Commit changes in a temporary GitIndex to a temporary branch.

        `author_name` and `author_email` are required to construct the
        commit author info.

        A new commit is added to the temporary build branch of the
        definitions repository with:
        1.  the tree of anything currently in the temporary GitIndex.
            This is the same as the current commit on HEAD unless
            `stage_uncommited_changes` has been called.
        2.  the parent of the previous temporary commit, or the last
            commit of the working tree if there has been no previous
            commits
        3.  author and committer email as specified by `email`, author
            name of `name` and committer name of 'Morph (on behalf of
            `name`)'
        4.  commit message describing the current build using `uuid`

        '''
        commit_message = 'Morph build %s\n' % self._build_uuid
        committer_name = 'Morph (on behalf of %s)' % author_name
        committer_email = author_email
        with morphlib.branchmanager.LocalRefManager() as lrm:
            tree = self._index.write_tree()
            try:
                parent = self._repo.resolve_ref_to_commit(self._build_ref)
            except morphlib.gitdir.InvalidRefError:
                parent = self._repo.resolve_ref_to_commit(self._repo.HEAD)
            else:
                # Skip updating ref if we already have a temporary build
                # branch and have this tree on the branch
                if tree == self_.def_repo.resolve_ref_to_tree(
                        self._build_ref):
                    return

            commit_cb(gd=self._repo, build_ref=self._build_ref)
            commit = self._repo.commit_tree(
                                    tree, parent=parent,
                                    committer_name=committer_name,
                                    committer_email=committer_email,
                                    author_name=author_name,
                                    author_email=author_email,
                                    message=commit_message)
            try:
                old_commit = self._repo.resolve_ref_to_commit(self._build_ref)
            except morphlib.gitdir.InvalidRefError:
                lrm.add(self._repo, self._build_ref, commit)
            else:
                # NOTE: This will fail if build_ref pointed to a tag,
                # due to resolve_ref_to_commit returning the commit id
                # of tags, but since it's only morph that touches those
                # refs, it should not be a problem.
                lrm.update(self._repo, self._build_ref, commit, old_commit)
        self._register_cleanup(lrm.close)

    def needs_pushing(self):
        '''Work out if the temporary branch needs to be pushed

        NOTE: This assumes that the refs in the morphologies and the
        refs in the local checkouts match.

        '''

        head_ref = self._repo.HEAD
        upstream_ref = self._repo.get_upstream_of_branch(head_ref)
        if upstream_ref is None:
            return True
        head_sha1 = self._repo.resolve_ref_to_commit(head_ref)
        upstream_sha1 = self._repo.resolve_ref_to_commit(upstream_ref)
        return head_sha1 != upstream_sha1

    def push_build_branch(self, push_cb):
        '''Push the temporary build branch to the remote repository.
        '''

        with morphlib.branchmanager.RemoteRefManager(False) as rrm:
            remote = self._repo.get_remote('origin')
            refspec = morphlib.gitdir.RefSpec(self._build_ref)
            push_cb(gd=self._repo, build_ref=self._build_ref,
                    remote=remote, refspec=refspec)
            rrm.push(remote, refspec)
        self._register_cleanup(rrm.close)

    @property
    def repo_remote_url(self):
        '''URI of the repository that systems may be found in.'''

        return self._repo.remote_url

    @property
    def repo_local_url(self):
        return urlparse.urljoin('file://', self._repo.dirname)

    @property
    def head_commit(self):
        return self._repo.resolve_ref_to_commit(self._repo.HEAD)

    @property
    def head_ref(self):
        return self._repo.HEAD

    @property
    def build_commit(self):
        return self._repo.resolve_ref_to_commit(self.build_ref)

    @property
    def build_ref(self):
        '''Name of the ref of the repository that systems may be found in.'''
        return self._build_ref

    def close(self):
        '''Clean up any resources acquired during operation.'''
        # TODO: This is a common pattern for our context managers, we
        # could do with a way to share the common code. I suggest the
        # ExitStack from python3.4 or the contextlib2 module.
        exceptions = []
        while self._cleanup:
            func, args, kwargs = self._cleanup.pop()
            try:
                func(*args, **kwargs)
            except Exception as e:
                exceptions.append(e)
        if exceptions:
            raise BuildBranchCleanupError(self, exceptions)
