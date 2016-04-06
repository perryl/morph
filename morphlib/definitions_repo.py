# Copyright (C) 2015-2016  Codethink Limited
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


'''Handles the Git repository containing Baserock definitions.'''


import cliapp

import contextlib
import logging
import os
import urlparse
import uuid
import warnings

import morphlib
import gitdir


class DefinitionsRepoNotFound(cliapp.AppException):
    def __init__(self):
        cliapp.AppException.__init__(self,
            'This command must be run from inside a Git repository '
            'containing Baserock definitions.')


class FileOutsideRepo(cliapp.AppException):
    def __init__(self, path, repo):
        cliapp.AppException.__init__(self,
            'File %s is not in repo %s.' % (path, repo))


class DefinitionsRepo(gitdir.GitDirectory):
    '''Represents a definitions.git repo checked out locally.

    '''
    def __init__(self, path, search_for_root=False, allow_missing=False):
        morphlib.gitdir.GitDirectory.__init__(
            self, path, search_for_root=search_for_root,
            allow_missing=allow_missing)

    @property
    def HEAD(self):
        '''Return the ref considered to be HEAD of this definitions repo.

        In a normal Git checkout, this will return whatever ref is checked out
        as the working tree (HEAD, in Git terminology).

        '''
        return morphlib.gitdir.GitDirectory.HEAD.fget(self)

    @property
    def remote_url(self):
        '''Return the 'upstream' URL of this repo.'''

        return self.get_remote('origin').get_fetch_url()

    def branch_with_local_changes(self, build_uuid, push=True,
                                  build_ref_prefix=None,
                                  git_user_name=None, git_user_email=None,
                                  status_cb=lambda **kwargs: None):
        '''Yield a branch that includes the user's local changes to this repo.

        When operating on local repos, this isn't really necessary. But when
        doing distributed building, any local changes the user has made need
        to be pushed. As a convenience for the user, Morph supports creating
        temporary branches with their local changes and pushing them to the
        'origin' remote of the repo they are working in.

        If there are no local changes, there is no temporary branch created,
        and the function yields whatever branch was checked out.

        The 'git_user_name' and 'git_user_email' parameters are used when
        creating commits in the temporary branch. The 'build_ref_prefix' is
        prepended to the ref name of the temporary branch. Pushing is limited
        to only certain refs in some Git servers.

        '''

        status_cb(msg='Looking for uncommitted changes (pass '
                      '--local-changes=ignore to skip)')

        def report_add(gd, build_ref, changed):
            status_cb(msg='Creating temporary branch in %(dirname)s named '
                          '%(ref)s',
                      dirname=gd.dirname, ref=build_ref)

        def report_commit(gd, build_ref):
            status_cb(msg='Committing changes in %(dirname)s to %(ref)s',
                      dirname=gd.dirname, ref=build_ref, chatty=True)

        def report_push(gd, build_ref, remote, refspec):
            status_cb(msg='Pushing %(ref)s in %(dirname)s to %(remote)s',
                      ref=build_ref, dirname=gd.dirname,
                      remote=remote.get_push_url(), chatty=True)

        @contextlib.contextmanager
        def bbcm():
            with contextlib.closing(morphlib.buildbranch.BuildBranch(
                    build_ref_prefix, build_uuid, definitions_repo=self)) \
            as bb:
                changes_made = bb.stage_uncommited_changes(add_cb=report_add)
                unpushed = bb.needs_pushing()
                if not changes_made and not unpushed:
                    yield bb.repo_remote_url, bb.head_commit, bb.head_ref
                    return
                bb.commit_staged_changes(git_user_name, git_user_email,
                                         commit_cb=report_commit)
                if push:
                    repo_url = bb.repo_remote_url
                    bb.push_build_branch(push_cb=report_push)
                else:
                    repo_url = bb.repo_local_url
                yield repo_url, bb.build_commit, bb.build_ref
        return bbcm()

    @contextlib.contextmanager
    def source_pool(self, repo_cache, ref, system_filename,
                    include_local_changes=False, push_local_changes=False,
                    status_cb=None, build_ref_prefix=None,
                    git_user_name=None, git_user_email=None):
        '''Load the system defined in 'morph' and all the sources it contains.

        This is a context manager, because depending on the settings given it
        may create and push a temporary build branch. This is useful when there
        are local changes that you would like distributed build workers to
        build.

        If 'include_local_changes' is False, the on-disk definitions.git repo
        is used only to query the HEAD ref. Morph then looks for this ref in
        its local clone of that repo's 'origin' remote, which ensures that the
        changes it is building are pushed to the configured Git server (at
        least at time it is building them).

        When 'include_local_changes' is True, Morph will create a temporary
        branch in the repo including any local changes. If the definitions.git
        repo is inside an old-style Morph system branch, it will create
        temporary branches in all repos that have been marked with `morph
        edit`.  The branch is cleaned up when the context manager exits. The
        'user_name', 'user_email' and 'build_ref_prefix' settings must be
        passed if a temporary build branch is created.

        FIXME: if not inside an old-style Morph system branch, the temporary
        branch is redundant as Morph could just read the files from the disk
        as-is. This requires changes to SourceResolver before it is possible.

        The 'push_local_changes' option isn't much use. You probably want to
        use branch_with_local_changes() instead. It is present so that the
        `morph build` command continues to honour the 'push-build-branches'
        setting, but that was probably only useful for `morph distbuild` and
        that now uses branch_with_local_changes().

        The 'repo_cache' parameter is a morphlib.repocache.RepoCache instance.
        If update_gits=False is set for this repo cache, and one of the refs in
        the build graph is not available locally, you will see a
        morphlib.gitdir.InvalidRefError exception.

        The 'status_cb' function will be called if set to output progress and
        status messages to the user.

        The function yields a morphlib.srcpool.SourcePool instance, which is
        all you need to resolve cache keys, and construct a usable build graph.
        See morphlib.buildcommand.BuildCommand.resolve_artifacts() for a way
        of doing this.

        '''
        # FIXME: currently the way this function is implemented causes the
        # `deploy` command to re-create a temporary build branch for each
        # system that is deployed. This is a regression in terms of
        # performance. But it seems to me that the sourcepool object should
        # be able to contain multiple systems, and so the correct fix is to
        # extend this function to handle multiple systems, rather than split
        # up the 'process local changes' stage from the 'create source pool'
        # stage.
        if include_local_changes:
            build_uuid = uuid.uuid4().hex
            temporary_branch = DefinitionsRepo.branch_with_local_changes(
                self, build_uuid, push=push_local_changes,
                build_ref_prefix=build_ref_prefix, git_user_name=git_user_name,
                git_user_email=git_user_email, status_cb=status_cb)
            with temporary_branch as (repo_url, commit, original_ref):
                if status_cb:
                    status_cb(msg='Deciding on task order')

                yield morphlib.sourceresolver.create_source_pool(
                    repo_cache, repo_url, commit, [system_filename],
                    original_ref=original_ref, status_cb=status_cb)
        else:
            repo_url = self.remote_url
            commit = self.resolve_ref_to_commit(ref)

            if status_cb:
                status_cb(msg='Deciding on task order')

            try:
                yield morphlib.sourceresolver.create_source_pool(
                    repo_cache, repo_url, commit, [system_filename],
                    original_ref=ref, status_cb=status_cb)
            except morphlib.sourceresolver.InvalidDefinitionsRefError as e:
                raise cliapp.AppException(
                    'Commit %s wasn\'t found in the "origin" remote %s. '
                    'You either need to push your local commits on branch %s '
                    'to "origin", or use the --local-changes=include feature '
                    'of Morph.' % (e.ref, e.repo_url, ref))

    def get_version(self, mf=None):
        ''' Returns version of the definitions

        This will read the VERSION file, raising a Exception if the file
        is not found.

        '''
        if not mf:
            mf = morphlib.morphologyfinder.MorphologyFinder(self)
        try:
            version_text = mf.read_file('VERSION')
        except IOError:
            raise morphlib.definitions_version.VersionFileNotFound()
        return  morphlib.definitions_version.check_version_file(version_text)

    def get_morphology_loader(self):
        '''Return a MorphologyLoader instance.

        This may read the VERSION and DEFAULTS file and pass appropriate
        information to the MorphologyLoader constructor.

        '''
        mf = morphlib.morphologyfinder.MorphologyFinder(self)

        version = self.get_version(mf)

        defaults_text = mf.read_file('DEFAULTS', allow_missing=True)
        if defaults_text is None:
            warnings.warn("No DEFAULTS file found.")

        defaults = morphlib.defaults.Defaults(version,
                                              text=defaults_text)

        loader = morphlib.morphloader.MorphologyLoader(
            predefined_build_systems=defaults.build_systems())

        return loader

    def load_all_morphologies(self, loader=None):
        loader = loader or self.get_morphology_loader()

        mf = morphlib.morphologyfinder.MorphologyFinder(self)
        for filename in (f for f in mf.list_morphologies()
                         if not self.is_symlink(f)):
            text = mf.read_file(filename)
            m = loader.load_from_string(text, filename=filename)
            m.repo_url = self.remote_url
            m.ref = self.HEAD
            yield m

    def relative_path(self, path, cwd='.'):
        '''Make 'path' relative to the top directory of this repo.

        If 'path' is a relative path, it is taken to be relative to the
        current working directory. Thus, the result of this function will
        be different depending on the value of os.getcwd().

        If the given path is outside the repo, a PathOutsideRepo exception
        is raised.

        '''
        def path_is_outside_repo(path):
            return path.split(os.sep, 1)[0] == '..'

        absolute_path = os.path.join(cwd, os.path.abspath(path))
        repo_relative_path = os.path.relpath(absolute_path, self.dirname)

        if path_is_outside_repo(repo_relative_path):
            raise FileOutsideRepo(repo_relative_path, self)

        return repo_relative_path

    def relative_path_to_chunk(self, repo_url):
        '''Return a sensible directory to check out repo_url.

        This will be a path in the directory that contains this definitions
        repo, with its name based on 'repo_url'.

        '''
        # Parse the URL. If the path component is absolute, we assume
        # it's a real URL; otherwise, an aliased URL.
        parts = urlparse.urlparse(repo_url)

        # Remove .git suffix, if any.
        path = parts.path
        if path.endswith('.git'):
            path = path[:-len('.git')]

        relative = os.path.basename(parts.path)

        # Replace colons with slashes.
        relative = '/'.join(relative.split(':'))

        # Remove anyleading slashes, or os.path.join below will only
        # use the relative part (since it's absolute, not relative).
        relative = relative.lstrip('/')

        return os.path.join(os.path.dirname(self.dirname), relative)


