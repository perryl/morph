# Copyright (C) 2012-2014  Codethink Limited
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
import os

import morphlib


class ShowDependenciesPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('show-dependencies',
                                self.show_dependencies,
                                arg_synopsis='(REPO REF MORPHOLOGY)...')

    def disable(self):
        pass

    def show_dependencies(self, args):
        '''Dumps the dependency tree of all input morphologies.

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a branch or other commit reference in that repository.
        * `FILENAME` is a morphology filename at that ref.

        This command analyses a system morphology and produces a listing
        of build dependencies of the constituent components.

        '''

        if not os.path.exists(self.app.settings['cachedir']):
            os.mkdir(self.app.settings['cachedir'])
        cachedir = os.path.join(self.app.settings['cachedir'], 'gits')
        tarball_base_url = self.app.settings['tarball-server']
        repo_resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            self.app.settings['repo-alias'])
        lrc = morphlib.localrepocache.LocalRepoCache(
            self.app, cachedir, repo_resolver, tarball_base_url)

        remote_url = morphlib.util.get_git_resolve_cache_server(
            self.app.settings)
        if remote_url:
            rrc = morphlib.remoterepocache.RemoteRepoCache(
                remote_url, repo_resolver)
        else:
            rrc = None
            
        build_command = morphlib.buildcommand.BuildCommand(self.app)

        # traverse the morphs to list all the sources
        for repo, ref, filename in self.app.itertriplets(args):
            morph = morphlib.util.sanitise_morphology_path(filename)
            self.app.output.write('dependency graph for %s|%s|%s:\n' %
                                  (repo, ref, morph))

            srcpool = build_command.create_source_pool(repo, ref, filename)
            root_artifact = build_command.resolve_artifacts(srcpool)

            for artifact in reversed(root_artifact.walk()):
                self.app.output.write('  %s\n' % artifact)
                for dependency in sorted(artifact.dependencies, key=str):
                    self.app.output.write('    -> %s\n' % dependency)

