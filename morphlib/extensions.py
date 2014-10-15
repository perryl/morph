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

import asyncore
import asynchat
import glob
import logging
import os
import stat
import subprocess
import tempfile

import cliapp

import morphlib
import sysbranchdir


class ExtensionError(morphlib.Error):
    pass

class ExtensionNotFoundError(ExtensionError):
    pass

class ExtensionNotExecutableError(ExtensionError):
    pass

def _get_root_repo():
    system_branch = morphlib.sysbranchdir.open_from_within('.')
    root_repo_dir = morphlib.gitdir.GitDirectory(
            system_branch.get_git_directory_name(
                system_branch.root_repository_url))
    return root_repo_dir

def _get_morph_extension_directory():
    code_dir = os.path.dirname(morphlib.__file__)
    return os.path.join(code_dir, 'exts')

def _list_repo_extension_filenames(kind): #pragma: no cover
    repo_dir = _get_root_repo()
    files = repo_dir.list_files()
    return (f for f in files if os.path.splitext(f)[1] == kind)

def _list_morph_extension_filenames(kind):
    return glob.glob(os.path.join(_get_morph_extension_directory(),
                                  '*' + kind))

def _get_extension_name(filename):
    return os.path.basename(filename)

def _get_repo_extension_contents(name, kind):
    repo_dir = _get_root_repo()
    return repo_dir.read_file(name + kind)

def _get_morph_extension_filename(name, kind):
    return os.path.join(_get_morph_extension_directory(), name + kind)

def _is_executable(filename):
    st = os.stat(filename)
    mask = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    return (stat.S_IMODE(st.st_mode) & mask) != 0

def _list_extensions(kind):
    repo_extension_filenames = []
    try:
        repo_extension_filenames = \
                _list_repo_extension_filenames(kind)
    except (sysbranchdir.NotInSystemBranch):
        # Squash this and just return no system branch extensions
        pass
    morph_extension_filenames = _list_morph_extension_filenames(kind)

    repo_extension_names = \
            (_get_extension_name(f) for f in repo_extension_filenames)
    morph_extension_names = \
            (_get_extension_name(f) for f in morph_extension_filenames)

    extension_names = set(repo_extension_names)
    extension_names.update(set(morph_extension_names))
    return list(extension_names)

def list_extensions(kind=None):
    """
    List all available extensions by 'kind'.

    'kind' should be one of '.write' or '.configure'.
    If 'kind' is not provided available extensions of both
    types will be returned.

    '.check' extensions are not listed here as they should
    be associated with a '.write' extension of the same name.
    """
    if kind:
        return _list_extensions(kind)
    else:
        configure_extensions = _list_extensions('.configure')
        write_extensions = _list_extensions('.write')

        return configure_extensions + write_extensions

class get_extension_filename():
    """
    Find the filename of an extension by its 'name' and 'kind'.

    'kind' should be one of '.configure', '.write' or '.check'.

    '.help' files for the extensions may also be retrieved by
    passing the kind as '.write.help' or '.configure.help'.

    If the extension is in the build repository then a temporary
    file will be created, which will be deleted on exting the with block.
    """
    def __init__(self, name, kind, executable=True):
        self.name = name
        self.kind = kind
        self.executable = executable
        self.delete = False

    def __enter__(self):
        ext_filename = None
        try:
            ext_contents = _get_repo_extension_contents(self.name,
                                                        self.kind)
        except (IOError, cliapp.AppException, sysbranchdir.NotInSystemBranch):
            # Not found: look for it in the Morph code.
            ext_filename = _get_morph_extension_filename(self.name, self.kind)
            if not os.path.exists(ext_filename):
                raise ExtensionNotFoundError(
                    'Could not find extension %s%s' % (self.name, self.kind))
            if self.executable and not _is_executable(ext_filename):
                raise ExtensionNotExecutableError(
                    'Extension not executable: %s' % ext_filename)
        else:
            # Found it in the system morphology's repository.
            fd, ext_filename = tempfile.mkstemp()
            os.write(fd, ext_contents)
            os.close(fd)
            os.chmod(ext_filename, 0700)
            self.delete = True

        self.ext_filename = ext_filename
        return ext_filename

    def __exit__(self, type, value, trace):
        if self.delete:
            os.remove(self.ext_filename)


