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

import collections
import cPickle
import logging
import os

import morphlib
import pylru


class PickleCacheManager(object):
    '''Cache manager for PyLRU that reads and writes to Pickle files.

    The 'pickle' format is less than ideal in many ways and is actually
    slower than JSON in Python. However, the data we need to cache is keyed
    by tuples and in JSON a dict can only be keyed with strings. For now,
    using 'pickle' seems to be the least worst option.

    '''

    def __init__(self, filename, size):
        self.filename = filename
        self.size = size

    def _populate_cache_from_file(self, filename, cache):
        try:
            with open(filename, 'r') as f:
                data = cPickle.load(f)
            for key, value in data.iteritems():
                cache[str(key)] = value
        except (EOFError, IOError, cPickle.PickleError) as e:
            logging.warning('Failed to load cache %s: %s', self.filename, e)

    def load_cache(self):
        '''Create a pylru.lrucache object prepopulated with saved data.'''
        cache = pylru.lrucache(self.size)
        # There should be a more efficient way to do this, by hooking into
        # the json module directly.
        if os.path.exists(self.filename):
            self._populate_cache_from_file(self.filename, cache)
        return cache

    def save_cache(self, cache):
        '''Save the data from a pylru.lrucache object to disk.

        Any changes that have been made by other instances or processes since
        load_cache() was called will be overwritten.

        '''
        data = {}
        for key, value in cache.items():
            data[key] = value
        try:
            with open(self.filename, 'w') as f:
                cPickle.dump(data, f)
        except (IOError, cPickle.PickleError) as e:
            logging.warning('Failed to save cache to %s: %s', self.filename, e)


class SourceResolverError(cliapp.AppException):
    pass


class MorphologyNotFoundError(SourceResolverError):
    def __init__(self, filename):
        SourceResolverError.__init__(
            self, "Couldn't find morphology: %s" % filename)


class NotcachedError(SourceResolverError):
    def __init__(self, repo_name):
        SourceResolverError.__init__(
            self, "Repository %s is not cached locally and there is no "
                  "remote cache specified" % repo_name)


