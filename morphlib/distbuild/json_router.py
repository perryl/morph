# distbuild/json_router.py -- state machine to route JSON messages
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


import logging

import distbuild


class JsonRouter(distbuild.StateMachine):

    '''Route JSON messages between clients and helpers.
    
    This state machine receives JSON messages from clients and helpers,
    and routes messages between them.
    
    Each incoming request is labeled with a unique identifier, then
    sent to the next free helper. The helper's response will retain
    the unique id, so that the response can be routed to the right
    client.
    
    '''

    pending_requests = []
    running_requests = {}
    pending_helpers = []
    request_counter = distbuild.IdentifierGenerator('JsonRouter')
    route_map = distbuild.RouteMap()

    def __init__(self, conn):
        distbuild.StateMachine.__init__(self, 'idle')
        self.conn = conn
        logging.debug('JsonMachine: connection from %s', conn.getpeername())

    def setup(self):
        jm = distbuild.JsonMachine(self.conn)
        jm.debug_json = True
        self.mainloop.add_state_machine(jm)
        
        spec = [
            ('idle', jm, distbuild.JsonNewMessage, 'idle', self.bloop),
            ('idle', jm, distbuild.JsonEof, None, self.close),
        ]
        self.add_transitions(spec)

    def _lookup_request(self, request_id):
        if request_id in self.running_requests:
            return self.running_requests[request_id]
        else:
            return None
        
    def bloop(self, event_source, event):
        logging.debug('JsonRouter: got msg: %s', repr(event.msg))
        handlers = {
            'http-request': self.do_request,
            'http-response': self.do_response,
            'exec-request': self.do_request,
            'exec-cancel': self.do_cancel,
            'exec-output': self.do_exec_output,
            'exec-response': self.do_response,
            'helper-ready': self.do_helper_ready,
        }
        handler = handlers.get(event.msg['type'])
        handler(event_source, event)

    def do_request(self, client, event):
        self._enqueue_request(client, event.msg)
        if self.pending_helpers:
            self._send_request()

    def do_cancel(self, client, event):
        for id in self.route_map.get_outgoing_ids(event.msg['id']):
            logging.debug('JsonRouter: looking up request for id %s', id)
            t = self._lookup_request(id)
            if t:
                helper = t[2]
                new = dict(event.msg)
                new['id'] = id
                helper.send(new)
                logging.debug('JsonRouter: sent to helper: %s', repr(new))

    def do_response(self, helper, event):
        t = self._lookup_request(event.msg['id'])
        if t:
            client, msg, helper = t
            new = dict(event.msg)
            new['id'] = self.route_map.get_incoming_id(msg['id'])
            client.send(new)
            logging.debug('JsonRouter: sent to client: %s', repr(new))

    def do_helper_ready(self, helper, event):
        self.pending_helpers.append(helper)
        if self.pending_requests:
            self._send_request()

    def do_exec_output(self, helper, event):
        t = self._lookup_request(event.msg['id'])
        if t:
            client, msg, helper = t
            new = dict(event.msg)
            new['id'] = self.route_map.get_incoming_id(msg['id'])
            client.send(new)
            logging.debug('JsonRouter: sent to client: %s', repr(new))

    def close(self, event_source, event):
        logging.debug('closing: %s', repr(event_source))
        event_source.close()

        # Remove from pending helpers.
        if event_source in self.pending_helpers:
            self.pending_helpers.remove(event_source)

        # Remove from running requests, and put the request back in the
        # pending requests queue if the helper quit (but not if the
        # client quit).
        for request_id in self.running_requests.keys():
            client, msg, helper = self.running_requests[request_id]
            if event_source == client:
                del self.running_requests[request_id]
            elif event_source == helper:
                del self.running_requests[request_id]
                self._enqueue_request(client, msg)

        # Remove from pending requests, if the client quit.
        i = 0
        while i < len(self.pending_requests):
            client, msg = self.pending_requests[i]
            if event_source == client:
                del self.pending_requests[i]
            else:
                i += 1
                
        # Finally, if there are any pending requests and helpers,
        # send requests.
        while self.pending_requests and self.pending_helpers:
            self._send_request()

    def _enqueue_request(self, client, msg):
        new = dict(msg)
        new['id'] = self.request_counter.next()
        self.route_map.add(msg['id'], new['id'])
        self.pending_requests.append((client, new))

    def _send_request(self):
        client, msg = self.pending_requests.pop(0)
        helper = self.pending_helpers.pop()
        self.running_requests[msg['id']] = (client, msg, helper)
        helper.send(msg)
        logging.debug('JsonRouter: sent to helper: %s', repr(msg))

