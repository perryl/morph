# distbuild/helper_router.py -- state machine for controller's helper comms
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


class HelperRequest(object):

    def __init__(self, msg):
        self.msg = msg


class HelperOutput(object):

    def __init__(self, msg):
        self.msg = msg


class HelperResult(object):

    def __init__(self, msg):
        self.msg = msg


class HelperRouter(distbuild.StateMachine):

    '''Route JSON messages between helpers and other state machines.
    
    This state machine relays and schedules access to one distbuild-helper
    process. The helper process connects to a socket, which causes an
    instance of HelperRouter to be created (one per connection). The
    various instances co-ordinate requests automatically amongst
    themselves.
    
    Other state machines in the same mainloop as HelperRouter can
    request work from the helper process by emitting an event:
    
    * event source: the distbuild.HelperProcess class
    * event: distbuild.HelperRequest instance

    The HelperRequest event gets a message to be serialised as JSON.
    The message must be a Pythondict that the distbuild-helper understands.
    
    HelperRouter will send the msg to the next available helper process.
    When the helper sends back the result, HelperRouter will emit a
    HelperResult event, using the same ``request_id`` as the request had.
    
    For its internal use, HelperRouter sets the ``id`` item in the
    request object.

    '''

    _pending_requests = []
    _running_requests = {}
    _pending_helpers = []
    _request_counter = distbuild.IdentifierGenerator('HelperRouter')
    _route_map = distbuild.RouteMap()

    def __init__(self, conn):
        distbuild.StateMachine.__init__(self, 'idle')
        self.conn = conn

    def setup(self):
        jm = distbuild.JsonMachine(self.conn)
        self.mainloop.add_state_machine(jm)
        
        spec = [
            ('idle', HelperRouter, HelperRequest, 'idle', 
                self._handle_request),
            ('idle', jm, distbuild.JsonNewMessage, 'idle', self._helper_msg),
            ('idle', jm, distbuild.JsonEof, None, self._close),
        ]
        self.add_transitions(spec)

    def _handle_request(self, event_source, event):
        '''Send request received via mainloop, or put in queue.'''
        logging.debug('HelperRouter: received request: %s', repr(event.msg))
        self._enqueue_request(event.msg)
        if self._pending_helpers:
            self._send_request()
        
    def _helper_msg(self, event_source, event):
        '''Handle message from helper.'''
        
#        logging.debug('HelperRouter: from helper: %s', repr(event.msg))
        
        handlers = {
            'helper-ready': self._handle_helper_ready,
            'exec-output': self._handle_exec_output,
            'exec-response': self._handle_exec_response,
            'http-response': self._handle_http_response,
        }
        
        handler = handlers[event.msg['type']]
        handler(event_source, event.msg)
        
    def _handle_helper_ready(self, event_source, msg):
        self._pending_helpers.append(event_source)
        if self._pending_requests:
            self._send_request()

    def _get_request(self, msg):
        request_id = msg['id']
        if request_id in self._running_requests:
            request, helper = self._running_requests[request_id]
            return request
        elif request_id is None:
            logging.error(
                'Helper process sent message without "id" field: %s',
                repr(event.msg))
        else:
            logging.error(
                'Helper process sent message with unknown id: %s',
                repr(event.msg))

    def _new_message(self, msg):
        old_id = msg['id']
        new_msg = dict(msg)
        new_msg['id'] = self._route_map.get_incoming_id(old_id)
        return new_msg

    def _handle_exec_output(self, event_source, msg):
        request = self._get_request(msg)
        if request is not None:
            new_msg = self._new_message(msg)
            self.mainloop.queue_event(HelperRouter, HelperOutput(new_msg))

    def _handle_exec_response(self, event_source, msg):
        request = self._get_request(msg)
        if request is not None:
            new_msg = self._new_message(msg)
            self._route_map.remove(msg['id'])
            del self._running_requests[msg['id']]
            self.mainloop.queue_event(HelperRouter, HelperResult(new_msg))

    def _handle_http_response(self, event_source, msg):
        request = self._get_request(msg)
        if request is not None:
            new_msg = self._new_message(msg)
            self._route_map.remove(msg['id'])
            del self._running_requests[msg['id']]
            self.mainloop.queue_event(HelperRouter, HelperResult(new_msg))

    def _close(self, event_source, event):
        logging.debug('HelperRouter: closing: %s', repr(event_source))
        event_source.close()

        # Remove from pending helpers.
        if event_source in self._pending_helpers:
            self._pending_helpers.remove(event_source)

        # Re-queue any requests running on the hlper that just quit.
        for request_id in self._running_requests.keys():
            request, helper = self._running_requests[request_id]
            if event_source == helper:
                del self._running_requests[request_id]
                self._enqueue_request(request)
                
        # Finally, if there are any pending requests and helpers,
        # send requests.
        while self._pending_requests and self._pending_helpers:
            self._send_request()

    def _enqueue_request(self, request):
        '''Put request into queue.'''
#        logging.debug('HelperRouter: enqueuing request: %s' % repr(request))
        old_id = request['id']
        new_id = self._request_counter.next()
        request['id'] = new_id
        self._route_map.add(old_id, new_id)
        self._pending_requests.append(request)

    def _send_request(self):
        '''Pick the first queued request and send it to an available helper.'''
        request = self._pending_requests.pop(0)
        helper = self._pending_helpers.pop()
        self._running_requests[request['id']] = (request, helper)
        helper.send(request)
#        logging.debug('HelperRouter: sent to helper: %s', repr(request))

