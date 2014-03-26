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


from collections import defaultdict
import datetime
import errno
import json
import logging
import os
from os.path import relpath
import shutil
import stat
import tarfile
import time
import traceback
import subprocess
import tempfile
import gzip

import cliapp

import morphlib
from morphlib.artifactcachereference import ArtifactCacheReference
import morphlib.gitversion

def extract_sources(app, repo_cache, repo, sha1, srcdir): #pragma: no cover
    '''Get sources from git to a source directory, including submodules'''

    def extract_repo(repo, sha1, destdir):
        app.status(msg='Extracting %(source)s into %(target)s',
                   source=repo.original_name,
                   target=destdir)

        repo.checkout(sha1, destdir)
        morphlib.git.reset_workdir(app.runcmd, destdir)
        submodules = morphlib.git.Submodules(app, repo.path, sha1)
        try:
            submodules.load()
        except morphlib.git.NoModulesFileError:
            return []
        else:
            tuples = []
            for sub in submodules:
                cached_repo = repo_cache.get_repo(sub.url)
                sub_dir = os.path.join(destdir, sub.path)
                tuples.append((cached_repo, sub.commit, sub_dir))
            return tuples

    todo = [(repo, sha1, srcdir)]
    while todo:
        repo, sha1, srcdir = todo.pop()
        todo += extract_repo(repo, sha1, srcdir)
    set_mtime_recursively(srcdir)

def set_mtime_recursively(root):  # pragma: no cover
    '''Set the mtime for every file in a directory tree to the same.

    We do this because git checkout does not set the mtime to anything,
    and some projects (binutils, gperf for example) include formatted
    documentation and try to randomly build things or not because of
    the timestamps. This should help us get more reliable  builds.

    '''

    now = time.time()
    for dirname, subdirs, basenames in os.walk(root.encode("utf-8"),
                                               topdown=False):
        for basename in basenames:
            pathname = os.path.join(dirname, basename)
            # we need the following check to ignore broken symlinks
            if os.path.exists(pathname):
                os.utime(pathname, (now, now))
        os.utime(dirname, (now, now))

def ldconfig(runcmd, rootdir):  # pragma: no cover
    '''Run ldconfig for the filesystem below ``rootdir``.

    Essentially, ``rootdir`` specifies the root of a new system.
    Only directories below it are considered.

    ``etc/ld.so.conf`` below ``rootdir`` is assumed to exist and
    be populated by the right directories, and should assume
    the root directory is ``rootdir``. Example: if ``rootdir``
    is ``/tmp/foo``, then ``/tmp/foo/etc/ld.so.conf`` should
    contain ``/lib``, not ``/tmp/foo/lib``.

    The ldconfig found via ``$PATH`` is used, not the one in ``rootdir``,
    since in bootstrap mode that might not yet exist, the various
    implementations should be compatible enough.

    '''

    # FIXME: use the version in ROOTDIR, since even in
    # bootstrap it will now always exist due to being part of build-essential

    conf = os.path.join(rootdir, 'etc', 'ld.so.conf')
    if os.path.exists(conf):
        logging.debug('Running ldconfig for %s' % rootdir)
        cache = os.path.join(rootdir, 'etc', 'ld.so.cache')

        # The following trickery with $PATH is necessary during the Baserock
        # bootstrap build: we are not guaranteed that PATH contains the
        # directory (/sbin conventionally) that ldconfig is in. Then again,
        # it might, and if so, we don't want to hardware a particular
        # location. So we add the possible locations to the end of $PATH
        env = dict(os.environ)
        old_path = env['PATH']
        env['PATH'] = '%s:/sbin:/usr/sbin:/usr/local/sbin' % old_path
        runcmd(['ldconfig', '-r', rootdir], env=env)
    else:
        logging.debug('No %s, not running ldconfig' % conf)


