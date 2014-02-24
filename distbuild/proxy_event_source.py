# distbuild/proxy_event_source.py -- proxy for temporary event sources
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


import errno
import logging
import socket

import distbuild


class ProxyEventSource(object):

    '''Proxy event sources that may come and go.'''

    def __init__(self):
        self.event_source = None

    def get_select_params(self):
        if self.event_source:
            return self.event_source.get_select_params()
        else:
            return [], [], [], None
            
    def get_events(self, r, w, x):
        if self.event_source:
            return self.event_source.get_events(r, w, x)
        else:
            return []
            
    def is_finished(self):
        return False

