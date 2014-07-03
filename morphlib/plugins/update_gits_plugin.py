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


class UpdateGitsPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('update-gits',
                                self.update_gits,
                                arg_synopsis='(REPO REF MORPHOLOGY)...')

    def disable(self):
        pass

    def update_gits(self, args):
        '''Manually update cached git repositories for the given morphology

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a git commit ref (sha1, branch, tag).
        * `MORPHOLOGY` is a morphology filename.

        This updates the local cached copy of a git repository, and any
        git repositories of components in the morphology (for system
        and stratum morphologies).

        You do not normally need to do this. Morph updates the cached
        repositories automatically anyway.

        '''

        app = self.app
        if not os.path.exists(app.settings['cachedir']):
            os.mkdir(app.settings['cachedir'])
        cachedir = os.path.join(app.settings['cachedir'], 'gits')
        repo_resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            app.settings['repo-alias'])
        tarball_base_url = app.settings['tarball-server']
        cache = morphlib.localrepocache.LocalRepoCache(
            app, cachedir, repo_resolver, tarball_base_url)

        subs_to_process = set()

        def visit(reponame, ref, filename, absref, tree, morphology,
                morphology_repo, morphology_ref):
            app.status(msg='Updating %(repo_name)s %(ref)s %(filename)s',
                       repo_name=reponame, ref=ref, filename=filename)
            assert cache.has_repo(reponame)
            cached_repo = cache.get_repo(reponame)
            try:
                submodules = morphlib.git.Submodules(app, cached_repo.path,
                                                     absref)
                submodules.load()
            except morphlib.git.NoModulesFileError:
                pass
            else:
                for submod in submodules:
                    subs_to_process.add((submod.url, submod.commit))

        app.traverse_morphs(app.itertriplets(args), cache, None,
                            update=True, visit=visit)

        done = set()
        for url, ref in subs_to_process:
            app.cache_repo_and_submodules(cache, url, ref, done)
