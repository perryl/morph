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
import urlparse
import uuid
import logging

import morphlib


class SystemBranchDirectoryAlreadyExists(morphlib.Error):

    def __init__(self, root_directory):
        self.msg = (
            "%s: File exists" % 
            root_directory)


class NotInSystemBranch(morphlib.Error):

    def __init__(self, dirname):
        self.msg = (
            "Can't find the system branch directory.\n"
            "Morph must be built and deployed within "
            "the system branch checkout.")


class SystemBranchDirectory(object):

    '''A directory containing a checked out system branch.'''

    def __init__(self,
        root_directory, root_repository_url, system_branch_name):
        self.root_directory = os.path.abspath(root_directory)
        self.root_repository_url = root_repository_url
        self.system_branch_name = system_branch_name

    @property
    def _magic_path(self):
        return os.path.join(self.root_directory, '.morph-system-branch')

    @property
    def _config_path(self):
        return os.path.join(self._magic_path, 'config')

    def set_config(self, key, value):
        '''Set a configuration key/value pair.'''
        morphlib.git.gitcmd(cliapp.runcmd, 'config', '-f',
                            self._config_path, key, value)

    def get_config(self, key):
        '''Get a configuration value for a given key.'''
        value = morphlib.git.gitcmd(cliapp.runcmd, 'config', '-f',
                                    self._config_path, key)
        return value.strip()

    def _find_git_directory(self, repo_url):
        for gd in self.list_git_directories():
            if gd.get_config('morph.repository') == repo_url:
                return gd.dirname
        return None

    def _fabricate_git_directory_name(self, repo_url):
        # Parse the URL. If the path component is absolute, we assume
        # it's a real URL; otherwise, an aliased URL.
        parts = urlparse.urlparse(repo_url)

        if os.path.isabs(parts.path):
            # Remove .git suffix, if any.
            path = parts.path
            if path.endswith('.git'):
                path = path[:-len('.git')]

            # Add the domain name etc (netloc). Ignore any other parts.
            # Note that we _know_ the path starts with a slash, so we avoid
            # adding one here.
            relative = '%s%s' % (parts.netloc, path)
        else:
            relative = repo_url

        # Replace colons with slashes.
        relative = '/'.join(relative.split(':'))

        # Remove anyleading slashes, or os.path.join will only
        # use the relative part (since it's absolute, not relative).
        relative = relative.lstrip('/')

        return relative

    def relative_to_root_repo(self, path, root_repo_url): # pragma: no cover
        ''' Takes a path and the root repo's url and returns a path
            relative to the root repo'''

        root_repo_dir = self._fabricate_git_directory_name(root_repo_url)

        commonprefix = os.path.commonprefix([self.root_directory,
                                            '/' + root_repo_dir])

        if commonprefix == self.root_directory:
            root_repo_dir = os.path.join('/', root_repo_dir)
        else:
            root_repo_dir = os.path.join(self.root_directory, root_repo_dir)

        logging.debug('Repo with url %s is found at %s'
                      % (root_repo_url, root_repo_dir))
        return os.path.relpath(os.path.abspath(path), root_repo_dir)

    def get_git_directory_name(self, repo_url):
        '''Return directory pathname for a given git repository.

        If the repository has already been cloned, then it returns the
        path to that, if not it will fabricate a path based on the url.

        If the URL is a real one (not aliased), the schema and leading //
        are removed from it, as is a .git suffix.

        Any colons in the URL path or network location are replaced
        with slashes, so that directory paths do not contain colons.
        This avoids problems with PYTHONPATH, PATH, and other things
        that use colon as a separator.

        '''
        found_repo = self._find_git_directory(repo_url)

        if not found_repo:
            git_dir_name = self._fabricate_git_directory_name(repo_url)
            return os.path.join(self.root_directory, git_dir_name)
        return found_repo

    def get_filename(self, repo_url, relative):
        '''Return full pathname to a file in a checked out repository.

        This is a convenience function.

        '''

        return os.path.join(self.get_git_directory_name(repo_url), relative)

    def clone_cached_repo(self, cached_repo, checkout_ref):
        '''Clone a cached git repository into the system branch directory.

        The cloned repository will NOT have the system branch's git branch
        checked out: instead, checkout_ref is checked out (this is for
        backwards compatibility with older implementation of "morph
        branch"; it may change later). The system branch's git branch
        is NOT created: the caller will need to do that. Submodules are
        NOT checked out.

        The "origin" remote will be set to follow the cached repository's
        upstream. Remotes are not updated.

        '''

        # Do the clone.
        dirname = self.get_git_directory_name(cached_repo.original_name)
        gd = morphlib.gitdir.clone_from_cached_repo(
            cached_repo, dirname, checkout_ref)

        # Remember the repo name we cloned from in order to be able
        # to identify the repo again later using the same name, even
        # if the user happens to rename the directory.
        gd.set_config('morph.repository', cached_repo.original_name)

        # Create a UUID for the clone. We will use this for naming
        # temporary refs, e.g. for building.
        gd.set_config('morph.uuid', uuid.uuid4().hex)

        # Configure the "origin" remote to use the upstream git repository,
        # and not the locally cached copy.
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            cached_repo.app.settings['repo-alias'])
        remote = gd.get_remote('origin')
        remote.set_fetch_url(resolver.pull_url(cached_repo.url))
        gd.set_config(
            'url.%s.pushInsteadOf' %
                resolver.push_url(cached_repo.original_name),
            resolver.pull_url(cached_repo.url))

        return gd

    def list_git_directories(self):
        '''List all git directories in a system branch directory.

        The list will contain zero or more GitDirectory objects.

        '''

        return (morphlib.gitdir.GitDirectory(dirname)
                for dirname in
                morphlib.util.find_leaves(self.root_directory, '.git'))

    # Not covered by unit tests, since testing the functionality spans
    # multiple modules and only tests useful output with a full system
    # branch, so it is instead covered by integration tests.
    def load_all_morphologies(self, loader): # pragma: no cover
        gd_name = self.get_git_directory_name(self.root_repository_url)
        gd = morphlib.gitdir.GitDirectory(gd_name)
        mf = morphlib.morphologyfinder.MorphologyFinder(gd)
        for filename in (f for f in mf.list_morphologies()
                         if not gd.is_symlink(f)):
            text = mf.read_morphology(filename)
            m = loader.load_from_string(text, filename=filename)
            m.repo_url = self.root_repository_url
            m.ref = self.system_branch_name
            yield m