def download_depends(constituents, lac, rac, metadatas=None):
    for constituent in constituents:
        if not lac.has(constituent):
            source = rac.get(constituent)
            target = lac.put(constituent)
            shutil.copyfileobj(source, target)
            target.close()
            source.close()
        if metadatas is not None:
            for metadata in metadatas:
                if not lac.has_artifact_metadata(constituent, metadata):
                    if rac.has_artifact_metadata(constituent, metadata):
                        src = rac.get_artifact_metadata(constituent, metadata)
                        dst = lac.put_artifact_metadata(constituent, metadata)
                        shutil.copyfileobj(src, dst)
                        dst.close()
                        src.close()


def get_chunk_files(f):  # pragma: no cover
    tar = tarfile.open(fileobj=f)
    for member in tar.getmembers():
        if member.type is not tarfile.DIRTYPE:
            yield member.name
    tar.close()


def get_stratum_files(f, lac):  # pragma: no cover
    for ca in (ArtifactCacheReference(a) for a in json.load(f)):
        cf = lac.get(ca)
        for filename in get_chunk_files(cf):
            yield filename
        cf.close()


def get_overlaps(artifact, constituents, lac):  # pragma: no cover
    # check whether strata overlap
    installed = defaultdict(set)
    for dep in constituents:
        handle = lac.get(dep)
        if artifact.source.morphology['kind'] == 'stratum':
            for filename in get_chunk_files(handle):
                installed[filename].add(dep)
        elif artifact.source.morphology['kind'] == 'system':
            for filename in get_stratum_files(handle, lac):
                installed[filename].add(dep)
        handle.close()
    overlaps = defaultdict(set)
    for filename, artifacts in installed.iteritems():
        if len(artifacts) > 1:
            overlaps[frozenset(artifacts)].add(filename)
    return overlaps


def log_overlaps(overlaps):  # pragma: no cover
    for overlapping, files in sorted(overlaps.iteritems()):
        logging.warning('  Artifacts %s overlap with files:' %
                        ', '.join(sorted(a.name for a in overlapping)))
        for filename in sorted(files):
            logging.warning('    %s' % filename)


def write_overlap_metadata(artifact, overlaps, lac):  # pragma: no cover
    f = lac.put_artifact_metadata(artifact, 'overlaps')
    # the big list comprehension is because json can't serialize
    # artifacts, sets or dicts with non-string keys
    json.dump(
        [
            [
                [a.name for a in afs], list(files)
            ] for afs, files in overlaps.iteritems()
        ], f, indent=4)
    f.close()


class BuilderBase(object):

    '''Base class for building artifacts.'''

    def __init__(self, app, staging_area, local_artifact_cache,
                 remote_artifact_cache, artifact, repo_cache, max_jobs,
                 setup_mounts):
        self.app = app
        self.staging_area = staging_area
        self.local_artifact_cache = local_artifact_cache
        self.remote_artifact_cache = remote_artifact_cache
        self.artifact = artifact
        self.repo_cache = repo_cache
        self.max_jobs = max_jobs
        self.build_watch = morphlib.stopwatch.Stopwatch()
        self.setup_mounts = setup_mounts

    def save_build_times(self):
        '''Write the times captured by the stopwatch'''
        meta = {
            'build-times': {}
        }
        for stage in self.build_watch.ticks.iterkeys():
            meta['build-times'][stage] = {
                'start': '%s' % self.build_watch.start_time(stage),
                'stop': '%s' % self.build_watch.stop_time(stage),
                'delta': '%.4f' % self.build_watch.start_stop_seconds(stage)
            }

        logging.debug('Writing metadata to the cache')
        with self.local_artifact_cache.put_source_metadata(
                self.artifact.source, self.artifact.cache_key,
                'meta') as f:
            json.dump(meta, f, indent=4, sort_keys=True)
            f.write('\n')

    def create_metadata(self, artifact_name, contents=[]):
        '''Create metadata to artifact to allow it to be reproduced later.

        The metadata is represented as a dict, which later on will be
        written out as a JSON file.

        '''

        assert isinstance(self.artifact.source.repo,
                          morphlib.cachedrepo.CachedRepo)
        meta = {
            'artifact-name': artifact_name,
            'source-name': self.artifact.source.morphology['name'],
            'kind': self.artifact.source.morphology['kind'],
            'description': self.artifact.source.morphology['description'],
            'repo': self.artifact.source.repo.url,
            'repo-alias': self.artifact.source.repo_name,
            'original_ref': self.artifact.source.original_ref,
            'sha1': self.artifact.source.sha1,
            'morphology': self.artifact.source.filename,
            'cache-key': self.artifact.cache_key,
            'cache-id': self.artifact.cache_id,
            'morph-version': {
                'ref': morphlib.gitversion.ref,
                'tree': morphlib.gitversion.tree,
                'commit': morphlib.gitversion.commit,
                'version': morphlib.gitversion.version,
            },
            'contents': contents,
        }

        return meta

    # Wrapper around open() to allow it to be overridden by unit tests.
    def _open(self, filename, mode):  # pragma: no cover
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        return open(filename, mode)

    def write_metadata(self, instdir, artifact_name, contents=[]):
        '''Write the metadata for an artifact.

        The file will be located under the ``baserock`` directory under
        instdir, named after ``cache_key`` with ``.meta`` as the suffix.
        It will be in JSON format.

        '''

        meta = self.create_metadata(artifact_name, contents)

        basename = '%s.meta' % artifact_name
        filename = os.path.join(instdir, 'baserock', basename)

        # Unit tests use StringIO, which in Python 2.6 isn't usable with
        # the "with" statement. So we don't do it with "with".
        f = self._open(filename, 'w')
        f.write(json.dumps(meta, indent=4, sort_keys=True))
        f.close()

    def new_artifact(self, artifact_name):
        '''Return an Artifact object for something built from our source.'''
        a = morphlib.artifact.Artifact(self.artifact.source, artifact_name)
        a.cache_key = self.artifact.cache_key
        return a

    def runcmd(self, *args, **kwargs):
        return self.staging_area.runcmd(*args, **kwargs)

