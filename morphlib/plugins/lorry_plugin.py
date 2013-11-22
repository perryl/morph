# Copyright (C) 2013  Codethink Limited
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

import os
import cliapp
import logging

import morphlib
from morphlib.util import OrderedDict, json

class LorryPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'lorry', self._lorry, arg_synopsis='NAME URL TYPE [ARG...]')

    def disable(self):
        pass

    def _lorry(self, args, **kwargs):
        '''Ingest a new component into git in the Baserock way

        Command line arguments:

        * `NAME` is used for the resulting lorry file and git repo
        * `URL` specifies the upstream (repo or tarball)
        * `TYPE` specifies the upstream type eg tar, bzr, svn, git
        * `ARG` is a Lorry command argument.

        This creates a NAME.lorry file, and then runs Lorry on it

        Example:

            morph foo http://code.liw.fi/foo/bzr/trunk/ bzr

        '''

        if len(args) < 3:
            raise cliapp.AppException('morph lorry needs a lorry name,'
                                      ' url and type as paramaters')
        chunk = args[0]
        url = args[1]
        type = args[2]

        lorrydir = os.path.join(self.app.settings['cachedir'],'lorries')
        if not os.path.exists(lorrydir):
            os.makedirs(lorrydir)

        lorry = {chunk: {'type': type, 'url': url}}
        f = open(os.path.join(lorrydir, chunk + '.lorry'), "w")
        f.write(json.dumps(lorry, indent=4, sort_keys=True))
        f.close()

        self.app.runcmd(['lorry', '--verbose', '--pull-only', f.name,
            '-w', lorrydir], stdin=None, stdout=None, stderr=None)
