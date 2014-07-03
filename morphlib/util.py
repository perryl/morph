# Copyright (C) 2011-2014  Codethink Limited
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

import itertools
import os
import re
import subprocess

import fs.osfs

import morphlib

'''Utility functions for morph.'''


# It is intentional that if collections does not have OrderedDict that
# simplejson is also used in preference to json, as OrderedDict became
# a member of collections in the same release json got its object_pairs_hook
try: # pragma: no cover
    from collections import OrderedDict
    import json
except ImportError: # pragma: no cover
    from ordereddict import OrderedDict
    import simplejson as json

try:
    from multiprocessing import cpu_count
except NotImplementedError:  # pragma: no cover
    cpu_count = lambda: 1
import os


def indent(string, spaces=4):
    '''Return ``string`` indented by ``spaces`` spaces.

    The final line is not terminated by a newline. This makes it easy
    to use this function for indenting long text for logging: the
    logging library adds a newline, so not including it in the indented
    text avoids a spurious empty line in the log file.

    This also makes the result be a plain ASCII encoded string.

    '''

    if type(string) == unicode:  # pragma: no cover
        string = string.decode('utf-8')
    lines = string.splitlines()
    lines = ['%*s%s' % (spaces, '', line) for line in lines]
    return '\n'.join(lines)


def sanitise_morphology_path(morph_name):
    '''Turn morph_name into a file path to a morphology.

    We support both a file path being provided, and just the morphology
    name for backwards compatibility.

    '''
    if morph_name.endswith('.morph'):
        return morph_name

    if '/' in morph_name:
        # This must be a new-style path reference. Require the user to specify
        # '.morph' in the filename.
        return morph_name
    else:
        return morph_name + '.morph'


def make_concurrency(cores=None):
    '''Return the number of concurrent jobs for make.

    This will be given to make as the -j argument.

    '''

    n = cpu_count() if cores is None else cores
    # Experimental results (ref. Kinnison) says a factor of 1.5
    # gives about the optimal result for build times, since much of
    # builds are I/O bound, not CPU bound.
    return max(int(n * 1.5 + 0.5), 1)


def create_cachedir(settings):  # pragma: no cover
    '''Return cache directory, creating it if necessary.'''

    cachedir = settings['cachedir']
    if not os.path.exists(cachedir):
        os.mkdir(cachedir)
    return cachedir


def get_artifact_cache_server(settings): # pragma: no cover
    if settings['artifact-cache-server']:
        return settings['artifact-cache-server']
    if settings['cache-server']:
        return settings['cache-server']
    return None


def get_git_resolve_cache_server(settings): # pragma: no cover
    if settings['git-resolve-cache-server']:
        return settings['git-resolve-cache-server']
    if settings['cache-server']:
        return settings['cache-server']
    return None


def new_artifact_caches(settings):  # pragma: no cover
    '''Create new objects for local and remote artifact caches.

    This includes creating the directories on disk, if missing.

    '''

    cachedir = create_cachedir(settings)
    artifact_cachedir = os.path.join(cachedir, 'artifacts')
    if not os.path.exists(artifact_cachedir):
        os.mkdir(artifact_cachedir)

    lac = morphlib.localartifactcache.LocalArtifactCache(
            fs.osfs.OSFS(artifact_cachedir))

    rac_url = get_artifact_cache_server(settings)
    rac = None
    if rac_url:
        rac = morphlib.remoteartifactcache.RemoteArtifactCache(rac_url)
    return lac, rac


def combine_aliases(app):  # pragma: no cover
    '''Create a full repo-alias set from the app's settings.'''
    trove_host = app.settings['trove-host']
    trove_ids = app.settings['trove-id']
    repo_aliases = app.settings['repo-alias']
    repo_pat = r'^(?P<prefix>[a-z][a-z0-9-]+)=(?P<pull>[^#]+)#(?P<push>[^#]+)$'
    trove_pat = (r'^(?P<prefix>[a-z][a-z0-9-]+)=(?P<path>[^#]+)#'
                 '(?P<pull>[^#]+)#(?P<push>[^#]+)$')
    alias_map = {}
    def _expand(protocol, path):
        if protocol == "git":
            return "git://%s/%s/%%s" % (trove_host, path)
        elif protocol == "ssh":
            return "ssh://git@%s/%s/%%s" % (trove_host, path)
        else:
            raise morphlib.Error(
                'Unknown protocol in trove_id: %s' % protocol)

    if trove_host:
        alias_map['baserock'] = "baserock=%s#%s" % (
            _expand('git', 'baserock'),
            _expand('ssh', 'baserock'))
        alias_map['upstream'] = "upstream=%s#%s" % (
            _expand('git', 'delta'),
            _expand('ssh', 'delta'))
        for trove_id in trove_ids:
            m = re.match(trove_pat, trove_id)
            if m:
                alias_map[m.group('prefix')] = "%s=%s#%s" % (
                    m.group('prefix'),
                    _expand(m.group('pull'), m.group('path')),
                    _expand(m.group('push'), m.group('path')))
            elif '=' not in trove_id:
                alias_map[trove_id] = "%s=%s#%s" % (
                    trove_id,
                    _expand('ssh', trove_id),
                    _expand('ssh', trove_id))
    for repo_alias in repo_aliases:
        m = re.match(repo_pat, repo_alias)
        if m:
            alias_map[m.group('prefix')] = repo_alias
        else:
            raise morphlib.Error(
                'Invalid repo-alias: %s' % repo_alias)


    return alias_map.values()

