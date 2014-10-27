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
    '''Represent the sources modified in a system branch.

    This is an abstraction on top of SystemBranchDirectories, providing
    the ability to add uncommitted changes to the temporary build branch,
    push temporary build branches and retrieve the correct repository
    URI and ref to build the system.

    '''

    # TODO: This currently always uses the temporary build ref. It
    # would be better to not use local repositories and temporary refs,
    # so building from a workspace appears to be identical to using
    # `morph build-morphology`
    def __init__(self, sb, build_ref_prefix):

        self._sb = sb

        self._cleanup = collections.deque()
        self._to_push = {}
        self._td = fs.tempfs.TempFS()
        self._register_cleanup(self._td.close)

        self._branch_root = sb.get_config('branch.root')
        branch_uuid = sb.get_config('branch.uuid')

        for gd in sb.list_git_directories():
            try:
                repo_uuid = gd.get_config('morph.uuid')
            except cliapp.AppException:
                # Not a repository cloned by morph, ignore
                break
            build_ref = os.path.join('refs/heads', build_ref_prefix,
                                     branch_uuid, repo_uuid)
            # index is commit of workspace + uncommitted changes may want
            # to change to use user's index instead of user's commit,
            # so they can add new files first
            index = gd.get_index(self._td.getsyspath(repo_uuid))
            index.set_to_tree(gd.resolve_ref_to_tree(gd.HEAD))
            self._to_push[gd] = (build_ref, index)

        rootinfo, = ((gd, index) for gd, (build_ref, index)
                     in self._to_push.iteritems()
                     if gd.get_config('morph.repository') == self._branch_root)
        self._root, self._root_index = rootinfo

    def _register_cleanup(self, func, *args, **kwargs):
        self._cleanup.append((func, args, kwargs))

    def add_uncommitted_changes(self, add_cb=lambda **kwargs: None):
        '''Add any uncommitted changes to temporary build GitIndexes'''
        changes_made = False
        for gd, (build_ref, index) in self._to_push.iteritems():
            changed = [to_path for code, to_path, from_path
                       in index.get_uncommitted_changes()]
            if not changed:
                continue
            add_cb(gd=gd, build_ref=gd, changed=changed)
            changes_made = True
            index.add_files_from_working_tree(changed)
        return changes_made

    @staticmethod
    def _hash_morphologies(gd, morphologies, loader):
        '''Hash morphologies and return object info'''
        for morphology in morphologies:
            loader.unset_defaults(morphology)
            sha1 = gd.store_blob(loader.save_to_string(morphology))
            yield 0100644, sha1, morphology.filename

    def inject_build_refs(self, loader, use_local_repos,
                          inject_cb=lambda **kwargs: None):
        '''Update system and stratum morphologies to point to our branch.

        For all edited repositories, this alter the temporary GitIndex
        of the morphs repositories to point their temporary build branch
        versions.

        `loader` is a MorphologyLoader that is used to convert morphology
        files into their in-memory representations and back again.

        '''
        root_repo = self._root.get_config('morph.repository')
        root_ref = self._root.HEAD
        morphs = morphlib.morphset.MorphologySet()
        for morph in self._sb.load_all_morphologies(loader):
            morphs.add_morphology(morph)

        sb_info = {}
        for gd, (build_ref, index) in self._to_push.iteritems():
            repo, ref = gd.get_config('morph.repository'), gd.HEAD
            sb_info[repo, ref] = (gd, build_ref)

        def filter(m, kind, spec):
            return (spec.get('repo'), spec.get('ref')) in sb_info
        def process(m, kind, spec):
            repo, ref = spec['repo'], spec['ref']
            gd, build_ref = sb_info[repo, ref]
            if (repo, ref) == (root_repo, root_ref):
                spec['repo'] = None
                spec['ref'] = None
                return True
            if use_local_repos:
                spec['repo'] = urlparse.urljoin('file://', gd.dirname)
            spec['ref'] = build_ref
            return True

        morphs.traverse_specs(process, filter)

        if any(m.dirty for m in morphs.morphologies):
            inject_cb(gd=self._root)

        # TODO: Prevent it hashing unchanged morphologies, while still
        # hashing uncommitted ones.
        self._root_index.add_files_from_index_info(
            self._hash_morphologies(self._root, morphs.morphologies, loader))

    def update_build_refs(self, name, email, uuid,
                          commit_cb=lambda **kwargs: None):
        '''Commit changes in temporary GitIndexes to temporary branches.

        `name` and `email` are required to construct the commit author info.
        `uuid` is used to identify each build uniquely and is included
        in the commit message.

        A new commit is added to the temporary build branch of each of
        the repositories in the SystemBranch with:
        1.  The tree of anything currently in the temporary GitIndex.
            This is the same as the current commit on HEAD unless
            `add_uncommitted_changes` or `inject_build_refs` have
            been called.
        2.  the parent of the previous temporary commit, or the last
            commit of the working tree if there has been no previous
            commits
        3.  author and committer email as specified by `email`, author
            name of `name` and committer name of 'Morph (on behalf of
            `name`)'
        4.  commit message describing the current build using `uuid`

        '''
        commit_message = 'Morph build %s\n\nSystem branch: %s\n' % \
            (uuid, self._sb.system_branch_name)
        author_name = name
        committer_name = 'Morph (on behalf of %s)' % name
        author_email = committer_email = email

        with morphlib.branchmanager.LocalRefManager() as lrm:
            for gd, (build_ref, index) in self._to_push.iteritems():
                tree = index.write_tree()
                try:
                    parent = gd.resolve_ref_to_commit(build_ref)
                except morphlib.gitdir.InvalidRefError:
                    parent = gd.resolve_ref_to_commit(gd.HEAD)
                else:
                    # Skip updating ref if we already have a temporary
                    # build branch and have this tree on the branch
                    if tree == gd.resolve_ref_to_tree(build_ref):
                        continue

                commit_cb(gd=gd, build_ref=build_ref)

                commit = gd.commit_tree(tree, parent=parent,
                                        committer_name=committer_name,
                                        committer_email=committer_email,
                                        author_name=author_name,
                                        author_email=author_email,
                                        message=commit_message)
                try:
                    old_commit = gd.resolve_ref_to_commit(build_ref)
                except morphlib.gitdir.InvalidRefError:
                    lrm.add(gd, build_ref, commit)
                else:
                    # NOTE: This will fail if build_ref pointed to a tag,
                    #       due to resolve_ref_to_commit returning the
                    #       commit id of tags, but since it's only morph
                    #       that touches those refs, it should not be
                    #       a problem.
                    lrm.update(gd, build_ref, commit, old_commit)

    def get_unpushed_branches(self):
        '''Work out which, if any, local branches need to be pushed to build

        NOTE: This assumes that the refs in the morphologies and the
        refs in the local checkouts match.

        '''
        for gd, (build_ref, index) in self._to_push.iteritems():
            head_ref = gd.HEAD
            upstream_ref = gd.get_upstream_of_branch(head_ref)
            if upstream_ref is None:
                yield gd
                continue
            head_sha1 = gd.resolve_ref_to_commit(head_ref)
            upstream_sha1 = gd.resolve_ref_to_commit(upstream_ref)
            if head_sha1 != upstream_sha1:
                yield gd

    def push_build_branches(self, push_cb=lambda **kwargs: None):
        '''Push all temporary build branches to the remote repositories.
        '''
        with morphlib.branchmanager.RemoteRefManager(False) as rrm:
            for gd, (build_ref, index) in self._to_push.iteritems():
                remote = gd.get_remote('origin')
                refspec = morphlib.gitdir.RefSpec(build_ref)
                push_cb(gd=gd, build_ref=build_ref,
                        remote=remote, refspec=refspec)
                rrm.push(remote, refspec)
        self._register_cleanup(rrm.close)

    @property
    def root_repo_url(self):
        '''URI of the repository that systems may be found in.'''
        return self._sb.get_config('branch.root')

    @property
    def root_ref(self):
        return self._sb.get_config('branch.name')

    @property
    def root_commit(self):
        return self._root.resolve_ref_to_commit(self.root_ref)

    @property
    def root_local_repo_url(self):
        return urlparse.urljoin('file://', self._root.dirname)

    @property
    def root_build_ref(self):
        '''Name of the ref of the repository that systems may be found in.'''
        build_ref, index = self._to_push[self._root]
        return build_ref

    @property
    def root_build_commit(self):
        return self._root.resolve_ref_to_commit(self.root_build_ref)

    def close(self):
        '''Clean up any resources acquired during operation.'''
        # TODO: This is a common pattern for our context managers,
        # we could do with a way to share the common code. I suggest the
        # ExitStack from python3.4 or the contextlib2 module.
        exceptions = []
        while self._cleanup:
            func, args, kwargs = self._cleanup.pop()
            try:
                func(*args, **kwargs)
            except Exception, e:
                exceptions.append(e)
        if exceptions:
            raise BuildBranchCleanupError(self, exceptions)


