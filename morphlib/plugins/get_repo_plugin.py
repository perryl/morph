# -*- coding: utf-8 -*-
# Copyright © 2015  Codethink Limited
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


import logging
import os
import shutil

import cliapp

import morphlib


class DirectoryAlreadyExistsError(morphlib.Error):

    def __init__(self, chunk, dirname):
        self.msg = ('Failed to clone repo for %s, destination directory %s '
                    'already exists.' % (chunk, dirname))


class GetRepoPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'get-repo', self.get_repo, arg_synopsis='CHUNK [PATH]')
        self.app.settings.string(['checkout-ref'],
                                 'ref to checkout in the cloned repo',
                                 metavar='REF', default='',
                                 group='get-repo options')

    def disable(self):
        pass

    def extract_repo(self, repo_cache, repo, sha1, destdir,
                     submodules_map=None): #pragma: no cover
        self.app.status(msg='Extracting %(source)s into %(target)s',
                   source=repo.original_name,
                   target=destdir)
        gd = morphlib.gitdir.checkout_from_cached_repo(repo, sha1, destdir)
        morphlib.git.reset_workdir(self.app.runcmd, destdir)

        # Configure the "origin" remote to use the upstream git repository,
        # and not the locally cached copy.
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            self.app.settings['repo-alias'])
        remote = gd.get_remote('origin')
        remote.set_fetch_url(resolver.pull_url(repo.url))
        remote.set_push_url(resolver.push_url(repo.original_name))

        # Check and handle submodules
        submodules = morphlib.git.Submodules(repo.dirname, sha1,
                                             self.app.runcmd)
        try:
            submodules.load()
        except morphlib.git.NoModulesFileError:
            return []
        else:
            tuples = []
            for sub in submodules:
                if submodules_map and sub.name in submodules_map:
                    url = submodules_map[sub.name]['url']
                else:
                    url = sub.url
                cached_repo = repo_cache.get_updated_repo(url, sub.commit)
                sub_dir = os.path.join(destdir, sub.path)
                tuples.append((cached_repo, sub.commit, sub_dir))
            return tuples

    def _get_chunk_dirname(self, path, definitions_repo, spec):
        if path:
            return path
        else:
            return definitions_repo.relative_path_to_chunk(spec['repo'])

    def get_repo(self, args):
        '''Checkout a component repository.

        Command line arguments:

        * `CHUNK` is the name of a chunk
        * `PATH` is the path at which the checkout will be located.
        * `REF` is the ref to checkout. By default this is the ref defined in
          the stratum containing the chunk.

        This makes a local checkout of CHUNK in PATH (or in the current system
        branch if PATH isn't given).

        '''

        if len(args) < 1:
            raise cliapp.AppException('morph get-repo needs a chunk '
                                      'as parameter: `morph get-repo '
                                      'CHUNK [PATH]')

        chunk_name = args[0]
        path = None
        if len(args) > 1:
            path = os.path.abspath(args[1])
        ref = self.app.settings['ref']

        def checkout_chunk(morph, chunk_spec, definitions_version):
            dirname = self._get_chunk_dirname(path, definitions_repo,
                                              chunk_spec)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
                self.app.status(
                    msg='Checking out ref %(ref)s of %(chunk)s in '
                        '%(stratum)s stratum',
                    ref=ref or chunk_spec['ref'], chunk=chunk_spec['name'],
                    stratum=morph['name'])
                repo_cache = morphlib.util.new_repo_cache(self.app)
                cached_repo = repo_cache.get_updated_repo(chunk_spec['repo'],
                                                          chunk_spec['ref'])

                submodules = {}
                if definitions_version >= 8:
                    submodules = chunk_spec.get('submodules', {})

                repo_cache.ensure_submodules(
                    cached_repo, chunk_spec['ref'], submodules)

                try:
                    todo = [(cached_repo, ref or chunk_spec['ref'], dirname)]
                    while todo:
                        repo, sha1, destdir = todo.pop()
                        todo += self.extract_repo(repo_cache, repo, sha1,
                                                  destdir, submodules)

                except morphlib.gitdir.InvalidRefError:
                    raise cliapp.AppException(
                             "Cannot get '%s', repo has no commit at ref %s."
                             % (chunk_spec['name'], ref or chunk_spec['ref']))
                except BaseException as e:
                    logging.debug('Removing %s due to %s', dirname, e)
                    shutil.rmtree(dirname)
                    raise
            else:
                raise DirectoryAlreadyExistsError(chunk_spec['name'], dirname)

            return dirname

        strata = set()
        found = 0

        definitions_repo = morphlib.definitions_repo.open(
            '.', search_for_root=True, app=self.app)
        version = definitions_repo.get_version()

        self.app.status(msg='Loading in all morphologies')
        for morph in definitions_repo.load_all_morphologies():
            if morph['kind'] == 'stratum':
                for chunk in morph['chunks']:
                    if chunk['name'] == chunk_name:
                        if found >= 1:
                            self.app.status(
                                msg='Chunk %(chunk)s also found in '
                                    '%(stratum)s stratum.',
                                chunk=chunk_name, stratum=morph['name'],
                                chatty=True)
                        else:
                            chunk_dirname = checkout_chunk(morph, chunk,
                                                           version)
                        strata.add(morph['name'])
                        found = found + 1

        if found == 0:
            self.app.status(
                msg="No chunk %(chunk)s found. If you want to create one, add "
                "an entry to a stratum morph file.", chunk=chunk_name)

        if found >= 1:
            self.app.status(
                msg="Chunk %(chunk)s source is available at %(dir)s",
                chunk=chunk_name, dir=chunk_dirname)

        if found > 1:
            self.app.status(
                msg="Note that this chunk appears in more than one stratum: "
                    "%(strata)s",
                strata=', '.join(strata))
