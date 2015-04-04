# Copyright (C) 2014-2015  Codethink Limited
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


import collections
import cPickle
import logging
import os
import pylru
import shutil
import tempfile
import yaml

import cliapp

import morphlib

tree_cache_size = 10000
tree_cache_filename = 'trees.cache.pickle'
buildsystem_cache_size = 10000
buildsystem_cache_filename = 'detected-chunk-buildsystems.cache.pickle'

supported_versions = [0, 1]

class PickleCacheManager(object): # pragma: no cover
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
                cache[key] = value
        except (EOFError, IOError, cPickle.PickleError) as e:
            logging.warning('Failed to load cache %s: %s', self.filename, e)

    def load_cache(self):
        '''Create a pylru.lrucache object prepopulated with saved data.'''
        cache = pylru.lrucache(self.size)
        # There should be a more efficient way to do this, by hooking into
        # the json module directly.
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
            with morphlib.savefile.SaveFile(self.filename, 'w') as f:
                cPickle.dump(data, f)
        except (IOError, cPickle.PickleError) as e:
            logging.warning('Failed to save cache to %s: %s', self.filename, e)


class SourceResolverError(cliapp.AppException):
    pass


class MorphologyNotFoundError(SourceResolverError): # pragma: no cover
    def __init__(self, filename):
        SourceResolverError.__init__(
            self, "Couldn't find morphology: %s" % filename)

