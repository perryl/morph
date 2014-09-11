# Base class for import tools written in Python.
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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import cliapp

import logging
import os


class ImportExtension(cliapp.Application):
    '''A base class for import extensions.

    A subclass should subclass this class, and add a ``process_args`` method.

    Note that it is not necessary to subclass this class for import extensions.
    This class is here just to collect common code.

    '''

    def setup_logging(self):
        # For old cliapp
        self.setup_logging_to_file()

    def setup_logging_to_file(self):
        '''Direct all logging output to MORPH_LOG_FD, if set.

        This file descriptor is read by Morph and written into its own log
        file.

        This overrides cliapp's usual configurable logging setup.

        '''
        # For new cliapp
        log_write_fd = int(os.environ.get('MORPH_LOG_FD', 0))

        if log_write_fd == 0:
            return

        formatter = logging.Formatter('%(message)s')

        handler = logging.StreamHandler(os.fdopen(log_write_fd, 'w'))
        handler.setFormatter(formatter)

        logger = logging.getLogger()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

    def process_args(self, args):
        raise NotImplementedError()
