# Copyright (C) 2015  Codethink Limited
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
import morphlib

class GetChunkDetailsPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'get-chunk-details', self.get_chunk_details,
            arg_synopsis='[STRATUM] CHUNK')

    def disable(self):
        pass

    def get_chunk_details(self, args):
        '''Print out details for the given chunk

        Command line arguments:

        * `STRATUM` is the stratum to search for chunk (optional).
        * `CHUNK` is the component to obtain a URL for.

        '''

        stratum_name = None

        if len(args) == 1:
            chunk_name = args[0]
        elif len(args) == 2:
            stratum_name = args[0]
            chunk_name = args[1]
        else:
            raise cliapp.AppException(
                'Wrong number of arguments to get-chunk-details command '
                '(see help)')

        sb = morphlib.sysbranchdir.open_from_within('.')
        loader = morphlib.morphloader.MorphologyLoader()

        aliases = self.app.settings['repo-alias']
        self.resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)

        found = 0
        for morph in sb.load_all_morphologies(loader):
            if morph['kind'] == 'stratum':
                if (stratum_name == None or
                        morph['name'] == stratum_name):
                    for chunk in morph['chunks']:
                        if chunk['name'] == chunk_name:
                            found = found + 1
                            self._print_chunk_details(chunk, morph)

        if found == 0:
            if stratum_name == None:
                print('Chunk `{}` not found'
                      .format(chunk_name))
            else:
                print('Chunk `{}` not found in stratum `{}`'
                      .format(chunk_name, stratum_name))

    def _print_chunk_details(self, chunk, morph):
        repo = self.resolver.pull_url(chunk['repo'])
        print('In stratum {}:'.format(morph['name']))
        print('  Chunk: {}'.format(chunk['name']))
        print('   Repo: {}'.format(repo))
        print('    Ref: {}'.format(chunk['ref']))
