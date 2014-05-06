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


class ValidatePlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('validate', self.validate)

    def validate(self, args):
        '''Validate inputs and caches.

        '''

        lrc, rrc = morphlib.util.new_repo_caches(self.app)

        git_errors = lrc.validate()

        self.app.output.write('Found corruption in %i cached git repos.\n' %
                              len(git_errors))

        for repo_dir, error_text in git_errors.iteritems():
            self.app.output.write('    %s\n' % repo_dir)
            if self.app.settings['verbose']:
                error_text_indented = '\n'.join(
                    ['    ' + line for line in error_text.split('\n')])
                self.app.output.write("    %s\n" % error_text_indented)