class UnknownVersionError(SourceResolverError): # pragma: no cover
    def __init__(self, version):
        SourceResolverError.__init__(
            self, "Definitions format version %s is not supported" % version)


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
                 tree_cache_manager, buildsystem_cache_manager, update_repos,
                 status_cb=None):
        self.lrc = local_repo_cache
        self.rrc = remote_repo_cache
        self.tree_cache_manager = tree_cache_manager
        self.buildsystem_cache_manager = buildsystem_cache_manager

        self.update = update_repos
        self.status = status_cb

        self._resolved_trees = {}
        self._resolved_morphologies = {}
        self._resolved_buildsystems = {}

        self._definitions_checkout_dir = None

    def cache_repo_locally(self, reponame):
        if self.update:
            self.status(msg='Caching git repository %(reponame)s',
                        reponame=reponame)
            repo = self.lrc.cache_repo(reponame)
        else:  # pragma: no cover
            # This is likely to raise a morphlib.localrepocache.NotCached
            # exception, because the caller should have checked if the
            # localrepocache already had the repo. But we may as well try.
            repo = self.lrc.get_repo(reponame)
        return repo

    def _resolve_ref(self, reponame, ref): # pragma: no cover
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating or cloning
        the repository into the local repo cache.

        This function is complex due to the 3 layers of caching described in
        the SourceResolver docstring.

        '''

        # The Baserock reference definitions use absolute refs so, and, if the
        # absref is cached, we can short-circuit all this code.
        if (reponame, ref) in self._resolved_trees:
            logging.debug('Returning tree (%s, %s) from tree cache',
                          reponame, ref)
            return ref, self._resolved_trees[(reponame, ref)]

        logging.debug('tree (%s, %s) not in cache', reponame, ref)

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
            except BaseException as e:
                logging.warning('Caught (and ignored) exception: %s' % str(e))

        if absref is None:
            repo = self.cache_repo_locally(reponame)
            absref = repo.resolve_ref_to_commit(ref)
            tree = repo.resolve_ref_to_tree(absref)

        logging.debug('Writing tree to cache with ref (%s, %s)',
                      reponame, absref)
        self._resolved_trees[(reponame, absref)] = tree

        return absref, tree

    def _get_file_contents_from_definitions(self,
                                            filename):  # pragma: no cover
        if os.path.exists(filename):
            with open(filename) as f:
                return f.read()
        else:
            return None

    def _get_file_contents_from_repo(self, reponame,
                                     sha1, filename):  # pragma: no cover
        if self.lrc.has_repo(reponame):
            self.status(msg="Looking for %(reponame)s:%(filename)s in the "
                            "local repo cache.",
                        reponame=reponame, filename=filename, chatty=True)
            try:
                repo = self.lrc.get_repo(reponame)
                text = repo.read_file(filename, sha1)
            except IOError:
                text = None
        elif self.rrc is not None:
            self.status(msg="Looking for %(reponame)s:%(filename)s in the "
                            "remote repo cache.",
                        reponame=reponame, filename=filename, chatty=True)
            try:
                text = self.rrc.cat_file(reponame, sha1, filename)
            except morphlib.remoterepocache.CatFileError:
                text = None
        else:  # pragma: no cover
            repo = self.cache_repo_locally(reponame)
            text = repo.read_file(filename, sha1)

        return text

    def _get_file_contents(self, reponame, sha1, filename):  # pragma: no cover
        '''Read the file at the specified location.

        Returns None if the file does not exist in the specified commit.

        '''
        text = None

        if reponame == self._definitions_repo and \
                sha1 == self._definitions_absref: # pragma: no cover
            # There is a temporary local checkout of the definitions repo which
            # we can quickly read definitions files from.
            defs_filename = os.path.join(self._definitions_checkout_dir,
                                         filename)
            text = self._get_file_contents_from_definitions(defs_filename)
        else:
            text = self._get_file_contents_from_repo(reponame, sha1, filename)

        return text

    def _get_morphology(self, reponame, sha1, filename):  # pragma: no cover
        '''Read the morphology at the specified location.

        Returns None if the file does not exist in the specified commit.

        '''
        key = (reponame, sha1, filename)
        if key in self._resolved_morphologies:
            return self._resolved_morphologies[key]

        loader = morphlib.morphloader.MorphologyLoader()

        text = self._get_file_contents(reponame, sha1, filename)
        morph = loader.load_from_string(text, filename)

        if morph is not None:
            self._resolved_morphologies[key] = morph

        return morph

    def _detect_build_system(self, reponame, sha1, expected_filename):
        '''Attempt to detect buildsystem of the given commit.

        Returns None if no known build system was detected.

        '''
        self.status(msg="File %s doesn't exist: attempting to infer "
                        "chunk morph from repo's build system" %
                    expected_filename, chatty=True)

        file_list = None

        if self.lrc.has_repo(reponame):
            repo = self.lrc.get_repo(reponame)
            try:
                file_list = repo.list_files(ref=sha1, recurse=False)
            except morphlib.gitdir.InvalidRefError:  # pragma: no cover
                pass
        elif self.rrc is not None:
            try:
                # This may or may not succeed; if the is repo not
                # hosted on the same Git server as the cache server then
                # it'll definitely fail.
                file_list = self.rrc.ls_tree(reponame, sha1)
            except morphlib.remoterepocache.LsTreeError:
                pass

        if not file_list:
            repo = self.cache_repo_locally(reponame)
            file_list = repo.list_files(ref=sha1, recurse=False)

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
                                            morph_name): # pragma: no cover
        bs = morphlib.buildsystem.lookup_build_system(buildsystem_name)
        loader = morphlib.morphloader.MorphologyLoader()
        morph = bs.get_morphology(morph_name)
        loader.validate(morph)
        loader.set_commands(morph)
        loader.set_defaults(morph)
        return morph

    def _parse_version_file(self, version_file): # pragma : no cover
        '''Parse VERSION file and return the version of the format if:

        VERSION is a YAML file
        and it's a dict
        and has the key 'version'
        and the type stored in the 'version' key is an int
        and that int is not in the supported format

        otherwise returns None

        '''
        version = None

        yaml_obj = yaml.safe_load(version_file)
        if yaml_obj is not None:
            if type(yaml_obj) is dict:
                if 'version' in yaml_obj.keys():
                    if type(yaml_obj['version']) is int:
                        version = yaml_obj['version']

        return version

    def _check_version_file(self,definitions_repo,
                            definitions_absref): # pragma: no cover
        version_file = self._get_file_contents(
            definitions_repo, definitions_absref, 'VERSION')

        if version_file is None:
            return

        version = self._parse_version_file(version_file)
        if version is not None:
            if version not in supported_versions:
                raise UnknownVersionError(version)

    def _process_definitions_with_children(self, system_filenames,
                                           definitions_repo,
                                           definitions_ref,
                                           definitions_absref,
                                           definitions_tree,
                                           visit): # pragma: no cover
        definitions_queue = collections.deque(system_filenames)
        chunk_queue = set()

        self._check_version_file(definitions_repo, definitions_absref)

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
                        # Autodetect a path if one is not given. This is to
                        # support the deprecated approach of putting the chunk
                        # .morph file in the toplevel directory of the chunk
                        # repo, instead of putting it in the definitions.git
                        # repo.
                        #
                        # All users should be specifying a full path to the
                        # chunk morph file, using the 'morph' field, and this
                        # code path should be removed.
                        path = morphlib.util.sanitise_morphology_path(
                            c.get('morph', c['name']))
                        chunk_queue.add((c['repo'], c['ref'], path))
                    else:
                        chunk_queue.add((c['repo'], c['ref'], c['morph']))

        return chunk_queue

    def _generate_morph_and_cache_buildsystem(self,
                                              definition_key, chunk_key,
                                              buildsystem,
                                              morph_name): # pragma: no cover
        logging.debug('Caching build system for chunk with key %s', chunk_key)

        self._resolved_buildsystems[chunk_key] = buildsystem

        morphology = self._create_morphology_for_build_system(buildsystem,
                                                              morph_name)
        self._resolved_morphologies[definition_key] = morphology
        return morphology

    def process_chunk(self, definition_repo, definition_ref, chunk_repo,
                      chunk_ref, filename, visit): # pragma: no cover
        absref = None
        tree = None
        chunk_key = None
        buildsystem = None

        morph_name = os.path.splitext(os.path.basename(filename))[0]

        # Get morphology from definitions repo
        definition_key = (definition_repo, definition_ref, filename)
        morphology = self._get_morphology(*definition_key)

        if morphology:
            absref, tree = self._resolve_ref(chunk_repo, chunk_ref)
            visit(chunk_repo, chunk_ref, filename, absref, tree, morphology)
            return

        absref, tree = self._resolve_ref(chunk_repo, chunk_ref)
        chunk_key = (chunk_repo, absref, filename)

        if chunk_key in self._resolved_buildsystems:
            logging.debug('Build system for %s is cached', str(chunk_key))
            self.status(msg='Build system for %(chunk)s is cached',
                        chunk=str(chunk_key),
                        chatty=True)
            buildsystem = self._resolved_buildsystems[chunk_key]

            # If the build system for this chunk is cached then:
            #   * the chunk does not have a chunk morph
            #     (so we don't need to look for one)
            #
            #   * a suitable (generated) morphology may already be cached.
            #
            # If the morphology is not already cached we can generate it
            # from the build-system and cache it.
            if definition_key in self._resolved_morphologies:
                morphology = self._resolved_morphologies[definition_key]
            else:
                morphology = self._generate_morph_and_cache_buildsystem(
                    definition_key, chunk_key, buildsystem, morph_name)
        else:
            logging.debug('Build system for %s is NOT cached', str(chunk_key))
            # build-system not cached, look for morphology in chunk repo
            # this can be slow (we may need to clone the repo from a remote)
            morphology = self._get_morphology(*chunk_key)

            if morphology != None:
                self._resolved_morphologies[definition_key] = morphology
            else:
                # This chunk doesn't have a chunk morph
                buildsystem = self._detect_build_system(*chunk_key)

                if buildsystem is None:
                    raise MorphologyNotFoundError(filename)
                else:
                    morphology = self._generate_morph_and_cache_buildsystem(
                        definition_key, chunk_key, buildsystem, morph_name)

        visit(chunk_repo, chunk_ref, filename, absref, tree, morphology)

    def traverse_morphs(self, definitions_repo, definitions_ref,
                        system_filenames,
                        visit=lambda rn, rf, fn, arf, m: None,
                        definitions_original_ref=None): # pragma: no cover
        self._resolved_trees = self.tree_cache_manager.load_cache()
        self._resolved_buildsystems = \
            self.buildsystem_cache_manager.load_cache()

        # Resolve the (repo, ref) pair for the definitions repo, cache result.
        definitions_absref, definitions_tree = self._resolve_ref(
            definitions_repo, definitions_ref)

        if definitions_original_ref:
            definitions_ref = definitions_original_ref

        self._definitions_checkout_dir = tempfile.mkdtemp()

        try:
            # FIXME: not an ideal way of passing this info across
            self._definitions_repo = definitions_repo
            self._definitions_absref = definitions_absref
            try:
                definitions_cached_repo = self.lrc.get_repo(definitions_repo)
            except morphlib.localrepocache.NotCached:
                definitions_cached_repo = self.cache_repo_locally(
                    definitions_repo)
            definitions_cached_repo.extract_commit(
                definitions_absref, self._definitions_checkout_dir)

            # First, process the system and its stratum morphologies. These
            # will all live in the same Git repository, and will point to
            # various chunk morphologies.
            chunk_queue = self._process_definitions_with_children(
                    system_filenames, definitions_repo, definitions_ref,
                    definitions_absref, definitions_tree, visit)

            # Now process all the chunks involved in the build.
            for repo, ref, filename in chunk_queue:
                self.process_chunk(definitions_repo, definitions_absref, repo,
                                   ref, filename, visit)
        finally:
            shutil.rmtree(self._definitions_checkout_dir)
            self._definitions_checkout_dir = None

            logging.debug('Saving contents of resolved tree cache')
            self.tree_cache_manager.save_cache(self._resolved_trees)

            logging.debug('Saving contents of build systems cache')
            self.buildsystem_cache_manager.save_cache(
                self._resolved_buildsystems)


def create_source_pool(lrc, rrc, repo, ref, filename, cachedir,
                       original_ref=None, update_repos=True,
                       status_cb=None): # pragma: no cover
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

    tree_cache_manager = PickleCacheManager(
        os.path.join(cachedir, tree_cache_filename), tree_cache_size)

    buildsystem_cache_manager = PickleCacheManager(
        os.path.join(cachedir, buildsystem_cache_filename),
        buildsystem_cache_size)

    resolver = SourceResolver(lrc, rrc, tree_cache_manager,
                              buildsystem_cache_manager, update_repos,
                              status_cb)
    resolver.traverse_morphs(repo, ref, [filename],
                             visit=add_to_pool,
                             definitions_original_ref=original_ref)
    return pool