class _EOFWrapper(asyncore.file_wrapper):
    '''File object that reports when it hits EOF

    The async_chat class doesn't notice that its input file has hit EOF,
    so if we give it one of these instead, it will mark the chatter for
    closiure and ensure any in-progress buffers are flushed.
    '''
    def __init__(self, dispatcher, fd):
        self._dispatcher = dispatcher
        asyncore.file_wrapper.__init__(self, fd)

    def recv(self, *args):
        data = asyncore.file_wrapper.recv(self, *args)
        if not data:
            self._dispatcher.close_when_done()
            # ensure any unterminated data is flushed
            return self._dispatcher.get_terminator()
        return data


class _OutputDispatcher(asynchat.async_chat, asyncore.file_dispatcher):
    '''asyncore dispatcher that calls line_handler per line.'''
    def __init__(self, fd, line_handler, map=None):
        asynchat.async_chat.__init__(self, sock=None, map=map)
        asyncore.file_dispatcher.__init__(self, fd=fd, map=map)
        self.set_terminator('\n')
        self._line_handler = line_handler
    collect_incoming_data = asynchat.async_chat._collect_incoming_data
    def set_file(self, fd):
        self.socket = _EOFWrapper(self, fd)
        self._fileno = self.socket.fileno()
        self.add_channel()
    def found_terminator(self):
        self._line_handler(''.join(self.incoming))
        self.incoming = []

class ExtensionSubprocess(object):

    def __init__(self, report_stdout, report_stderr, report_logger):
        self._report_stdout = report_stdout
        self._report_stderr = report_stderr
        self._report_logger = report_logger

    def run(self, filename, args, cwd, env):
        '''Run an extension.

        Anything written by the extension to stdout is passed to status(), thus
        normally echoed to Morph's stdout. An extra FD is passed in the
        environment variable MORPH_LOG_FD, and anything written here will be
        included as debug messages in Morph's log file.

        '''

        log_read_fd, log_write_fd = os.pipe()

        try:
            new_env = env.copy()
            new_env['MORPH_LOG_FD'] = str(log_write_fd)

            # Because we don't have python 3.2's pass_fds, we have to
            # play games with preexec_fn to close the fds we don't
            # need to inherit
            def close_read_end():
                os.close(log_read_fd)
            p = subprocess.Popen(
                ['unshare', '-m', '--', '/bin/sh', '-c',
                 'mount --make-rprivate / && exec "$@"', '-', filename] + args,
                cwd=cwd, env=new_env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                preexec_fn=close_read_end)
            os.close(log_write_fd)
            log_write_fd = None

            return self._watch_extension_subprocess(p, log_read_fd)
        finally:
            os.close(log_read_fd)
            if log_write_fd is not None:
                os.close(log_write_fd)

    def _watch_extension_subprocess(self, p, log_read_fd):
        '''Follow stdout, stderr and log output of an extension subprocess.'''

        try:
            socket_map = {}
            for handler, fd in ((self._report_stdout, p.stdout),
                                (self._report_stderr, p.stderr),
                                (self._report_logger, log_read_fd)):
                _OutputDispatcher(line_handler=handler, fd=fd,
                                  map=socket_map)
            asyncore.loop(use_poll=True, map=socket_map)

            returncode = p.wait()
            assert returncode is not None
        except BaseException as e:
            logging.debug('Received exception %r watching extension' % e)
            p.terminate()
            p.wait()
            raise
        finally:
            p.stdout.close()
            p.stderr.close()

        return returncode
