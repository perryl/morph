# distbuild/route_map.py -- map message ids for routing purposes
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


class RouteMap(object):

    '''Map message identifiers for routing purposes.
    
    Various state machines need to handle requests coming from multiple
    sources, and they need to keep track of which responses should be
    sent to which requestors. This class provides tools for keeping
    track of that.
    
    Each message is expected to have a unique identifier of some sort.
    The incoming request message has one, and all responses to it need
    to keep that. An incoming request might be converted into one or more
    outgoing requests, each with its own unique id. The responses to all
    of those need to be mapped back to the original incoming request.
    
    For this class, we care about "incoming id" and "outgoing id".
    There can be multiple outgoing identifiers for one incoming one.
    
    '''
    
    def __init__(self):
        self._routes = {}
    
    def add(self, incoming_id, outgoing_id):
        assert (outgoing_id not in self._routes or 
                self._routes[outgoing_id] == incoming_id)
        self._routes[outgoing_id] = incoming_id
        
    def get_incoming_id(self, outgoing_id):
        '''Get the incoming id corresponding to an outgoing one.
        
        Raise KeyError if not found.
        
        '''

        return self._routes[outgoing_id]

    def get_outgoing_ids(self, incoming_id):
        return [o for (o, i) in self._routes.iteritems() if i == incoming_id]

    def remove(self, outgoing_id):
        del self._routes[outgoing_id]
