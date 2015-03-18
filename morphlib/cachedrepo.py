# Copyright (C) 2012-2015  Codethink Limited
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


import cliapp

import os
import tempfile

import morphlib


class CheckoutDirectoryExistsError(cliapp.AppException):

    def __init__(self, repo, target_dir):
        cliapp.AppException.__init__(
            self,
            'Checkout directory %s for repo %s already exists' %
            (target_dir, repo))


class CloneError(cliapp.AppException):

    def __init__(self, repo, target_dir):
        cliapp.AppException.__init__(
            self,
            'Failed to clone %s into %s' % (repo.original_name, target_dir))


class CopyError(cliapp.AppException):

    def __init__(self, repo, target_dir):
        cliapp.AppException.__init__(
            self,
            'Failed to copy %s into %s' % (repo.original_name, target_dir))


class CheckoutError(cliapp.AppException):

    def __init__(self, repo, ref, target_dir):
        cliapp.AppException.__init__(
            self,
            'Failed to check out ref %s in %s' % (ref, target_dir))


class UpdateError(cliapp.AppException):

    def __init__(self, repo):
        cliapp.AppException.__init__(
            self, 'Failed to update cached version of repo %s' % repo)


class CachedRepo(object):

    '''A locally cached Git repository with an origin remote set up.

    On instance of this class represents a locally cached version of a
    remote Git repository. This remote repository is set up as the
    'origin' remote.

    Cached repositories are bare mirrors of the upstream.  Locally created
    branches will be lost the next time the repository updates.

    CachedRepo objects can resolve Git refs into SHA1s. Given a SHA1
    ref, they can also be asked to return the contents of a file via the
    cat() method. They can furthermore check out the repository into
    a local directory using a SHA1 ref. Last but not least, any cached
    repo may be updated from it's origin remote using the update()
    method.

    '''

    def __init__(self, app, original_name, url, path):
        '''Creates a new CachedRepo for a repo name, URL and local path.'''

        self.app = app
        self.original_name = original_name
        self.url = url
        self.path = path
        self.is_mirror = not url.startswith('file://')
        self.already_updated = False

        self._gitdir = morphlib.gitdir.GitDirectory(path)

    def ref_exists(self, ref):  # pragma: no cover
        '''Returns True if the given ref exists in the repo'''
        return self._gitdir.ref_exists(ref)

    def resolve_ref_to_commit(self, ref):  # pragma: no cover
        '''Resolve a named ref to a commit SHA1.

        Raises gitdir.InvalidRefError if the ref does not exist.

        '''
        return self._gitdir.resolve_ref_to_commit(ref)

    def resolve_ref_to_tree(self, ref):  # pragma: no cover
        '''Resolve a named ref to a tree SHA1.

        Raises gitdir.InvalidRefError if the ref does not exist.

        '''
        return self._gitdir.resolve_ref_to_tree(ref)

    def read_file(self, filename, ref):  # pragma: no cover
        '''Attempts to read a file from a given ref.

        Raises a gitdir.InvalidRefError if the ref is not found in the
        repository. Raises an IOError if the requested file is not found in
        the ref.

        '''
        return self._gitdir.read_file(filename, ref)

    def tags_containing_sha1(self, ref):  # pragma: no cover
        '''Check whether given sha1 is contained in any tags

        Raises a gitdir.InvalidRefError if the ref is not found in the
        repository.  Raises gitdir.ExpectedSha1Error if the ref is not
        a sha1.

        '''
        return self._gitdir.tags_containing_sha1(ref)

    def branches_containing_sha1(self, ref):  # pragma: no cover
        '''Check whether given sha1 is contained in any branches

        Raises a gitdir.InvalidRefError if the ref is not found in the
        repository.  Raises gitdir.ExpectedSha1Error if the ref is not
        a sha1.

        '''
        return self._gitdir.branches_containing_sha1(ref)

    def list_files(self, ref, recurse=True):  # pragma: no cover
        '''Return filenames found in the tree pointed to by the given ref.

        Returns a gitdir.InvalidRefError if the ref is not found in the
        repository.

        '''
        return self._gitdir.list_files(ref, recurse)

    def clone_checkout(self, ref, target_dir):
        '''Clone from the cache into the target path and check out a given ref.

        Raises a CheckoutDirectoryExistsError if the target
        directory already exists. Raises a gitdir.InvalidRefError if the
        ref is not found in the repository. Raises a CheckoutError if
        something else goes wrong while copying the repository or checking
        out the SHA1 ref.

        '''

        if os.path.exists(target_dir):
            raise CheckoutDirectoryExistsError(self, target_dir)

        self._gitdir.resolve_ref_to_commit(ref)

        self._clone_into(target_dir, ref)

    def checkout(self, ref, target_dir):
        '''Unpacks the repository in a directory and checks out a commit ref.

        Raises an gitdir.InvalidRefError if the ref is not found in the
        repository. Raises a CopyError if something goes wrong with the copy
        of the repository. Raises a CheckoutError if something else goes wrong
        while copying the repository or checking out the SHA1 ref.

        '''

        if not os.path.exists(target_dir):
            os.mkdir(target_dir)

        # Note, we copy instead of cloning because it's much faster in the case
        # that the target is on a different filesystem from the cache. We then
        # take care to turn the copy into something as good as a real clone.
        self._copy_repository(self.path, target_dir)

        self._checkout_ref_in_clone(ref, target_dir)

    def extract_commit(self, ref, target_dir):
        '''Extract files from a given commit into target_dir.

        This is different to a 'checkout': a checkout assumes a working tree
        associated with a repository. Here, the repository is immutable (it's
        in the cache) and we just want to look at the files in a quick way
        (quicker than going 'git cat-file everything').

        This seems marginally quicker than doing a shallow clone. Running
        `morph list-artifacts` 10 times gave an average time of 1.334s
        using `git clone --depth 1` and an average time of 1.261s using
        this code.

        '''
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        with tempfile.NamedTemporaryFile() as index_file:
            index = self._gitdir.get_index(index_file=index_file.name)
            index.set_to_tree(ref)
            index.checkout(working_tree=target_dir)

    def requires_update_for_ref(self, ref):
        '''Returns False if there's no need to update this cached repo.

        If the ref points to a specific commit that's already available
        locally, there's never any need to update. If it's a named ref and this
        repo wasn't already updated in the lifetime of the current process,
        it's necessary to update.

        '''
        if not self.is_mirror:
            # Repos with file:/// URLs don't ever need updating.
            return False

        if self.already_updated:
            return False

        # Named refs that are valid SHA1s will confuse this code.
        ref_can_change = not morphlib.git.is_valid_sha1(ref)

        if ref_can_change or not self._gitdir.ref_exists(ref):
            return True
        else:
            return False

    def update(self):
        '''Updates the cached repository using its origin remote.

        Raises an UpdateError if anything goes wrong while performing
        the update.

        '''

        if not self.is_mirror:
            return

        try:
            self._gitdir.update_remotes(
                echo_stderr=self.app.settings['verbose'])
            self.already_updated = True
        except cliapp.AppException:
            raise UpdateError(self)

    def _runcmd(self, *args, **kwargs):  # pragma: no cover
        if not 'cwd' in kwargs:
            kwargs['cwd'] = self.path
        return self.app.runcmd(*args, **kwargs)

    def _clone_into(self, target_dir, ref):  # pragma: no cover
        '''Actually perform the clone'''
        try:
            morphlib.git.clone_into(self._runcmd, self.path, target_dir,
                                    ref)
        except cliapp.AppException:
            raise CloneError(self, target_dir)

    def _copy_repository(self, source_dir, target_dir):  # pragma: no cover
        try:
            morphlib.git.copy_repository(
                self._runcmd, source_dir, target_dir, self.is_mirror)
        except cliapp.AppException:
            raise CopyError(self, target_dir)

    def _checkout_ref_in_clone(self, ref, clone_dir):  # pragma: no cover
        # This is a separate GitDirectory instance. Don't confuse it with the
        # internal ._gitdir attribute!
        working_gitdir = morphlib.gitdir.GitDirectory(clone_dir)
        try:
            working_gitdir.checkout(ref)
        except cliapp.AppException as e:
            raise CheckoutError(self, ref, clone_dir)
        return working_gitdir

    def __str__(self):  # pragma: no cover
        return self.url