class ChunkBuilder(BuilderBase):

    '''Build chunk artifacts.'''

    def create_devices(self, destdir): # pragma: no cover
        '''Creates device nodes if the morphology specifies them'''
        morphology = self.artifact.source.morphology
        perms_mask = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
        if 'devices' in morphology and morphology['devices'] is not None:
            for dev in morphology['devices']:
                destfile = os.path.join(destdir, './' + dev['filename'])
                mode = int(dev['permissions'], 8) & perms_mask
                if dev['type'] == 'c':
                    mode = mode | stat.S_IFCHR
                elif dev['type'] == 'b':
                    mode = mode | stat.S_IFBLK
                else:
                    raise IOError('Cannot create device node %s,'
                                  'unrecognized device type "%s"'
                                  % (destfile, dev['type']))
                self.app.status(msg="Creating device node %s"
                                    % destfile)
                os.mknod(destfile, mode,
                         os.makedev(dev['major'], dev['minor']))
                os.chown(destfile, dev['uid'], dev['gid'])

    def build_and_cache(self):  # pragma: no cover
        with self.build_watch('overall-build'):

            builddir, destdir = \
                self.staging_area.chroot_open(self.artifact.source,
                                              self.setup_mounts)
            log_name = None
            try:
                self.get_sources(builddir)
                with self.local_artifact_cache.put_source_metadata(
                        self.artifact.source, self.artifact.cache_key,
                        'build-log') as log:
                    log_name = log.real_filename
                    self.run_commands(builddir, destdir, log)
                    self.create_devices(destdir)
            except BaseException, e:
                logging.error('Caught exception: %s' % str(e))
                logging.info('Cleaning up staging area')
                self.staging_area.chroot_close()
                if log_name:
                    with open(log_name) as f:
                        for line in f:
                            logging.error('OUTPUT FROM FAILED BUILD: %s' %
                                          line.rstrip('\n'))
                self.staging_area.abort()
                raise
            self.staging_area.chroot_close()
            built_artifacts = self.assemble_chunk_artifacts(destdir)

        self.save_build_times()
        return built_artifacts


    def run_commands(self, builddir, destdir, logfile):  # pragma: no cover
        m = self.artifact.source.morphology
        bs = morphlib.buildsystem.lookup_build_system(m['build-system'])

        relative_builddir = self.staging_area.relative(builddir)
        relative_destdir = self.staging_area.relative(destdir)
        extra_env = { 'DESTDIR': relative_destdir }

        steps = [
            ('pre-configure', False),
            ('configure', False),
            ('post-configure', False),
            ('pre-build', True),
            ('build', True),
            ('post-build', True),
            ('pre-test', False),
            ('test', False),
            ('post-test', False),
            ('pre-install', False),
            ('install', False),
            ('post-install', False),
        ]
        for step, in_parallel in steps:
            with self.build_watch(step):
                key = '%s-commands' % step
                cmds = m.get_commands(key)
                if cmds:
                    self.app.status(msg='Running %(key)s', key=key)
                    logfile.write('# %s\n' % step)
                for cmd in cmds:
                    if in_parallel:
                        max_jobs = self.artifact.source.morphology['max-jobs']
                        if max_jobs is None:
                            max_jobs = self.max_jobs
                        extra_env['MAKEFLAGS'] = '-j%s' % max_jobs
                    else:
                        extra_env['MAKEFLAGS'] = '-j1'
                    try:
                        # flushing is needed because writes from python and
                        # writes from being the output in Popen have different
                        # buffers, but flush handles both
                        logfile.write('# # %s\n' % cmd)
                        logfile.flush()
                        self.runcmd(['sh', '-c', cmd],
                                    extra_env=extra_env,
                                    cwd=relative_builddir,
                                    stdout=logfile,
                                    stderr=subprocess.STDOUT)
                        logfile.flush()
                    except cliapp.AppException, e:
                        logfile.flush()
                        with open(logfile.name, 'r') as readlog:
                            self.app.output.write("%s failed\n" % step)
                            shutil.copyfileobj(readlog, self.app.output)
                        raise e

    def assemble_chunk_artifacts(self, destdir):  # pragma: no cover
        built_artifacts = []
        filenames = []
        source = self.artifact.source

        logging.debug('source: %s' % source)

        split_rules = source.split_rules

        def filepaths(destdir):
            for dirname, subdirs, basenames in os.walk(destdir):
                subdirsymlinks = [os.path.join(dirname, x) for x in subdirs
                                  if os.path.islink(x)]
                filenames = [os.path.join(dirname, x) for x in basenames]
                for relpath in (os.path.relpath(x, destdir) for x in
                                [dirname] + subdirsymlinks + filenames):
                    yield relpath

        with self.build_watch('determine-splits'):
            matches, overlaps, unmatched = \
                split_rules.partition(filepaths(destdir))

        with self.build_watch('create-chunks'):
            for chunk_artifact_name, chunk_artifact \
                in source.artifacts.iteritems():
                file_paths = matches[chunk_artifact_name]
                chunk_artifact = source.artifacts[chunk_artifact_name]

                def all_parents(path):
                    while path != '':
                        yield path
                        path = os.path.dirname(path)

                def parentify(filenames):
                    names = set()
                    for name in filenames:
                        names.update(all_parents(name))
                    return sorted(names)

                parented_paths = \
                    parentify(file_paths +
                              ['baserock/%s.meta' % chunk_artifact_name])

                logging.debug('chunk_artifact.basename(): %s' 
                    % chunk_artifact.basename())

                with self.local_artifact_cache.put(chunk_artifact) as f:
                    self.write_metadata(destdir, chunk_artifact_name,
                                        parented_paths)

                    self.app.status(msg='Creating chunk artifact %(name)s',
                                    name=chunk_artifact_name)
                    morphlib.bins.create_chunk(destdir, f, parented_paths)
                built_artifacts.append(chunk_artifact)

        for dirname, subdirs, files in os.walk(destdir):
            if files:
                raise Exception('DESTDIR %s is not empty: %s' %
                                (destdir, files))
        return built_artifacts

    def get_sources(self, srcdir):  # pragma: no cover
        s = self.artifact.source
        extract_sources(self.app, self.repo_cache, s.repo, s.sha1, srcdir)


