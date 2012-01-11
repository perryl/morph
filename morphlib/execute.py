# Copyright (C) 2011  Codethink Limited
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
import subprocess
import tempfile

import morphlib


class CommandFailure(cliapp.AppException):

    def __init__(self, command, stderr):
        cliapp.AppException.__init__(self, 
                'Command failed: %s\nOutput from command:\n%s' % 
                    (command, stderr))


class Execute(object):

    '''Execute commands for morph.'''
    
    def __init__(self, dirname, msg):
        self._setup_env()
        self.dirname = dirname
        self.msg = msg
        self._fakeroot_session = None

    def __del__(self): # pragma: no cover
        try:
            object.__del__(self)
        except AttributeError:
            pass
        if self._fakeroot_session:
            os.remove(self._fakeroot_session)

    def _setup_env(self):
        self.env = dict(os.environ)

    def _prefix(self, argv, as_root, as_fakeroot):
        if as_root: # pragma: no cover
            if os.getuid() == 0:
                prefix = ['env']
            else:
                prefix = ['sudo']
            envs = ["%s=%s" % x for x in self.env.iteritems()]
            argv = prefix + envs + argv
        elif as_fakeroot and os.getuid() != 0:
            if not self._fakeroot_session:
                self._fakeroot_session = tempfile.mkstemp()[1]
            argv = ['fakeroot', '-i', self._fakeroot_session, '-s',
                    self._fakeroot_session, '--'] + argv
        return argv

    def run(self, commands, as_root=False, as_fakeroot=False, _log=True):
        '''Execute a list of commands.
        
        If a command fails (returns non-zero exit code), the rest are
        not run, and CommandFailure is returned.
        
        '''

        stdouts = []
        for command in commands:
            self.msg('# %s' % command)
            argv = ['sh', '-c', command]
            argv = self._prefix(argv, as_root, as_fakeroot)
            logging.debug('run: argv=%s' % repr(argv))
            logging.debug('run: env=%s' % repr(self.env))
            logging.debug('run: cwd=%s' % repr(self.dirname))
            p = subprocess.Popen(argv, shell=False,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 env=self.env,
                                 cwd=self.dirname)
            out, err = p.communicate()
            if p.returncode != 0:
                if _log: # pragma: no cover
                    logging.error('Exit code: %d' % p.returncode)
                    logging.error('Standard output and error:\n%s' % 
                                    morphlib.util.indent(out))
                raise CommandFailure(command, out)
            stdouts.append(out)
        return stdouts

    def runv(self, argv, feed_stdin=None, as_root=False, as_fakeroot=False,
             _log=True, **kwargs):
        '''Run a command given as a list of argv elements.
        
        Return standard output. Raise ``CommandFailure`` if the command
        fails. Log standard output and error in any case.
        
        '''
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        if feed_stdin is not None and 'stdin' not in kwargs: 
            kwargs['stdin'] = subprocess.PIPE # pragma: no cover
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.STDOUT
        if 'cwd' not in kwargs:
            kwargs['cwd'] = self.dirname
        if 'env' not in kwargs:
            kwargs['env'] = self.env

        argv = self._prefix(argv, as_root, as_fakeroot)
        logging.debug('runv: argv=%s' % repr(argv))
        logging.debug('runv: env=%s' % repr(self.env))
        logging.debug('runv: cwd=%s' % repr(self.dirname))
        self.msg('# %s' % ' '.join(argv))
        p = subprocess.Popen(argv, **kwargs)
        out, err = p.communicate(feed_stdin)
        
        if p.returncode != 0:
            if _log: # pragma: no cover
                logging.error('Exit code: %d' % p.returncode)
                logging.error('Standard output:\n%s' %
                                morphlib.util.indent(out or ''))
                logging.error('Standard error:\n%s' %
                                morphlib.util.indent(err or ''))
            raise CommandFailure(' '.join(argv), out)
        return out

