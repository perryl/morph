# distbuild/route_map_tests.py -- unit tests for message routing
#
# Copyright (C) 2014  Codethink Limited
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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA..


import unittest

import distbuild


class RouteMapTests(unittest.TestCase):

    def setUp(self):
        self.rm = distbuild.RouteMap()

    def test_raises_error_for_unknown_route(self):
        self.assertRaises(KeyError, self.rm.get_incoming_id, 'outgoing')

    def test_finds_added_route(self):
        self.rm.add('incoming', 'outgoing')
        self.assertEqual(self.rm.get_incoming_id('outgoing'), 'incoming')

    def test_finds_outgoing_ids(self):
        self.rm.add('incoming', 'outgoing')
        self.assertEqual(self.rm.get_outgoing_ids('incoming'), ['outgoing'])

    def test_removes_added_route(self):
        self.rm.add('incoming', 'outgoing')
        self.rm.remove('outgoing')
        self.assertRaises(KeyError, self.rm.get_incoming_id, 'outgoing')

    def test_raises_error_if_forgetting_unknown_route(self):
        self.assertRaises(KeyError, self.rm.remove, 'outgoing')

    def test_silently_ignores_adding_existing_route(self):
        self.rm.add('incoming', 'outgoing')
        self.rm.add('incoming', 'outgoing')
        self.assertEqual(self.rm.get_incoming_id('outgoing'), 'incoming')

    def test_raises_assert_if_adding_conflicting_route(self):
        self.rm.add('incoming', 'outgoing')
        self.assertRaises(AssertionError, self.rm.add, 'different', 'outgoing')