def create(root_directory, root_repository_url, system_branch_name):
    '''Create a new system branch directory on disk.

    Return a SystemBranchDirectory object that represents the directory.

    The directory MUST NOT exist already. If it does,
    SystemBranchDirectoryAlreadyExists is raised.

    Note that this does NOT check out the root repository, or do any
    other git cloning.

    '''

    if os.path.exists(root_directory):
        raise SystemBranchDirectoryAlreadyExists(root_directory)

    magic_dir = os.path.join(root_directory, '.morph-system-branch')
    os.makedirs(root_directory)
    os.mkdir(magic_dir)

    sb = SystemBranchDirectory(
        root_directory, root_repository_url, system_branch_name)
    sb.set_config('branch.name', system_branch_name)
    sb.set_config('branch.root', root_repository_url)
    sb.set_config('branch.uuid', uuid.uuid4().hex)

    return sb


def open(root_directory):
    '''Open an existing system branch directory.'''

    # Ugly hack follows.
    sb = SystemBranchDirectory(root_directory, None, None)
    root_repository_url = sb.get_config('branch.root')
    system_branch_name = sb.get_config('branch.name')

    return SystemBranchDirectory(
        root_directory, root_repository_url, system_branch_name)


def open_from_within(dirname):
    '''Open a system branch directory, given any directory.

    The directory can be within the system branch root directory,
    or it can be a parent, in some cases. If each parent on the
    path from dirname to the system branch root directory has no
    siblings, this function will find it.

    '''

    root_directory = morphlib.util.find_root(
        dirname, '.morph-system-branch')
    if root_directory is None:
        root_directory = morphlib.util.find_leaf(
            dirname, '.morph-system-branch')
    if root_directory is None:
        raise NotInSystemBranch(dirname)
    return morphlib.sysbranchdir.open(root_directory)

