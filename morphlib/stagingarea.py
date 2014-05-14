# Copyright (C) 2012-2014  Codethink Limited
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


import logging
import os
import shutil
import stat
import cliapp
from urlparse import urlparse
import tempfile

import morphlib


class StagingArea(object):

    '''Represent the staging area for building software.

    The staging area is a temporary directory. In normal operation the build
    dependencies of the artifact being built are installed into the staging
    area and then 'chroot' is used to isolate the build processes from the host
    system. Chunks built in 'test' or 'build-essential' mode have an empty
    staging area and are allowed to use the tools of the host.

    '''

    _base_path = ['/sbin', '/usr/sbin', '/bin', '/usr/bin']

    def __init__(self, app, dirname, build_env, use_chroot=True, extra_env={},
                 extra_path=[]):
        self._app = app
        self.dirname = dirname
        self.builddirname = None
        self.destdirname = None
        self.mounted = []
        self._bind_readonly_mount = None

        self.use_chroot = use_chroot
        self.env = build_env.env
        self.env.update(extra_env)

        if use_chroot:
            path = extra_path + build_env.extra_path + self._base_path
        else:
            rel_path = extra_path + build_env.extra_path
            full_path = [os.path.normpath(dirname + p) for p in rel_path]
            path = full_path + os.environ['PATH'].split(':')
        self.env['PATH'] = ':'.join(path)

    # Wrapper to be overridden by unit tests.
    def _mkdir(self, dirname):  # pragma: no cover
        os.makedirs(dirname)

    def _dir_for_source(self, source, suffix):
        dirname = os.path.join(self.dirname,
                               '%s.%s' % (source.morphology['name'], suffix))
        self._mkdir(dirname)
        return dirname

    def builddir(self, source):
        '''Create a build directory for a given source project.

        Return path to directory.

        '''

        return self._dir_for_source(source, 'build')

    def destdir(self, source):
        '''Create an installation target directory for a given source project.

        This is meant to be used as $DESTDIR when installing chunks.
        Return path to directory.

        '''

        return self._dir_for_source(source, 'inst')

    def relative(self, filename):
        '''Return a filename relative to the staging area.'''

        if not self.use_chroot:
            return filename

        dirname = self.dirname
        if not dirname.endswith('/'):
            dirname += '/'

        assert filename.startswith(dirname)
        return filename[len(dirname) - 1:]  # include leading slash

    def hardlink_all_files(self, srcpath, destpath): # pragma: no cover
        '''Hardlink every file in the path to the staging-area

        If an exception is raised, the staging-area is indeterminate.

        '''

        file_stat = os.lstat(srcpath)
        mode = file_stat.st_mode

        if stat.S_ISDIR(mode):
            # Ensure directory exists in destination, then recurse.
            if not os.path.lexists(destpath):
                os.makedirs(destpath)
            dest_stat = os.stat(os.path.realpath(destpath))
            if not stat.S_ISDIR(dest_stat.st_mode):
                raise IOError('Destination not a directory. source has %s'
                              ' destination has %s' % (srcpath, destpath))

            for entry in os.listdir(srcpath):
                self.hardlink_all_files(os.path.join(srcpath, entry),
                                        os.path.join(destpath, entry))
        elif stat.S_ISLNK(mode):
            # Copy the symlink.
            if os.path.lexists(destpath):
                os.remove(destpath)
            os.symlink(os.readlink(srcpath), destpath)

        elif stat.S_ISREG(mode):
            # Hardlink the file.
            if os.path.lexists(destpath):
                os.remove(destpath)
            os.link(srcpath, destpath)

        elif stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            # Block or character device. Put contents of st_dev in a mknod.
            if os.path.lexists(destpath):
                os.remove(destpath)
            os.mknod(destpath, file_stat.st_mode, file_stat.st_rdev)
            os.chmod(destpath, file_stat.st_mode)

        else:
            # Unsupported type.
            raise IOError('Cannot extract %s into staging-area. Unsupported'
                          ' type.' % srcpath)

    def install_artifact(self, handle):
        '''Install a build artifact into the staging area.

        We access the artifact via an open file handle. For now, we assume
        the artifact is a tarball.

        '''

        chunk_cache_dir = os.path.join(self._app.settings['tempdir'], 'chunks')
        unpacked_artifact = os.path.join(
            chunk_cache_dir, os.path.basename(handle.name) + '.d')
        if not os.path.exists(unpacked_artifact):
            self._app.status(
                msg='Unpacking chunk from cache %(filename)s',
                filename=os.path.basename(handle.name))
            savedir = tempfile.mkdtemp(dir=chunk_cache_dir)
            try:
                morphlib.bins.unpack_binary_from_file(
                    handle, savedir + '/')
            except BaseException, e: # pragma: no cover
                shutil.rmtree(savedir)
                raise
            # TODO: This rename is not concurrency safe if two builds are
            #       extracting the same chunk, one build will fail because
            #       the other renamed its tempdir here first.
            os.rename(savedir, unpacked_artifact)

        if not os.path.exists(self.dirname):
            self._mkdir(self.dirname)

        self.hardlink_all_files(unpacked_artifact, self.dirname)

    def remove(self):
        '''Remove the entire staging area.

        Do not expect anything with the staging area to work after this
        method is called. Be careful about calling this method if
        the filesystem root directory was given as the dirname.

        '''

        shutil.rmtree(self.dirname)

    to_mount = (
        ('proc',    'proc',  'none'),
        ('dev/shm', 'tmpfs', 'none'),
    )

    def mount_ccachedir(self, source): #pragma: no cover
        ccache_dir = self._app.settings['compiler-cache-dir']
        if not os.path.isdir(ccache_dir):
            os.makedirs(ccache_dir)
        # Get a path for the repo's ccache
        ccache_url = source.repo.url
        ccache_path = urlparse(ccache_url).path
        ccache_repobase = os.path.basename(ccache_path)
        if ':' in ccache_repobase: # the basename is a repo-alias
            resolver = morphlib.repoaliasresolver.RepoAliasResolver(
                self._app.settings['repo-alias'])
            ccache_url = resolver.pull_url(ccache_repobase)
            ccache_path = urlparse(ccache_url).path
            ccache_repobase = os.path.basename(ccache_path)
        if ccache_repobase.endswith('.git'):
            ccache_repobase = ccache_repobase[:-len('.git')]

        ccache_repodir = os.path.join(ccache_dir, ccache_repobase)
        # Make sure that directory exists
        if not os.path.isdir(ccache_repodir):
            os.mkdir(ccache_repodir)
        # Get the destination path
        ccache_destdir= os.path.join(self.dirname, 'tmp', 'ccache')
        # Make sure that the destination exists. We'll create /tmp if necessary
        # to avoid breaking when faced with an empty staging area.
        if not os.path.isdir(ccache_destdir):
            os.makedirs(ccache_destdir)
        # Mount it into the staging-area
        self._app.runcmd(['mount', '--bind', ccache_repodir,
                         ccache_destdir])
        return ccache_destdir

    def do_mounts(self, setup_mounts):  # pragma: no cover
        if not setup_mounts:
            return
        for mount_point, mount_type, source in self.to_mount:
            logging.debug('Mounting %s in staging area' % mount_point)
            path = os.path.join(self.dirname, mount_point)
            if not os.path.exists(path):
                os.makedirs(path)
            morphlib.fsutils.mount(self._app.runcmd, source, path, mount_type)
            self.mounted.append(path)
        return

    def do_unmounts(self):  # pragma: no cover
        for path in reversed(self.mounted):
            logging.debug('Unmounting %s in staging area' % path)
            morphlib.fsutils.unmount(self._app.runcmd, path)

    def chroot_open(self, source, setup_mounts): # pragma: no cover
        '''Setup staging area for use as a chroot.'''

        assert self.builddirname == None and self.destdirname == None

        builddir = self.builddir(source)
        destdir = self.destdir(source)
        self.builddirname = builddir
        self.destdirname = destdir

        self.do_mounts(setup_mounts)

        if not self._app.settings['no-ccache']:
            self.mounted.append(self.mount_ccachedir(source))

        return builddir, destdir

    def chroot_close(self): # pragma: no cover
        '''Undo changes by chroot_open.

        This should be called after the staging area is no longer needed.

        '''

        self.do_unmounts()

    def runcmd(self, argv, **kwargs):  # pragma: no cover
        '''Run a command in a chroot in the staging area.'''
        assert 'env' not in kwargs
        kwargs['env'] = self.env
        if 'extra_env' in kwargs:
            kwargs['env'].update(kwargs['extra_env'])
            del kwargs['extra_env']

        if 'cwd' in kwargs:
            cwd = kwargs['cwd']
            del kwargs['cwd']
        else:
            cwd = '/'

        chroot_dir = self.dirname if self.use_chroot else '/'
        temp_dir = kwargs["env"].get("TMPDIR", "/tmp")

        staging_dirs = [self.builddirname, self.destdirname]
        if self.use_chroot:
            staging_dirs += ["dev", "proc", temp_dir.lstrip('/')]
        do_not_mount_dirs = [os.path.join(self.dirname, d)
                             for d in staging_dirs]
        if not self.use_chroot:
            do_not_mount_dirs += [temp_dir]

        logging.debug("Not mounting dirs %r" % do_not_mount_dirs)

        real_argv = ['linux-user-chroot', '--chdir', cwd, '--unshare-net']
        for d in morphlib.fsutils.invert_paths(os.walk(chroot_dir),
                                               do_not_mount_dirs):
            if not os.path.islink(d):
                real_argv += ['--mount-readonly', self.relative(d)]

        real_argv += [chroot_dir]

        real_argv += argv

        try:
            if 'logfile' in kwargs:
                logfile = kwargs['logfile']
                del kwargs['logfile']

                if logfile:
                    teecmd = ['tee', '-a', logfile]
                    return self._app.runcmd(real_argv, teecmd, **kwargs)
                else:
                    return self._app.runcmd(real_argv, **kwargs)
        except cliapp.AppException as e:
            raise cliapp.AppException('In staging area %s: running '
                                      'command \'%s\' failed.' % 
                                      (self.dirname, ' '.join(argv)))

    def abort(self): # pragma: no cover
        '''Handle what to do with a staging area in the case of failure.
           This may either remove it or save it for later inspection.
        '''
        # TODO: when we add the option to throw away failed builds,
        #       hook it up here


        dest_dir = os.path.join(self._app.settings['tempdir'],
                                'failed', os.path.basename(self.dirname))
        os.rename(self.dirname, dest_dir)
        self.dirname = dest_dir

