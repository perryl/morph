# Copyright (C) 2012-2015  Codethink Limited
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


import morphlib

class BuildSystem(object):

    '''Predefined command sequences for a given build system.

    For example, you can have an 'autotools' build system, which runs
    'configure', 'make' and 'make install'.

    '''

    def __init__(self):
        self.pre_configure_commands = []
        self.configure_commands = []
        self.post_configure_commands = []
        self.pre_build_commands = []
        self.build_commands = []
        self.post_build_commands = []
        self.pre_test_commands = []
        self.test_commands = []
        self.post_test_commands = []
        self.pre_install_commands = []
        self.install_commands = []
        self.post_install_commands = []
        self.pre_strip_commands = []
        self.strip_commands = []
        self.post_strip_commands = []

    def from_dict(self, name, commands):
        self.name = name

        self.configure_commands = commands.get('configure-commands', [])
        self.build_commands = commands.get('build-commands', [])
        self.install_commands = commands.get('install-commands', [])
        self.strip_commands = commands.get('strip-commands', [])

    def __getitem__(self, key):
        key = '_'.join(key.split('-'))
        return getattr(self, key)

    def get_morphology(self, name):
        '''Return the text of an autodetected chunk morphology.'''

        return morphlib.morphology.Morphology({
            'name': name,
            'kind': 'chunk',
            'build-system': self.name,
        })

class ManualBuildSystem(BuildSystem):

    '''A manual build system where the morphology must specify all commands.'''

    name = 'manual'
