# -*- coding: utf-8 -*-
# distbuild/build_request_db.py -- store build request history
#
# Copyright © 2015  Codethink Limited
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


import os
import sqlite3
import logging
import datetime
import cliapp

DB_PATH = '/srv/distbuild/distbuild.db'
SCHEMA_VERSION = 1
MAX_AGE = 60   # 60 days


class BuildRequestDB(object):

    first = True

    def __init__(self):
        self._cursor = None
        self._conn = None

        if not os.path.exists(DB_PATH):
            self._create_database()
            self._open_db()
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        db_version = self._get_db_schema_version(cursor)

        assert db_version is not None

        if db_version != SCHEMA_VERSION:
            logging.info('Database schema has version, %s '
                         'distbuild schema has version %s',
                         db_version, SCHEMA_VERSION)

            # TODO: Database migration

            logging.info('Removing existing database %s', DB_PATH)
            os.unlink(DB_PATH)
            self._create_database()

        self._open_db()

        if BuildRequestDB.first:
            self._restore_sanity()
            self._expire_requests()
            BuildRequestDB.first = False

    def close(self):
        self._cursor.commit()
        self._cursor.close()
        self._cursor = None

    def _open_db(self):
        logging.debug('Opening database %s', DB_PATH)
        self._conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)

        # Allows us to access items by column name,
        # instead of returning a tuple the cursor will return
        # a Row object which can be accessed like a dictionary
        self._conn.row_factory = sqlite3.Row

        self._cursor = self._conn.cursor()

    def _get_db_schema_version(self, cursor):
        cursor.execute('PRAGMA user_version')
        version, = cursor.fetchone()
        return version

    def _expire_requests(self):
        ''' Remove anything older than MAX_AGE '''
        logging.debug('Removing any old requests...')

        oldest_date = (datetime.datetime.now() -
                       datetime.timedelta(days=MAX_AGE))

        self._cursor.execute('SELECT id, last_updated '
                             'FROM build_requests')

        to_delete = (row for row in self._cursor.fetchall()
                        if row['last_updated'] < oldest_date)

        for row in to_delete:
            logging.debug('Deleting request with id %s', row['id'])
            self._cursor.execute('DELETE FROM build_requests '
                                 'WHERE id = ?', (row['id'], ))

        self._conn.commit()

    def _restore_sanity(self):
        ''' The controller may not have exited cleanly,
            when the controller is first started we need to ensure
            that no build requests are in an "active" state. '''

        logging.debug('Restoring sanity')

        self._cursor.execute('UPDATE build_requests '
                             "SET status = 'terminated', active = 0 "
                             "WHERE active = 1")

        self._conn.commit()

    def _create_database(self):
        logging.debug('Creating database %s', DB_PATH)
        conn = sqlite3.connect(DB_PATH)

        conn.cursor().execute('PRAGMA user_version = %s' % SCHEMA_VERSION)

        conn.cursor().execute('''CREATE TABLE build_requests
                                 (id text primary key not null,
                                  initiator_hostname text,
                                  repo text,
                                  ref text,
                                  morphology text,
                                  artifact text,
                                  status text,
                                  active boolean not null
                                        check (active in (0,1)),
                                  last_updated timestamp not null)''')

        conn.commit()
        conn.close()

    def add_request(self, **kwargs):
        columns = ('id', 'repo', 'ref', 'morphology',
                   'status', 'initiator_hostname', 'artifact', 'active')

        row = {k: str(v) for (k, v) in kwargs.iteritems() if k in columns}

        # Default values
        if 'artifact' not in row:   row['artifact'] = ''
        if 'active' not in row:     row['active'] = True
        row['last_updated'] = datetime.datetime.now()

        querystr = ('INSERT INTO build_requests VALUES '
                    '(:id, :initiator_hostname, :repo, :ref,'
                    ' :morphology, :status, :artifact, '
                    ' :active, :last_updated)')

        logging.debug('Values to insert: %s', row)
        logging.debug('Executing querystr: %s', querystr)

        self._cursor.execute(querystr, row)

        self._conn.commit()
        logging.debug('Added %s rows', self._cursor.rowcount)

    def update_request_status(self, id, (status, artifact)):
        logging.debug('Updating request (%s, %s, %s) in database',
                      id, status, artifact)

        ACTIVE = ('graphing', 'building', 'waiting')
        INACTIVE = ('cancelled', 'failed', 'finished')

        assert status in ACTIVE + INACTIVE

        self._cursor.execute('UPDATE build_requests '
                             'SET status = ?, artifact = ?, ACTIVE = ?, '
                             'last_updated = ? WHERE id = ?',
                             (status, artifact, int(status in ACTIVE),
                              datetime.datetime.now(), id))

        self._conn.commit()

        f = logging.warning if self._cursor.rowcount == 0 else logging.debug
        f('Updated %s rows', self._cursor.rowcount)

    def _query_tail(self, l):
        ''' Builds the tail of a named-style query (who=:who and age=:age) '''
        return (' AND '.join(map(lambda x: '%s=:%s' % (x, x), l) if l else ''))

    def get_requests(self, **kwargs):
        logging.debug('Getting request from database')

        querystr = 'SELECT * FROM build_requests'

        if 'active' in kwargs:
            kwargs['active'] = int(kwargs['active'])

        tail = self._query_tail(kwargs)
        if tail:
            querystr += ' WHERE %s' % tail

        logging.debug('Search keys: %s', kwargs)
        logging.debug('Executing querystr %s', querystr)
        self._cursor.execute(querystr, kwargs)

        results = self._cursor.fetchall()
        logging.debug('Query yielded %s', results)
        return results
