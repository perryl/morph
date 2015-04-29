# Copyright (C) 2015 Codethink Limited
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
import sys
import urllib
import urlparse

import morphlib


class ShowBuildLog(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('show-build-log', self.show_build_log,
                                arg_synopsis='SYSTEM CHUNK')

    def disable(self):
        pass

    def show_build_log(self, args):
        '''Display build logs for a given component in a system.

        Command line arguments:

        * `SYSTEM` is the name of the system we want log data from.
        * `CHUNK` is the name of the chunk we want log data for.

        Example:

            morph show-build-log devel-system-x86_64-generic.morph pip

        '''

        if len(args) != 2:
            raise cliapp.AppException('show-build-log expects system filename '
                                      'and chunk as input.')

        artifact_cache_server = (
            self.app.settings['artifact-cache-server'] or
            self.app.settings['cache-server'])

        system = args[0]
        chunk = args[1]

        sb = morphlib.sysbranchdir.open_from_within('.')
        root_repo_url = sb.get_config('branch.root')
        ref = sb.get_config('branch.name')

        definitions_repo_path = sb.get_git_directory_name(root_repo_url)

        build_command = morphlib.buildcommand.BuildCommand(self.app, None)
        srcpool = build_command.create_source_pool(definitions_repo_path, ref,
                                                   system)
        root = build_command.resolve_artifacts(srcpool)

        arch = root.source.morphology['arch']
        build_env = build_command.new_build_env(arch)

        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        for source in set(a.source for a in root.walk()):
            source.cache_key = ckc.compute_key(source)

        if source.cache_key != None:
            url = urlparse.urljoin(artifact_cache_server,
                '/1.0/artifacts?filename=%s.build-log' % source.cache_key)
            build_log = urllib.urlopen(url)
            build_output = []
            for line in build_log:
                build_output.append(str(line))
            sys.stdout.write(str(''.join(build_output)))