@contextlib.contextmanager
def pushed_build_branch(bb, loader, changes_need_pushing, name, email,
                        build_uuid, status):
    with contextlib.closing(bb) as bb:
        def report_add(gd, build_ref, changed):
            status(msg='Adding uncommitted changes '\
                           'in %(dirname)s to %(ref)s',
                       dirname=gd.dirname, ref=build_ref, chatty=True)
        changes_made = bb.add_uncommitted_changes(add_cb=report_add)
        unpushed = any(bb.get_unpushed_branches())

        if not changes_made and not unpushed:
            # We resolve the system branch ref to the commit SHA1 here, so that
            # the build uses whatever commit the user's copy of the root repo
            # considers the head of that branch to be. If we returned a named
            # ref, we risk building what the remote considers the head of that
            # branch to be instead, and we also trigger a needless update in
            # the cached copy of the root repo.
            yield bb.root_repo_url, bb.root_commit, bb.root_ref
            return

        def report_inject(gd):
            status(msg='Injecting temporary build refs '\
                           'into morphologies in %(dirname)s',
                       dirname=gd.dirname, chatty=True)
        bb.inject_build_refs(loader=loader,
                             use_local_repos=not changes_need_pushing,
                             inject_cb=report_inject)

        def report_commit(gd, build_ref):
            status(msg='Committing changes in %(dirname)s '\
                           'to %(ref)s',
                       dirname=gd.dirname, ref=build_ref,
                       chatty=True)
        bb.update_build_refs(name, email, build_uuid,
                             commit_cb=report_commit)

        if changes_need_pushing:
            def report_push(gd, build_ref, remote, refspec):
                status(msg='Pushing %(ref)s in %(dirname)s '\
                               'to %(remote)s',
                           ref=build_ref, dirname=gd.dirname,
                           remote=remote.get_push_url(), chatty=True)
            bb.push_build_branches(push_cb=report_push)

            yield bb.root_repo_url, bb.root_build_commit, bb.root_build_ref
        else:
            yield (bb.root_local_repo_url, bb.root_build_commit,
                                           bb.root_build_ref)
