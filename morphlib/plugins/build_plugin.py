# Copyright (C) 2012-2016  Codethink Limited
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
import uuid

import cliapp

import morphlib


class ComponentNotInSystemError(morphlib.Error):

    def __init__(self, components, system):
        components = ', '.join(components)
        self.msg = ('Components %s are not in %s. Ensure you provided '
                    'component names rather than filenames.'
                    % (components, system))


class BuildPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('build', self.build,
                                arg_synopsis='SYSTEM [COMPONENT...]')
        self.app.add_subcommand('distbuild', self.distbuild,
                                arg_synopsis='SYSTEM [COMPONENT...]')
        self.app.add_subcommand('distbuild-start', self.distbuild_start,
                                arg_synopsis='SYSTEM [COMPONENT...]')
        self.allow_detach = False

    def disable(self):
        self.allow_detach = False

    def _cmd_usage(self, cmd):
        return 'usage: morph %s %s' % (cmd, self.app.cmd_synopsis[cmd])

    def distbuild(self, args):
        '''Distbuild a system image in the current definitions repo

        Command line arguments:

        * `SYSTEM` is the name of the system to build.
        * `COMPONENT...` is the names of one or more chunks or strata to
          build. If none are given then SYSTEM is built.

        This command launches a distributed build, to use this command
        you must first set up a distbuild cluster.

        Artifacts produced during the build will be stored on your trove.

        Once the build completes you can use morph deploy to the deploy
        your system, the system artifact will be copied from your trove
        and cached locally.

        Log information can be found in the current working directory, in
        directories called build-xx.

        If you do not have a persistent connection to the server on which
        the distbuild runs, consider using `morph distbuild-start` instead.

        Example:

            morph distbuild devel-system-x86_64-generic.morph

        '''
        MINARGS = 1

        if len(args) < MINARGS:
            raise cliapp.AppException(self._cmd_usage('distbuild'))

        definitions_repo = morphlib.definitions_repo.open(
            '.', search_for_root=True, app=self.app)

        filename = args[0]
        filename = morphlib.util.sanitise_morphology_path(filename)
        filename = definitions_repo.relative_path(filename, cwd='.')

        component_names = args[MINARGS:]

        if self.app.settings['local-changes'] == 'include':
            # Create a temporary branch with any local changes, and push it to
            # the shared Git server. This is a convenience for developers, who
            # otherwise need to commit and push each change manually in order
            # for distbuild to see it. It renders the build unreproducible, as
            # the branch is deleted after being built, so this feature should
            # only be used during development!
            build_uuid = uuid.uuid4().hex
            branch = definitions_repo.branch_with_local_changes(
                build_uuid, push=True)
            with branch as (repo_url, commit, original_ref):
                self._distbuild(repo_url, commit, filename,
                                original_ref=original_ref,
                                component_names=component_names)
        else:
            ref = definitions_repo.HEAD
            commit = definitions_repo.resolve_ref_to_commit(ref)
            self._distbuild(definitions_repo.remote_url, commit, filename,
                            original_ref=ref,
                            component_names=component_names)

    def distbuild_start(self, args):
        '''Distbuild a system image without a lasting client-server connection.

        This command launches a distributed build, and disconnects from the
        distbuild cluster once the build starts, leaving the build running
        remotely.

        The command will return a build-ID which can be used to cancel the
        distbuild via `morph distbuild-cancel`. Builds started in this manner
        can be found via `morph distbuild-list-jobs`

        See `morph help distbuild` for more information and example usage.

        '''

        MINARGS = 1

        if len(args) < MINARGS:
            raise cliapp.AppException(self._cmd_usage('distbuild-start'))

        self.allow_detach = True
        self.distbuild(args)

    def _distbuild(self, repo_url, commit, filename, original_ref=None,
                   component_names=[]):
        '''Request a distributed build of a given system definition.'''

        addr = self.app.settings['controller-initiator-address']
        port = self.app.settings['controller-initiator-port']

        build_command = morphlib.buildcommand.InitiatorBuildCommand(
            self.app, addr, port, allow_detach=self.allow_detach)
        build_command.build(
            repo_url, commit, filename, original_ref=original_ref,
            component_names=component_names)

    def build(self, args):
        '''Build a system image in the current definitions repo.

        Command line arguments:

        * `SYSTEM` is the filename of the system to build.
        * `COMPONENT...` is the names of one or more chunks or strata to
          build. If this is not given then the SYSTEM is built.

        This builds a system image, and any of its components that
        need building.  The system name is the basename of the system
        morphology, in the root repository of the current system branch,
        without the `.morph` suffix in the filename.

        The location of the resulting system image artifact is printed
        at the end of the build output.

        If the 'local-changes' setting is set to 'include', you do not need
        to commit your changes before building. Morph does that for you, in a
        temporary branch for each build. Note that any system produced this way
        will not be reproducible later on as the branch it is built from will
        have been deleted. Also note that Morph does not add untracked files to
        the temporary branch, only uncommitted changes to files git already
        knows about. You need to `git add` and commit each new file yourself.

        Example:

            morph build systems/devel-system-x86_64-generic.morph

        Partial build example:

            morph build systems/devel-system-x86_64-generic.morph \\
                build-essential

        '''
        MINARGS = 1

        if len(args) < MINARGS:
            raise cliapp.AppException(self._cmd_usage('build'))

        definitions_repo = morphlib.definitions_repo.open(
            '.', search_for_root=True, app=self.app)

        filename = args[0]
        filename = morphlib.util.sanitise_morphology_path(filename)
        filename = definitions_repo.relative_path(filename, cwd='.')
        component_names = args[MINARGS:]

        # Raise an exception if there is not enough space
        morphlib.util.check_disk_available(
            self.app.settings['tempdir'],
            self.app.settings['tempdir-min-space'],
            self.app.settings['cachedir'],
            self.app.settings['cachedir-min-space'])

        source_pool_context = definitions_repo.source_pool(
            definitions_repo.HEAD, filename)
        with source_pool_context as source_pool:
            self._build(source_pool, filename, component_names=component_names)

    def _find_artifacts(self, names, root_artifact):
        found = collections.OrderedDict()
        not_found = names
        for a in root_artifact.walk():
            name = a.source.morphology['name']
            if name in names and name not in found:
                found[name] = a
                not_found.remove(name)
        return found, not_found

    def _build(self, source_pool, filename, component_names=None):
        '''Perform a local build of a given system definition.

        If a set of components was given, only build those. Otherwise,
        build the whole system.

        '''
        bc = morphlib.buildcommand.BuildCommand(self.app)
        bc.validate_sources(source_pool)
        bc.source_pool = source_pool
        definitions_version = source_pool.definitions_version
        root = bc.resolve_artifacts(source_pool)
        if not component_names:
            component_names = [root.source.name]
        components, not_found = self._find_artifacts(component_names, root)
        if not_found:
            raise ComponentNotInSystemError(not_found, filename)
        for name, component in components.iteritems():
            component.build_env = root.build_env
            bc.build_in_order(component, definitions_version)
            self.app.status(msg='%(kind)s %(name)s is cached at %(path)s',
                            kind=component.source.morphology['kind'],
                            name=name,
                            path=bc.lac.artifact_filename(component))
