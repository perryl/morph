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
        self.app.settings.string(['ref', 'r'],
                                 'ref to checkout in the cloned repo',
                                 metavar='REF', default='',
                                 group='get-repo options')

    def disable(self):
        pass

    def _clone_repo(self, cached_repo, dirname, checkout_ref):
        '''Clone a cached git repository into the directory given by path.'''
        # Do the clone.
        gd = morphlib.gitdir.checkout_from_cached_repo(
            cached_repo, checkout_ref, dirname)

        # Configure the "origin" remote to use the upstream git repository,
        # and not the locally cached copy.
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            self.app.settings['repo-alias'])
        remote = gd.get_remote('origin')
        remote.set_fetch_url(resolver.pull_url(cached_repo.url))
        remote.set_push_url(resolver.push_url(cached_repo.original_name))

        gd.update_submodules(self.app)
        gd.update_remotes()

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

        def checkout_chunk(morph, chunk_spec):
            dirname = self._get_chunk_dirname(path, definitions_repo,
                                              chunk_spec)
            if not os.path.exists(dirname):
                self.app.status(
                    msg='Checking out ref %(ref)s of %(chunk)s in '
                        '%(stratum)s stratum',
                    ref=ref or chunk_spec['ref'], chunk=chunk_spec['name'],
                    stratum=morph['name'])
                repo_cache = morphlib.util.new_repo_cache(self.app)
                cached_repo = repo_cache.get_updated_repo(chunk_spec['repo'],
                                                          chunk_spec['ref'])

                try:
                    self._clone_repo(cached_repo, dirname,
                                     ref or chunk_spec['ref'])
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
                            chunk_dirname = checkout_chunk(morph, chunk)
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
