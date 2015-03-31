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
import contextlib
import uuid
import logging

import morphlib


class BuildPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('build-morphology', self.build_morphology,
                                arg_synopsis='(REPO REF FILENAME)...')
        self.app.add_subcommand('build', self.build,
                                arg_synopsis='SYSTEM')
        self.app.add_subcommand('distbuild-morphology',
                                self.distbuild_morphology,
                                arg_synopsis='SYSTEM')
        self.app.add_subcommand('distbuild', self.distbuild,
                                arg_synopsis='SYSTEM')
        self.use_distbuild = False

    def disable(self):
        self.use_distbuild = False

    def distbuild_morphology(self, args):
        '''Distbuild a system, outside of a system branch.

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a branch or other commit reference in that repository.
        * `FILENAME` is a morphology filename at that ref.

        See 'help distbuild' and 'help build-morphology' for more information.

        '''

        addr = self.app.settings['controller-initiator-address']
        port = self.app.settings['controller-initiator-port']

        build_command = morphlib.buildcommand.InitiatorBuildCommand(
            self.app, addr, port)
        for repo_name, ref, filename in self.app.itertriplets(args):
            build_command.build(repo_name, ref, filename)

    def distbuild(self, args):
        '''Distbuild a system image in the current system branch

        Command line arguments:

        * `SYSTEM` is the name of the system to build.

        This command launches a distributed build, to use this command
        you must first set up a distbuild cluster.

        Artifacts produced during the build will be stored on your trove.

        Once the build completes you can use morph deploy to the deploy
        your system, the system artifact will be copied from your trove
        and cached locally.

        Example:

            morph distbuild devel-system-x86_64-generic.morph

        '''

        self.use_distbuild = True
        self.build(args)

    def build_morphology(self, args):
        '''Build a system, outside of a system branch.

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a branch or other commit reference in that repository.
        * `FILENAME` is a morphology filename at that ref.

        You probably want `morph build` instead. However, in some
        cases it is more convenient to not have to create a Morph
        workspace and check out the relevant system branch, and only
        just run the build. For those times, this command exists.

        This subcommand does not automatically commit changes to a
        temporary branch, so you can only build from properly committed
        sources that have been pushed to the git server.

        Example:

            morph build-morphology baserock:baserock/definitions \
                master devel-system-x86_64-generic.morph

        '''

        # Raise an exception if there is not enough space
        morphlib.util.check_disk_available(
            self.app.settings['tempdir'],
            self.app.settings['tempdir-min-space'],
            self.app.settings['cachedir'],
            self.app.settings['cachedir-min-space'])

        build_command = morphlib.buildcommand.BuildCommand(self.app)
        for repo_name, ref, filename in self.app.itertriplets(args):
            build_command.build(repo_name, ref, filename)

    def build(self, args):
        '''Build a system image in the current system branch

        Command line arguments:

        * `SYSTEM` is the name of the system to build.

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

            morph build devel-system-x86_64-generic.morph

        '''

        if len(args) != 1:
            raise cliapp.AppException('morph build expects exactly one '
                                      'parameter: the system to build')

        # Raise an exception if there is not enough space
        morphlib.util.check_disk_available(
            self.app.settings['tempdir'],
            self.app.settings['tempdir-min-space'],
            self.app.settings['cachedir'],
            self.app.settings['cachedir-min-space'])

        ws = morphlib.workspace.open('.')
        sb = morphlib.sysbranchdir.open_from_within('.')

        system_filename = morphlib.util.sanitise_morphology_path(args[0])
        system_filename = sb.relative_to_root_repo(system_filename)

        logging.debug('System branch is %s' % sb.root_directory)

        if self.use_distbuild:
            addr = self.app.settings['controller-initiator-address']
            port = self.app.settings['controller-initiator-port']

            build_command = morphlib.buildcommand.InitiatorBuildCommand(
                self.app, addr, port)
        else:
            build_command = morphlib.buildcommand.BuildCommand(self.app)

        if self.app.settings['local-changes'] == 'include':
            self._build_with_local_changes(build_command, sb, system_filename)
        else:
            self._build_local_commit(build_command, sb, system_filename)

    def _build_with_local_changes(self, build_command, sb, system_filename):
        '''Construct a branch including user's local changes, and build that.

        It is often a slow process to check all repos in the system branch for
        local changes. However, when using a distributed build cluster, all
        code being built must be pushed to the associated Trove, and it can be
        helpful to have this automated as part of the `morph build` command.

        '''
        build_uuid = uuid.uuid4().hex

        loader = morphlib.morphloader.MorphologyLoader()
        push = self.app.settings['push-build-branches']
        name = morphlib.git.get_user_name(self.app.runcmd)
        email = morphlib.git.get_user_email(self.app.runcmd)
        build_ref_prefix = self.app.settings['build-ref-prefix']

        self.app.status(msg='Looking for uncommitted changes (pass '
                            '--local-changes=ignore to skip)')

        self.app.status(msg='Collecting morphologies involved in '
                            'building %(system)s from %(branch)s',
                            chatty=True,
                            system=system_filename,
                            branch=sb.system_branch_name)

        bb = morphlib.buildbranch.BuildBranch(sb, build_ref_prefix)
        pbb = morphlib.buildbranch.pushed_build_branch(
                bb, loader=loader, changes_need_pushing=push,
                name=name, email=email, build_uuid=build_uuid,
                status=self.app.status)
        with pbb as (repo, commit, original_ref):
            build_command.build(repo, commit, system_filename,
                                original_ref=original_ref)

    def _build_local_commit(self, build_command, sb, system_filename):
        '''Build whatever commit the user has checked-out locally.

        This ignores any uncommitted changes. Also, if the user has a commit
        checked out locally that hasn't been pushed to the Trove that Morph is
        configured to work with, the build will fail in this sort of way:

            ERROR: Ref c55b853d92a52a5b5fe62edbfbf351169eb79c0a is an invalid
            reference for repo
            git://git.baserock.org/baserock/baserock/definitions

        The build process doesn't use the checked-out definitions repo at all,
        except to resolve the checked-out commit (HEAD). Instead, it uses the
        cached version of the definitions repo, updating the cache if
        necessary.

        We don't detect and warn the user about any uncommitted changes because
        doing so is slow when there are no changes (around 5 seconds on my
        machine for Baserock's definitions.git).

        '''
        root_repo_url = sb.get_config('branch.root')
        ref = sb.get_config('branch.name')

        definitions_repo_path = sb.get_git_directory_name(root_repo_url)
        definitions_repo = morphlib.gitdir.GitDirectory(definitions_repo_path)
        commit = definitions_repo.resolve_ref_to_commit(ref)

        build_command.build(root_repo_url, commit, system_filename)