class StratumBuilder(BuilderBase):
    '''Build stratum artifacts.'''

    def is_constituent(self, artifact):  # pragma: no cover
        '''True if artifact should be included in the stratum artifact'''
        return (artifact.source.morphology['kind'] == 'chunk' and \
                artifact.source.build_mode != 'bootstrap')

    def build_and_cache(self):  # pragma: no cover
        with self.build_watch('overall-build'):
            constituents = [d for d in self.artifact.dependencies
                            if self.is_constituent(d)]

            # the only reason the StratumBuilder has to download chunks is to
            # check for overlap now that strata are lists of chunks
            with self.build_watch('check-chunks'):
                # download the chunk artifact if necessary
                download_depends(constituents,
                                 self.local_artifact_cache,
                                 self.remote_artifact_cache)
                # check for chunk overlaps
                overlaps = get_overlaps(self.artifact, constituents,
                                        self.local_artifact_cache)
                if len(overlaps) > 0:
                    logging.warning('Overlaps in stratum artifact %s detected'
                                    % self.artifact.name)
                    log_overlaps(overlaps)
                    self.app.status(msg='Overlaps in stratum artifact '
                                        '%(stratum_name)s detected',
                                    stratum_name=self.artifact.name,
                                    error=True)
                    write_overlap_metadata(self.artifact, overlaps,
                                           self.local_artifact_cache)

            with self.build_watch('create-chunk-list'):
                lac = self.local_artifact_cache
                meta = self.create_metadata(self.artifact.name,
                                            [x.name for x in constituents])
                with lac.put_artifact_metadata(self.artifact, 'meta')  as f:
                    json.dump(meta, f, indent=4, sort_keys=True)
                with self.local_artifact_cache.put(self.artifact) as f:
                    json.dump([c.basename() for c in constituents], f)
        self.save_build_times()
        return [self.artifact]