class SourceResolver(object):
    '''Provides a way of resolving the set of sources for a given system.

    There are three levels of caching involved in resolving the sources to
    build.

    The canonical repo for each source is specified in the build-command
    (for strata and systems) or in the stratum morphology (for chunks). It will
    be either a normal URL, or a keyed URL using a repo-alias like
    'baserock:baserock/definitions'.

    The 'remote repo cache' is a Baserock Trove system. It functions as a
    normal Git server, but in addition it runs a service on port 8080 called
    'morph-cache-server' which can resolve refs, list their contents and read
    specific files from the repos it holds. This allows the SourceResolver to
    work out how to build something without cloning the whole repo. (If a local
    build of that source ends up being necessary then it will get cloned into
    the local cache later on).

    The second layer of caching is the local repository cache, which mirrors
    entire repositories in $cachedir/gits. If a repo is not in the remote repo
    cache then it must be present in the local repo cache.

    The third layer of caching is a simple commit SHA1 -> tree SHA mapping. It
    turns out that even if all repos are available locally, running
    'git rev-parse' on hundreds of repos requires a lot of IO and can take
    several minutes. Likewise, on a slow network connection it is time
    consuming to keep querying the remote repo cache. This third layer of
    caching works around both of those issues.

    The need for 3 levels of caching highlights design inconsistencies in
    Baserock, but for now it is worth the effort to maintain this code to save
    users from waiting 7 minutes each time that they want to build. The level 3
    cache is fairly simple because commits are immutable, so there is no danger
    of this cache being stale as long as it is indexed by commit SHA1. Due to
    the policy in Baserock of always using a commit SHA1 (rather than a named
    ref) in the system definitions, it makes repeated builds of a system very
    fast as no resolution needs to be done at all.

    '''

    def __init__(self, local_repo_cache, remote_repo_cache,
                 tree_cache_manager, update_repos, status_cb=None):
        self.lrc = local_repo_cache
        self.rrc = remote_repo_cache
        self.tree_cache_manager = tree_cache_manager

        self.update = update_repos
        self.status = status_cb

        self._resolved_trees = {}
        self._resolved_morphologies = {}
        self._resolved_buildsystems = {}

    def _resolve_ref(self, reponame, ref):
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating or cloning
        the repository into the local repo cache.

        This function is complex due to the 3 layers of caching described in
        the SourceResolver docstring.

        '''

        # The Baserock reference definitions use absolute refs so, and, if the
        # absref is cached, we can short-circuit all this code.
        if (reponame, ref) in self._resolved_trees:
            return ref, self._resolved_trees[ref]

        absref = None
        if self.lrc.has_repo(reponame):
            repo = self.lrc.get_repo(reponame)
            if self.update and repo.requires_update_for_ref(ref):
                self.status(msg='Updating cached git repository %(reponame)s '
                            'for ref %(ref)s', reponame=reponame, ref=ref)
                repo.update()
            # If the user passed --no-git-update, and the ref is a SHA1 not
            # available locally, this call will raise an exception.
            absref = repo.resolve_ref_to_commit(ref)
            tree = repo.resolve_ref_to_tree(absref)
        elif self.rrc is not None:
            try:
                absref, tree = self.rrc.resolve_ref(reponame, ref)
                if absref is not None:
                    self.status(msg='Resolved %(reponame)s %(ref)s via remote '
                                'repo cache',
                                reponame=reponame,
                                ref=ref,
                                chatty=True)
            except BaseException, e:
                logging.warning('Caught (and ignored) exception: %s' % str(e))
        if absref is None:
            if self.update:
                self.status(msg='Caching git repository %(reponame)s',
                            reponame=reponame)
                repo = self.lrc.cache_repo(reponame)
                repo.update()
            else:
                # This is likely to raise an exception, because if the local
                # repo cache had the repo we'd have already resolved the ref.
                repo = self.lrc.get_repo(reponame)
            absref = repo.resolve_ref_to_commit(ref)
            tree = repo.resolve_ref_to_tree(absref)
        return absref, tree

    def _get_morphology(self, reponame, sha1, filename):
        '''Read the morphology at the specified location.

        Returns None if the file does not exist in the specified commit.

        '''
        key = (reponame, sha1, filename)
        if key in self._resolved_morphologies:
            return self._resolved_morphologies[key]

        loader = morphlib.morphloader.MorphologyLoader()
        if self.lrc.has_repo(reponame):
            self.status(msg="Looking for %(reponame)s:%(filename)s in local "
                            "repo cache",
                        reponame=reponame, filename=filename, chatty=True)
            try:
                repo = self.lrc.get_repo(reponame)
                text = repo.read_file(filename, sha1)
                morph = loader.load_from_string(text)
            except IOError:
                morph = None
        elif self.rrc is not None:
            self.status(msg="Looking for %(reponame)s %(sha1)s %(filename)s"
                        " in the remote git cache.",
                        reponame=reponame, sha1=sha1, filename=filename,
                        chatty=True)
            try:
                text = self.rrc.cat_file(reponame, sha1, filename)
                morph = loader.load_from_string(text)
            except morphlib.remoterepocache.CatFileError:
                morph = None
        else:
            # We assume that _resolve_ref() must have already been called and
            # so the repo in question would have been made available already
            # if it had been possible.
            raise NotcachedError(reponame)

        if morph is None:
            return None
        else:
            loader.validate(morph)
            loader.set_commands(morph)
            loader.set_defaults(morph)
            self._resolved_morphologies[key] = morph
            return morph

    def _detect_build_system(self, reponame, sha1, expected_filename):
        '''Attempt to detect buildsystem of the given commit.

        Returns None if no known build system was be detected.

        '''
        self.status(msg="File %s doesn't exist: attempting to infer "
                        "chunk morph from repo's build system" %
                    expected_filename, chatty=True)

        if self.lrc.has_repo(reponame):
            repo = self.lrc.get_repo(reponame)
            file_list = repo.list_files(ref=sha1, recurse=False)
        elif self.rrc is not None:
            file_list = self.rrc.ls_tree(reponame, sha1)
        else:
            # We assume that _resolve_ref() must have already been called and
            # so the repo in question would have been made available already
            # if it had been possible.
            raise NotcachedError(reponame)

        # FIXME: needs to be a name
        buildsystem = morphlib.buildsystem.detect_build_system(file_list)

        if buildsystem is None:
            # It might surprise you to discover that if we can't autodetect a
            # build system, we raise MorphologyNotFoundError. Users are
            # required to provide a morphology for any chunk where Morph can't
            # infer the build instructions automatically, so this is the right
            # error.
            raise MorphologyNotFoundError(expected_filename)

        return buildsystem.name

    def _create_morphology_for_build_system(self, buildsystem_name,
                                            morph_name):
        bs = morphlib.buildsystem.lookup_build_system(buildsystem_name)
        loader = morphlib.morphloader.MorphologyLoader()
        morph = bs.get_morphology(morph_name)
        loader.validate(morph)
        loader.set_commands(morph)
        loader.set_defaults(morph)
        return morph

    def _process_definitions_with_children(self, system_filenames,
                                           definitions_repo,
                                           definitions_ref,
                                           definitions_absref,
                                           definitions_tree,
                                           visit):
        definitions_queue = collections.deque(system_filenames)
        chunk_in_definitions_repo_queue = set()
        chunk_in_source_repo_queue = set()

        while definitions_queue:
            filename = definitions_queue.popleft()

            morphology = self._get_morphology(
                definitions_repo, definitions_absref, filename)

            if morphology is None:
                raise MorphologyNotFoundError(filename)

            visit(definitions_repo, definitions_ref, filename,
                  definitions_absref, definitions_tree, morphology)

            if morphology['kind'] == 'cluster':
                raise cliapp.AppException(
                    "Cannot build a morphology of type 'cluster'.")
            elif morphology['kind'] == 'system':
                definitions_queue.extend(
                    morphlib.util.sanitise_morphology_path(s['morph'])
                    for s in morphology['strata'])
            elif morphology['kind'] == 'stratum':
                if morphology['build-depends']:
                    definitions_queue.extend(
                        morphlib.util.sanitise_morphology_path(s['morph'])
                        for s in morphology['build-depends'])
                for c in morphology['chunks']:
                    if 'morph' not in c:
                        path = morphlib.util.sanitise_morphology_path(
                            c.get('morph', c['name']))
                        chunk_in_source_repo_queue.add(
                            (c['repo'], c['ref'], path))
                        continue
                    chunk_in_definitions_repo_queue.add(
                        (c['repo'], c['ref'], c['morph']))

        return chunk_in_definitions_repo_queue, chunk_in_source_repo_queue

    def process_chunk(self, definition_repo, definition_ref, chunk_repo,
                      chunk_ref, filename, visit):
        # In the SourceResolver object, info on this chunk is keyed by the
        # repo & ref of the morphology (which is usually
        # baserock:baserock/definitions, but may be upstream:whatever if it
        # still has a chunk morph in its chunk repo). In the SourcePool object
        # the sources are keyed by repo & ref of the source itself. Sorry! :(
        key = (definition_repo, definition_ref, filename)
        morph_name = os.path.splitext(os.path.basename(filename))[0]

        morphology = None
        buildsystem = None

        if key in self._resolved_buildsystems:
            buildsystem = self._resolved_buildsystems[key]

        if buildsystem is None:
            # The morphologies aren't locally cached, so a morphology
            # for a chunk kept in the chunk repo will be read every time.
            # So, always keep your chunk morphs in your definitions repo,
            # not in the chunk repo!
            morphology = self._get_morphology(*key)

        if morphology is None:
            if buildsystem is None:
                buildsystem = self._detect_build_system(*key)
            if buildsystem is None:
                raise MorphologyNotFoundError(filename)
            else:
                morphology = self._create_morphology_for_build_system(
                    buildsystem, morph_name)
                self._resolved_morphologies[key] = morphology

        absref, tree = self._resolve_ref(chunk_repo, chunk_ref)
        visit(chunk_repo, chunk_ref, filename, absref, tree, morphology)

    def traverse_morphs(self, definitions_repo, definitions_ref,
                        system_filenames,
                        visit=lambda rn, rf, fn, arf, m: None,
                        definitions_original_ref=None):
        self._resolved_trees = self.tree_cache_manager.load_cache()

        # Resolve the (repo, ref) pair for the definitions repo, cache result.
        definitions_absref, definitions_tree = self._resolve_ref(
            definitions_repo, definitions_ref)

        if definitions_original_ref:
            definitions_ref = definitions_original_ref

        try:
            # First, process the system and its stratum morphologies. These
            # will all live in the same Git repository, and will point to
            # various chunk morphologies.
            chunk_in_definitions_repo_queue, chunk_in_source_repo_queue = \
                self._process_definitions_with_children(
                    system_filenames, definitions_repo, definitions_ref,
                    definitions_absref, definitions_tree, visit)

            # Now process all the chunks involved in the build. First those
            # with morphologies in definitions.git, and then (for compatibility
            # reasons only) those with the morphology in the chunk's source
            # repository.
            for repo, ref, filename in chunk_in_definitions_repo_queue:
                self.process_chunk(definitions_repo, definitions_ref, repo,
                                   ref, filename, visit)

            for repo, ref, filename in chunk_in_source_repo_queue:
                self.process_chunk(repo, ref, repo, ref, filename, visit)
        finally:
            self.tree_cache_manager.save_cache(self._resolved_trees)


def create_source_pool(lrc, rrc, repo, ref, filename, cachedir,
                       original_ref=None, update_repos=True,
                       status_cb=None):
    '''Find all the sources involved in building a given system.

    Given a system morphology, this function will traverse the tree of stratum
    and chunk morphologies that the system points to and create appropriate
    Source objects. These are added to a new SourcePool object, which is
    returned.

    Note that Git submodules are not considered 'sources' in the current
    implementation, and so they must be handled separately.

    The 'lrc' and 'rrc' parameters specify the local and remote Git repository
    caches used for resolving the sources.

    '''
    pool = morphlib.sourcepool.SourcePool()

    def add_to_pool(reponame, ref, filename, absref, tree, morphology):
        sources = morphlib.source.make_sources(reponame, ref,
                                               filename, absref,
                                               tree, morphology)
        for source in sources:
            pool.add(source)

    tree_cache_size = 10000
    tree_cache_manager = PickleCacheManager(
        os.path.join(cachedir, 'trees.cache.pickle'), tree_cache_size)

    resolver = SourceResolver(lrc, rrc, tree_cache_manager, update_repos,
                              status_cb)
    resolver.traverse_morphs(repo, ref, [filename],
                             visit=add_to_pool,
                             definitions_original_ref=original_ref)
    return pool