def new_repo_caches(app):  # pragma: no cover
    '''Create new objects for local, remote git repository caches.'''

    aliases = app.settings['repo-alias']
    cachedir = create_cachedir(app.settings)
    gits_dir = os.path.join(cachedir, 'gits')
    tarball_base_url = app.settings['tarball-server']
    repo_resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)
    lrc = morphlib.localrepocache.LocalRepoCache(
        app, gits_dir, repo_resolver, tarball_base_url=tarball_base_url)

    url = get_git_resolve_cache_server(app.settings)
    if url:
        rrc = morphlib.remoterepocache.RemoteRepoCache(url, repo_resolver)
    else:
        rrc = None

    return lrc, rrc


def log_dict_diff(app, cur, pre): # pragma: no cover
    '''Log the differences between two dicts to debug log'''
    dictA = cur
    dictB = pre
    for key in dictA.keys():
        if key not in dictB:
            app.status(msg="New environment: %(key)s = %(value)s",
                       key=key, value=dictA[key], chatty=True)
        elif dictA[key] != dictB[key]:
            app.status(msg="Environment changed: \
                %(key)s = %(valA)s to %(key)s = %(valB)s",
                key=key, valA=dictA[key], valB=dictB[key], chatty=True)
    for key in dictB.keys():
        if key not in dictA:
            app.status(msg="Environment removed:  %(key)s = %(value)s",
                       key=key, value=dictB[key], chatty=True)


# This acquired from rdiff-backup which is GPLv2+ and a patch from 2011
# which has not yet been merged, combined with a tad of tidying from us.
def copyfileobj(inputfp, outputfp, blocksize=1024*1024):  # pragma: no cover
    """Copies file inputfp to outputfp in blocksize intervals"""

    sparse = False
    buf = None
    while 1:
        inbuf = inputfp.read(blocksize)
        if not inbuf: break
        if not buf:
            buf = inbuf
        else:
            buf += inbuf

        # Combine "short" reads
        if (len(buf) < blocksize):
            continue

        buflen = len(buf)
        if buf == "\x00" * buflen:
            outputfp.seek(buflen, os.SEEK_CUR)
            buf = None
            # flag sparse=True, that we seek()ed, but have not written yet
            # The filesize is wrong until we write
            sparse = True
        else:
            outputfp.write(buf)
            buf = None
            # We wrote, so clear sparse.
            sparse = False

    if buf:
        outputfp.write(buf)
    elif sparse:
        outputfp.seek(-1, os.SEEK_CUR)
        outputfp.write("\x00")

def get_bytes_free_in_path(path): # pragma: no cover
    """Returns the bytes free in the filesystem that path is part of"""

    fsinfo = os.statvfs(path)
    return fsinfo.f_bavail * fsinfo.f_bsize

def on_same_filesystem(path_a, path_b): # pragma: no cover
    """Tests whether both paths are on the same fileystem

       Note behaviour may be unexpected on btrfs, since subvolumes
       appear to be on a different device, but share a storage pool.

    """
    # TODO: return true if one path is a subvolume of the other on btrfs?
    return os.stat(path_a).st_dev == os.stat(path_b).st_dev

def unify_space_requirements(tmp_path, tmp_min_size,
                             cache_path, cache_min_size): # pragma: no cover
    """Adjust minimum sizes when paths share a disk.

       Given pairs of path and minimum size, return the minimum sizes such
       that when the paths are on the same disk, the sizes are added together.

    """
    # TODO: make this work for variable number of (path, size) pairs as needed
    #       hint: try list.sort and itertools.groupby
    if not on_same_filesystem(tmp_path, cache_path):
        return tmp_min_size, cache_min_size
    unified_size = tmp_min_size + cache_min_size
    return unified_size, unified_size