class SystemBuilder(BuilderBase):  # pragma: no cover

    '''Build system image artifacts.'''

    def __init__(self, *args, **kwargs):
        BuilderBase.__init__(self, *args, **kwargs)
        self.args = args
        self.kwargs = kwargs

    def build_and_cache(self):
        self.app.status(msg='Building system %(system_name)s',
                        system_name=self.artifact.source.morphology['name'])

        with self.build_watch('overall-build'):
            arch = self.artifact.source.morphology['arch']

            rootfs_name = self.artifact.source.morphology['name'] + '-rootfs'
            rootfs_artifact = self.new_artifact(rootfs_name)
            handle = self.local_artifact_cache.put(rootfs_artifact)

            try:
                fs_root = self.staging_area.destdir(self.artifact.source)
                self.unpack_strata(fs_root)
                self.write_metadata(fs_root, rootfs_name)
                self.copy_kernel_into_artifact_cache(fs_root)
                unslashy_root = fs_root[1:]
                def uproot_info(info):
                    info.name = relpath(info.name, unslashy_root)
                    if info.islnk():
                        info.linkname = relpath(info.linkname,
                                                unslashy_root)
                    return info
                artiname = self.artifact.source.morphology['name']
                tar = tarfile.open(fileobj=handle, mode="w", name=artiname)
                self.app.status(msg='Constructing tarball of root filesystem',
                                chatty=True)
                tar.add(fs_root, recursive=True, filter=uproot_info)
                tar.close()
            except BaseException, e:
                logging.error(traceback.format_exc())
                self.app.status(msg='Error while building system',
                                error=True)
                handle.abort()
                raise

            handle.close()

        self.save_build_times()
        return [self.artifact]

    def unpack_one_stratum(self, stratum_artifact, target):
        '''Unpack a single stratum into a target directory'''

        cache = self.local_artifact_cache
        with cache.get(stratum_artifact) as stratum_file:
            artifact_list = json.load(stratum_file)
            for chunk in (ArtifactCacheReference(a) for a in artifact_list):
                self.app.status(msg='Unpacking chunk %(basename)s',
                                basename=chunk.basename(), chatty=True)
                with cache.get(chunk) as chunk_file:
                    morphlib.bins.unpack_binary_from_file(chunk_file, target)

        target_metadata = os.path.join(
                target, 'baserock', '%s.meta' % stratum_artifact.name)
        with cache.get_artifact_metadata(stratum_artifact, 'meta') as meta_src:
            with morphlib.savefile.SaveFile(target_metadata, 'w') as meta_dst:
                shutil.copyfileobj(meta_src, meta_dst)

    def unpack_strata(self, path):
        '''Unpack strata into a directory.'''

        self.app.status(msg='Unpacking strata to %(path)s',
                        path=path, chatty=True)
        with self.build_watch('unpack-strata'):
            # download the stratum artifacts if necessary
            download_depends(self.artifact.dependencies,
                             self.local_artifact_cache,
                             self.remote_artifact_cache,
                             ('meta',))

            # download the chunk artifacts if necessary
            for stratum_artifact in self.artifact.dependencies:
                f = self.local_artifact_cache.get(stratum_artifact)
                chunks = [ArtifactCacheReference(a) for a in json.load(f)]
                download_depends(chunks,
                                 self.local_artifact_cache,
                                 self.remote_artifact_cache)
                f.close()

            # check whether the strata overlap
            overlaps = get_overlaps(self.artifact, self.artifact.dependencies,
                                    self.local_artifact_cache)
            if len(overlaps) > 0:
                self.app.status(msg='Overlaps in system artifact '
                                    '%(artifact_name)s detected',
                                artifact_name=self.artifact.name,
                                error=True)
                log_overlaps(overlaps)
                write_overlap_metadata(self.artifact, overlaps,
                                       self.local_artifact_cache)

            # unpack it from the local artifact cache
            for stratum_artifact in self.artifact.dependencies:
                self.unpack_one_stratum(stratum_artifact, path)

            ldconfig(self.app.runcmd, path)

    def write_metadata(self, instdir, artifact_name):
        BuilderBase.write_metadata(self, instdir, artifact_name)

        os_release_file = os.path.join(instdir, 'etc', 'os-release')
        dirname = os.path.dirname(os_release_file)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        with morphlib.savefile.SaveFile(os_release_file, 'w') as f:
            f.write('NAME="Baserock"\n')
            f.write('ID=baserock\n')
            f.write('HOME_URL="http://wiki.baserock.org"\n')
            f.write('SUPPORT_URL="http://wiki.baserock.org/mailinglist"\n')
            f.write('BUG_REPORT_URL="http://wiki.baserock.org/mailinglist"\n')

        os.chmod(os_release_file, 0644)

    def copy_kernel_into_artifact_cache(self, path):
        '''Copy the installed kernel image into the local artifact cache.

        The kernel image will be a separate artifact from the root
        filesystem/disk image/whatever. This is sometimes useful with
        funky bootloaders or virtualisation.

        '''

        name = self.artifact.source.morphology['name'] + '-kernel'
        a = self.new_artifact(name)
        with self.local_artifact_cache.put(a) as dest:
            for basename in ['zImage', 'vmlinuz']:
                installed_path = os.path.join(path, 'boot', basename)
                if os.path.exists(installed_path):
                    with open(installed_path) as kernel:
                        shutil.copyfileobj(kernel, dest)
                    break


class Builder(object):  # pragma: no cover

    '''Helper class to build with the right BuilderBase subclass.'''

    classes = {
        'chunk': ChunkBuilder,
        'stratum': StratumBuilder,
        'system': SystemBuilder,
    }

    def __init__(self, app, staging_area, local_artifact_cache,
                 remote_artifact_cache, repo_cache, max_jobs, setup_mounts):
        self.app = app
        self.staging_area = staging_area
        self.local_artifact_cache = local_artifact_cache
        self.remote_artifact_cache = remote_artifact_cache
        self.repo_cache = repo_cache
        self.max_jobs = max_jobs
        self.setup_mounts = setup_mounts

    def build_and_cache(self, artifact):
        kind = artifact.source.morphology['kind']
        o = self.classes[kind](self.app, self.staging_area,
                               self.local_artifact_cache,
                               self.remote_artifact_cache, artifact,
                               self.repo_cache, self.max_jobs,
                               self.setup_mounts)
        self.app.status(msg='Builder.build: artifact %s with %s' %
                       (artifact.name, repr(o)),
                       chatty=True)
        built_artifacts = o.build_and_cache()
        self.app.status(msg='Builder.build: done',
                        chatty=True)
        return built_artifacts