class DefinitionsRepoWithApp(DefinitionsRepo):
    '''Wrapper class for DefinitionsRepo that understands Morph settings.

    The DefinitionsRepo class does not require a morphlib.app.Application
    instance to use it. However, this means you need to pass quite a lot
    of parameters in. Code inside Morph can use this class instead to save
    duplicating code.

    '''
    def __init__(self, app, *args, **kwargs):
        DefinitionsRepo.__init__(self, *args, **kwargs)
        self.app = app

        self._git_user_name = morphlib.git.get_user_name(app.runcmd)
        self._git_user_email = morphlib.git.get_user_email(app.runcmd)

        self.repo_cache = morphlib.util.new_repo_cache(self.app)

    def branch_with_local_changes(self, uuid, push=False):
        '''Equivalent to DefinitionsRepo.branch_with_local_changes().'''

        return DefinitionsRepo.branch_with_local_changes(
            self, uuid,
            push=(push or self.app.settings['push-build-branches']),
            build_ref_prefix=self.app.settings['build-ref-prefix'],
            git_user_name=self._git_user_name,
            git_user_email=self._git_user_email,
            status_cb=self.app.status)

    def source_pool(self, ref, system_filename):
        '''Equivalent to DefinitionsRepo.source_pool().'''

        local_changes = self.app.settings['local-changes']
        return DefinitionsRepo.source_pool(
            self, self.repo_cache, ref, system_filename,
            include_local_changes=(local_changes == 'include'),
            push_local_changes=self.app.settings['push-build-branches'],
            build_ref_prefix=self.app.settings['build-ref-prefix'],
            git_user_name=self._git_user_name,
            git_user_email=self._git_user_email,
            status_cb=self.app.status)

def _local_definitions_repo(path, search_for_root, app=None):
    '''Open a local Git repo containing Baserock definitions, at 'path'.

    Raises morphlib.gitdir.NoGitRepoError if there is no repo found at 'path'.

    '''
    if app:
        gitdir = morphlib.definitions_repo.DefinitionsRepoWithApp(
            app, path, search_for_root=search_for_root)
    else:
        gitdir = morphlib.definitions_repo.DefinitionsRepo(
            path, search_for_root=search_for_root)
    return gitdir


def open(path, search_for_root=False, app=None):
    '''Open the definitions.git repo at 'path'.

    Returns a DefinitionsRepo instance.

    If 'search_for_root' is True, this function will traverse up from 'path'
    to find a .git directory, and assume that is the top of the Git repository.
    If you are trying to find the repo based on the current working directory,
    you should set this to True. If you are trying to find the repo based on a
    path entered manually by the user, you may want to set this to False to
    avoid confusion.

    '''

    try:
        definitions_repo = _local_definitions_repo(
            path, search_for_root=search_for_root, app=app)
    except morphlib.gitdir.NoGitRepoError:
        raise DefinitionsRepoNotFound()
    logging.info('Opened definitions repo %s', definitions_repo)
    return definitions_repo