def check_disk_available(tmp_path, tmp_min_size,
                         cache_path, cache_min_size): # pragma: no cover
    # if both are on the same filesystem, assume they share a storage pool,
    # so the sum of the two sizes needs to be available
    # TODO: if we need to do this on any more than 2 paths
    #       extend it to take a [(path, min)]
    tmp_min_size, cache_min_size = unify_space_requirements(
        tmp_path, tmp_min_size, cache_path, cache_min_size)
    tmp_size, cache_size = map(get_bytes_free_in_path, (tmp_path, cache_path))
    errors = []
    for path, min in [(tmp_path, tmp_min_size), (cache_path, cache_min_size)]:
        free = get_bytes_free_in_path(path)
        if free < min:
            errors.append('\t%(path)s requires %(min)d bytes free, '
                          'has %(free)d' % locals())
    if not errors:
        return
    raise morphlib.Error('Insufficient space on disk:\n' +
                         '\n'.join(errors) + '\n'
                         'Please run `morph gc`. If the problem persists '
                         'increase the disk size, manually clean up some '
                         'space or reduce the disk space required by the '
                         'tempdir-min-space and cachedir-min-space '
                         'configuration options.')




def find_root(dirname, subdir_name):
    '''Find parent of a directory, at or above a given directory.

    The sought-after directory is indicated by the existence of a
    subdirectory of the indicated name. For example, dirname might
    be the current working directory of the process, and subdir_name
    might be ".morph"; then the returned value would be the Morph
    workspace root directory, which has a subdirectory called
    ".morph".

    Return path to desired directory, or None if not found.

    '''

    dirname = os.path.normpath(os.path.abspath(dirname))
    while not os.path.isdir(os.path.join(dirname, subdir_name)):
        if dirname == '/':
            return None
        dirname = os.path.dirname(dirname)
    return dirname


def find_leaves(search_dir, subdir_name):
    '''This is like find_root, except it looks towards leaves.

    The directory tree, starting at search_dir is traversed.

    If a directory has a subdirectory called subdir_name, then
    the directory is returned.

    It does not recurse into a leaf's subdirectories.

    '''

    for dirname, subdirs, filenames in os.walk(search_dir):
        if subdir_name in subdirs:
            del subdirs[:]
            yield dirname


def find_leaf(dirname, subdir_name):
    '''This is like find_root, except it looks towards leaves.

    If there are no subdirectories, or more than one, fail.

    '''

    leaves = list(find_leaves(dirname, subdir_name))
    if len(leaves) == 1:
        return leaves[0]
    return None


class EnvironmentAlreadySetError(morphlib.Error):

    def __init__(self, conflicts):
        self.conflicts = conflicts
        morphlib.Error.__init__(
            self, 'Keys %r are already set in the environment' % conflicts)


def parse_environment_pairs(env, pairs):
    '''Add key=value pairs to the environment dict.

    Given a dict and a list of strings of the form key=value,
    set dict[key] = value, unless key is already set in the
    environment, at which point raise an exception.

    This does not modify the passed in dict.

    Returns the extended dict.

    '''

    extra_env = dict(p.split('=', 1) for p in pairs)
    conflicting = [k for k in extra_env if k in env]
    if conflicting:
        raise EnvironmentAlreadySetError(conflicting)

    # Return a dict that is the union of the two
    # This is not the most performant, since it creates
    # 3 unnecessary lists, but I felt this was the most
    # easy to read. Using itertools.chain may be more efficicent
    return dict(env.items() + extra_env.items())


def has_hardware_fp(): # pragma: no cover
    '''
    This function returns whether the binary /proc/self/exe is compiled
    with hardfp _not_ whether the platform is hardfp.

    We expect the binaries on our build platform to be compiled with
    hardfp.

    This is not ideal but at the time of writing this is the only
    reliable way to decide whether our architecture is a hardfp
    architecture.
    '''

    output = subprocess.check_output(['readelf', '-A', '/proc/self/exe'])
    return 'Tag_ABI_VFP_args: VFP registers' in output


def get_host_architecture(): # pragma: no cover
    '''Get the canonical Morph name for the host's architecture.'''

    machine = os.uname()[-1]

    table = {
        'x86_64': 'x86_64',
        'i386': 'x86_32',
        'i486': 'x86_32',
        'i586': 'x86_32',
        'i686': 'x86_32',
        'armv7l': 'armv7l',
        'armv7b': 'armv7b',
        'ppc64': 'ppc64'
    }

    if machine not in table:
        raise morphlib.Error('Unknown host architecture %s' % machine)

    if machine == 'armv7l' and has_hardware_fp():
        return 'armv7lhf'

    return table[machine]


def sanitize_environment(env):
    for k in env:
        env[k] = str(env[k])

def iter_trickle(iterable, limit):
    '''Split an iterable up into `limit` length chunks.'''
    it = iter(iterable)
    while True:
        buf = list(itertools.islice(it, limit))
        if len(buf) == 0:
           break
        yield buf
