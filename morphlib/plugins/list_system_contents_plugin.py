# Copyright (C) 2014 Codethink Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import cliapp
import contextlib
import fnmatch
import tarfile
import uuid

import morphlib

import pdb


class ListSystemContentsPlugin(cliapp.Plugin):
    '''Annotate the root file system for a given system.

    Command line arguments:

    * `SYSTEM` is the name of a system

    '''

    def enable(self):
        self.app.add_subcommand(
            'list-system-contents', self.list_system_contents,
            arg_synopsis='SYSTEM')

    def disable(self):
        pass

    def commit_uncommitted_changes(self, system_branch):
        # from morphlib/plugins/build_plugin.py
        build_uuid = uuid.uuid4().hex

        build_ref_prefix = self.app.settings['build-ref-prefix'] or 'build/'

        self.app.status(msg="Creating temporary build branch")

        build_branch = morphlib.buildbranch.BuildBranch(
                system_branch, build_ref_prefix, push_temporary=False)
        with contextlib.closing(build_branch) as build_branch:
            # These functions return impure generators to do their work
            # rather than actually doing what their names suggest.
            list(build_branch.add_uncommitted_changes())

            loader = morphlib.morphloader.MorphologyLoader()
            list(build_branch.inject_build_refs(loader))

            name = morphlib.git.get_user_name(self.app.runcmd)
            email = morphlib.git.get_user_email(self.app.runcmd)
            list(build_branch.update_build_refs(name, email, build_uuid))

        return build_branch

    def list_system_contents(self, args):
        if len(args) != 1:
            raise morphlib.Error("Usage: morph-search-file SYSTEM")

        system_name = morphlib.util.strip_morph_extension(args[0])

        workspace = morphlib.workspace.open('.')
        system_branch = morphlib.sysbranchdir.open_from_within('.')

        build_branch = self.commit_uncommitted_changes(system_branch)

        build_command = morphlib.buildcommand.BuildCommand(self.app)

        source_pool = build_command.create_source_pool(
                build_branch.root_repo_url,
                build_branch.root_ref,
                system_name + '.morph')
        root_artifact = build_command.resolve_artifacts(source_pool)

        build_command.build_in_order(root_artifact)

        files = dict()
        for artifact in root_artifact.walk():
            if artifact.source.morphology['kind'] != 'chunk':
                continue
            try:
                artifact_file = build_command.lac.get(artifact)
                contents = morphlib.builder2.get_chunk_files(artifact_file)
                for path in contents:
                    abs_path = '/%s' % path
                    if abs_path in files:
                        print 'WARNING: file %s is in more than one chunk!' % abs_path
                    files[abs_path] = artifact
                files.update('/%s' % p for p in contents)
            except tarfile.ReadError:
                print "Read error for %s" % artifact.name

        def get_stratum_for_chunk(chunk):
            for artifact in chunk.dependents:
                # Currently it's safe to assume that only the containing
                # stratum will be in the chunk artifact's list of dependents.
                if artifact.source.morphology['kind'] == 'stratum':
                    return artifact
            raise ValueError(
                'Chunk %s has no stratum in its dependent list!' % chunk)

        for path in sorted(files.iterkeys()):
            chunk = files[path]
            stratum = get_stratum_for_chunk(chunk)
            chunk_in_system = (stratum in root_artifact.dependencies)
            present_flag = ' ' if chunk_in_system else 'X'
            print '%s  %20s: %s' % (present_flag, chunk.name, path)
