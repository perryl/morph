# Copyright (C) 2012,2013,2014  Codethink Limited
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


import cliapp
import contextlib
import uuid

import morphlib


class BuildPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('build-morphology', self.build_morphology,
                                arg_synopsis='(REPO REF FILENAME)...')
        self.app.add_subcommand('build', self.build,
                                arg_synopsis='SYSTEM')
        self.app.add_subcommand('distbuild', self.distbuild,
                                arg_synopsis='SYSTEM')
        self.use_distbuild = False

    def disable(self):
        self.use_distbuild = False

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

            morph distbuild devel-system-x86_64-generic

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

            morph build-morphology baserock:baserock/morphs \
                master devel-system-x86_64-generic

        '''

        # Raise an exception if there is not enough space
        morphlib.util.check_disk_available(
            self.app.settings['tempdir'],
            self.app.settings['tempdir-min-space'],
            self.app.settings['cachedir'],
            self.app.settings['cachedir-min-space'])

        build_command = morphlib.buildcommand.BuildCommand(self.app)
        build_command.build(args)

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

        You do not need to commit your changes before building, Morph
        does that for you, in a temporary branch for each build. However,
        note that Morph does not untracked files to the temporary branch,
        only uncommitted changes to files git already knows about. You
        need to `git add` and commit each new file yourself.

        Example:

            morph build devel-system-x86_64-generic

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

        system_name = morphlib.util.strip_morph_extension(args[0])

        ws = morphlib.workspace.open('.')
        sb = morphlib.sysbranchdir.open_from_within('.')

        build_uuid = uuid.uuid4().hex

        if self.use_distbuild:
            addr = self.app.settings['controller-initiator-address']
            port = self.app.settings['controller-initiator-port']

            build_command = morphlib.buildcommand.InitiatorBuildCommand(
                self.app, addr, port)
        else:
            build_command = morphlib.buildcommand.BuildCommand(self.app)

        loader = morphlib.morphloader.MorphologyLoader()
        push = self.app.settings['push-build-branches']
        name = morphlib.git.get_user_name(self.app.runcmd)
        email = morphlib.git.get_user_email(self.app.runcmd)
        build_ref_prefix = self.app.settings['build-ref-prefix']

        self.app.status(msg='Starting build %(uuid)s', uuid=build_uuid)
        self.app.status(msg='Collecting morphologies involved in '
                            'building %(system)s from %(branch)s',
                            system=system_name, branch=sb.system_branch_name)

        bb = morphlib.buildbranch.BuildBranch(sb, build_ref_prefix,
                                              push_temporary=push)
        with contextlib.closing(bb) as bb:

            for gd, build_ref in bb.add_uncommitted_changes():
                self.app.status(msg='Adding uncommitted changes '\
                                    'in %(dirname)s to %(ref)s',
                                dirname=gd.dirname, ref=build_ref, chatty=True)

            for gd in bb.inject_build_refs(loader):
                self.app.status(msg='Injecting temporary build refs '\
                                    'into morphologies in %(dirname)s',
                                dirname=gd.dirname, chatty=True)

            for gd, build_ref in bb.update_build_refs(name, email, build_uuid):
                self.app.status(msg='Committing changes in %(dirname)s '\
                                    'to %(ref)s',
                                dirname=gd.dirname, ref=build_ref, chatty=True)

            for gd, build_ref, remote in bb.push_build_branches():
                self.app.status(msg='Pushing %(ref)s in %(dirname)s '\
                                    'to %(remote)s',
                                ref=build_ref, dirname=gd.dirname,
                                remote=remote.get_push_url(), chatty=True)

            build_command.build([bb.root_repo_url,
                                 bb.root_ref,
                                 system_name])
