# distbuild/protocol.py -- abstractions for the JSON messages
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


'''Construct protocol message objects (dicts).'''


_types = {
    'build-request': [
        'id',
        'repo',
        'ref',
        'morphology',
    ],
    'build-progress': [
        'id',
        'message',
    ],
    'build-steps': [
        'id',
        'steps',
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
}


def message(message_type, **kwargs):
    assert message_type in _types
    required_fields = _types[message_type]

    for name in required_fields:
        assert name in kwargs, 'field %s is required' % name

    for name in kwargs:
        assert name in required_fields, 'field %s is not allowed' % name

    msg = dict(kwargs)
    msg['type'] = message_type
    return msg

