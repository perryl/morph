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


import unittest

import morphlib


class BuildSystemTests(unittest.TestCase):

    def setUp(self):
        self.bs = morphlib.buildsystem.BuildSystem()

    def test_has_configure_commands(self):
        self.assertEqual(self.bs['configure-commands'], [])

    def test_has_build_commands(self):
        self.assertEqual(self.bs['build-commands'], [])

    def test_has_test_commands(self):
        self.assertEqual(self.bs['test-commands'], [])

    def test_has_install_commands(self):
        self.assertEqual(self.bs['install-commands'], [])

    def test_returns_morphology(self):
        self.bs.name = 'fake'
        morph = self.bs.get_morphology('foobar')
        self.assertTrue(morph.__class__.__name__ == 'Morphology')

    def test_construct_from_dict(self):
        '''Test parsing a dict of information from a DEFAULTS file.'''

        commands_dict = {
             'configure-commands': 'foo'
        }
        self.bs.from_dict('test', commands_dict)
        self.assertEqual(self.bs.configure_commands, 'foo')
