# distbuild/protocol.py -- abstractions for the JSON messages
#
# Copyright (C) 2012, 2014-2015  Codethink Limited
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


'''Construct protocol message objects (dicts).'''


# Version refers to an integer that should be incremented by one each time a
# time a change is introduced that would break server/initiator compatibility


VERSION = 2


_required_fields = {
    'build-request': [
        'id',
        'repo',
        'ref',
        'morphology',
        'partial',
        'protocol_version',
        'allow_detach',
    ],
    'build-progress': [
        'id',
        'message',
    ],
    'step-started': [
        'id',
        'step_name',
        'worker_name',
    ],
    'step-already-started': [
        'id',
        'step_name',
        'worker_name',
    ],
    'step-output': [
        'id',
        'step_name',
        'stdout',
        'stderr',
    ],
    'step-finished': [
        'id',
        'step_name',
    ],
    'step-failed': [
        'id',
        'step_name',
    ],
    'build-finished': [
        'id',
        'urls',
    ],
    'build-failed': [
        'id',
        'reason',
    ],
    'exec-request': [
        'id',
        'argv',
        'stdin_contents',
    ],
    'exec-cancel': [
        'id',
    ],
    'http-request': [
        'id',
        'url',
        'method',
        'headers',
        'body',
    ],
    'list-requests': [
        'id',
        'protocol_version',
    ],
    'request-output': [
        'message',
    ],
    'build-cancel': [
        'id',
        'protocol_version',
    ],
    'build-status': [
        'id',
        'protocol_version',
    ],
}


_optional_fields = {
    'build-request': [
        'original_ref',
        'component_names'
    ]
}


def message(message_type, **kwargs):
    known_types = _required_fields.keys()
    assert message_type in known_types

    required_fields = _required_fields[message_type]
    optional_fields = _optional_fields.get(message_type, [])

    for name in required_fields:
        assert name in kwargs, 'field %s is required' % name

    for name in kwargs:
        assert (name in required_fields or name in optional_fields), \
              'field %s is not allowed' % name

    msg = dict(kwargs)
    msg['type'] = message_type
    return msg

