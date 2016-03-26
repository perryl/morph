# Copyright (C) 2014-2016  Codethink Limited
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
import contextlib
import cPickle
import logging
import os
import pylru
import warnings

import cliapp

import morphlib
from morphlib.util import sanitise_morphology_path


tree_cache_size = 10000
tree_cache_filename = 'trees.cache.pickle'


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

    @contextlib.contextmanager
    def open(self):
        cache = self.load_cache()
        try:
            yield cache
        except BaseException as e:
            raise
        else:
            self.save_cache(cache)


class SourceResolverError(cliapp.AppException):
    pass


class MorphologyNotFoundError(SourceResolverError):
    def __init__(self, filename):
        SourceResolverError.__init__(
            self, "Couldn't find morphology: %s" % filename)


class MorphologyReferenceNotFoundError(SourceResolverError):
    def __init__(self, filename, reference_file):
        SourceResolverError.__init__(self,
                                     "Couldn't find morphology: %s "
                                     "referenced in %s"
                                     % (filename, reference_file))


class MorphologyNameError(SourceResolverError):
    def __init__(self, name_in_morphology, name, filename):
        SourceResolverError.__init__(self,
                                     "Name '%s' doesn't match '%s' in "
                                     "morphology: %s"
                                     % (name_in_morphology, name, filename))


# Callers may want to give the user a special error message if we hit an
# InvalidRefError in the definitions.git repo. Currently a separate exception
# type seems the easiest way to do that, but adding enough detail to the
# gitdir.InvalidRefError class may make this class redundant in future.
class InvalidDefinitionsRefError(SourceResolverError):
    def __init__(self, repo_url, ref):
        self.repo_url = repo_url
        self.ref = ref
        super(InvalidDefinitionsRefError, self).__init__(
            "Ref %s was not found in repo %s." % (ref, repo_url))


class SourceResolver(object):
    '''Provides a way of resolving the set of sources for a given system.

    There are three levels of caching involved in resolving the sources to
    build.

    The canonical repo for each source is specified in the build-command
    (for strata and systems) or in the stratum morphology (for chunks). It will
    be either a normal URL, or a keyed URL using a repo-alias like
    'baserock:baserock/definitions'.

    Each commit used in a build is resolved to a tree SHA1, which means that
    merge commits and changes to commit messages don't affect the cache
    identity of a chunk. This does mean we need to query every repo in the
    build graph, though.

    All requests for information on a repo use the 'repocache' module. This
    maintains a local copy of all the Git repos we need to work with. A repo
    cache can also use a remote 'morph-cache-server' instance, if available,
    to query certain information about a repo without cloning it locally.
    Using this we can resolve commits to trees without having to clone every
    repo locally, which is a huge performance improvement in some cases.

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

    def __init__(self, repo_cache, tree_cache_manager, status_cb=None):
        self.repo_cache = repo_cache
        self.tree_cache_manager = tree_cache_manager

        self.update = repo_cache.update_gits
        self.status = status_cb

    def _resolve_ref(self, resolved_trees, reponame, ref):
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating or cloning
        the repository into the local repo cache.

        '''

        # The Baserock reference definitions use absolute refs so, and, if the
        # absref is cached, we can short-circuit all this code.
        if (reponame, ref) in resolved_trees:
            logging.debug('Returning tree (%s, %s) from tree cache',
                          reponame, ref)
            return ref, resolved_trees[(reponame, ref)]

        logging.debug('tree (%s, %s) not in cache', reponame, ref)

        absref, tree = self.repo_cache.resolve_ref_to_commit_and_tree(reponame,
                                                                      ref)

        logging.debug('Writing tree to cache with ref (%s, %s)',
                      reponame, absref)
        resolved_trees[(reponame, absref)] = tree

        return absref, tree

    def _get_file_contents_from_definitions(self, definitions_checkout_dir,
                                            filename):
        fp = os.path.join(definitions_checkout_dir, filename)
        if os.path.exists(fp):
            with open(fp) as f:
                return f.read()
        else:
            logging.debug("Didn't find %s in definitions", filename)
            return None

    def _check_version_file(self, definitions_checkout_dir):
        version_text = self._get_file_contents_from_definitions(
                definitions_checkout_dir, 'VERSION')

        return morphlib.definitions_version.check_version_file(version_text)

    def _get_defaults(self, definitions_checkout_dir,
                      definitions_version=7):  # pragma: no cover
        '''Return the default build system commands, and default split rules.

        This function returns a tuple with two dicts.

        The defaults are read from a file named DEFAULTS in the definitions
        directory, if the definitions follow format version 7 or later. If the
        definitions follow version 6 or earlier, hardcoded defaults are used.

        '''
        # Read default build systems and split rules from DEFAULTS file.
        defaults_text = self._get_file_contents_from_definitions(
            definitions_checkout_dir, 'DEFAULTS')

        if defaults_text is None:
            warnings.warn("No DEFAULTS file found.")

        defaults = morphlib.defaults.Defaults(definitions_version,
                                              text=defaults_text)

        return defaults.build_systems(), defaults.split_rules()

    def _get_morphology(self, resolved_morphologies, definitions_checkout_dir,
                        morph_loader, filename):
        '''Read the morphology at the specified location.

        Returns None if the file does not exist in the specified commit.

        '''
        if filename in resolved_morphologies:
            return resolved_morphologies[filename]

        text = self._get_file_contents_from_definitions(
            definitions_checkout_dir, filename)
        morph = morph_loader.load_from_string(text, filename)

        if morph is not None:
            resolved_morphologies[filename] = morph

        return morph

    def _process_definitions_with_children(self,
                                           resolved_morphologies,
                                           definitions_checkout_dir,
                                           definitions_repo,
                                           definitions_ref,
                                           definitions_absref,
                                           definitions_tree,
                                           morph_loader,
                                           system_filenames,
                                           visit,
                                           predefined_split_rules):
        # Initialise definitions_queue with tuples (name, filename).
        # We don't need system's filename, so use 'None'
        definitions_queue = collections.deque((None, f)
                                               for f in system_filenames)
        chunk_queue = set()

        def get_morphology(filename):
            return self._get_morphology(resolved_morphologies,
                                        definitions_checkout_dir, morph_loader,
                                        filename)

        while definitions_queue:
            name, filename = definitions_queue.popleft()

            morphology = get_morphology(filename)

            if morphology is None:
                raise MorphologyNotFoundError(filename)

            visit(definitions_repo, definitions_ref, filename,
                  definitions_absref, definitions_tree, morphology,
                  predefined_split_rules)

            if morphology['kind'] == 'cluster':
                raise cliapp.AppException(
                    "Cannot build a morphology of type 'cluster'.")
            elif morphology['kind'] == 'system':
                # name is not mandatory, use 'None' if not definied.
                definitions_queue.extend((s.get('name'),
                    sanitise_morphology_path(s['morph']))
                    for s in morphology['strata'])
            elif morphology['kind'] == 'stratum':
                # If we have the name of the stratum, fail if it doesn't
                # match with the one set in the stratum file.
                if name and name != morphology.get('name'):
                    raise MorphologyNameError(morphology['name'], name,
                                              filename)
                if morphology['build-depends']:
                    # build-depends don't have names. Use 'None' as name.
                    definitions_queue.extend((None,
                        sanitise_morphology_path(s['morph']))
                        for s in morphology['build-depends'])
                for c in morphology['chunks']:
                    if 'morph' in c:
                        # Now, does this path actually exist?
                        path = c['morph']

                        morphology = get_morphology(path)
                        if morphology is None:
                            raise MorphologyReferenceNotFoundError(
                                path, filename)

                        chunk_queue.add((c['name'], c['repo'], c['ref'],
                                         path, None))
                    else:
                        # We invent a filename here, so that the rest of the
                        # Morph code doesn't need to know about the predefined
                        # build instructions.
                        chunk_filename = c['name'] + '.morph'
                        chunk_queue.add((c['name'], c['repo'], c['ref'],
                                         chunk_filename, c['build-system']))

        return chunk_queue

    def _create_morphology_for_build_system(self, morph_loader, buildsystem,
                                            morph_name):
        morph = buildsystem.get_morphology(morph_name)
        morph_loader.validate(morph)
        morph_loader.set_commands(morph)
        morph_loader.set_defaults(morph)
        return morph

    def process_chunk(self, resolved_morphologies, resolved_trees,
                      definitions_checkout_dir, morph_loader, chunk_name,
                      chunk_repo, chunk_ref, filename, chunk_buildsystem,
                      visit, predefined_build_systems, predefined_split_rules):
        absref, tree = self._resolve_ref(resolved_trees, chunk_repo, chunk_ref)

        if chunk_buildsystem is None:
            # Build instructions defined in a chunk .morph file. An error is
            # already raised in _process_definitions_with_children() if the
            # 'morph' field points to a file that doesn't exist.
            morphology = self._get_morphology(resolved_morphologies,
                                              definitions_checkout_dir,
                                              morph_loader, filename)

            if morphology['name'] != chunk_name:
                warnings.warn("Name '%s' doesn't match '%s in morpholgy: %s"
                              % (morphology['name'], chunk_name, filename))
        else:
            # Chunk uses one of the predefined build systems. In this case
            # 'filename' will be faked (name of chunk + '.morph').

            try:
                buildsystem = predefined_build_systems[chunk_buildsystem]
            except KeyError:
                raise SourceResolverError("Unknown build system for %s: %s" %
                        (filename, chunk_buildsystem))

            morphology = self._create_morphology_for_build_system(
                morph_loader, buildsystem, chunk_name)

        visit(chunk_repo, chunk_ref, filename, absref, tree, morphology,
              predefined_split_rules)

    def add_morphs_to_source_pool(self, definitions_repo, definitions_ref,
                                  system_filenames, pool,
                                  definitions_original_ref=None):

        def add_to_pool(reponame, ref, filename, absref, tree, morphology,
                        predefined_split_rules):
            # If there are duplicate chunks which have the same 'name' and the
            # same build instructions, we might cause a stack overflow in
            # cachekeycomputer.py when trying to hash the build graph. The
            # _find_duplicate_chunks() function doesn't handle this case, it
            # is checking for duplicates with the same name but different build
            # instructions.
            if morphology['kind'] != 'stratum':
                if pool.lookup(reponame, ref, filename):
                    raise morphlib.Error(
                        "There are multiple versions of component '%s'" %
                        morphology['name'])

            sources = morphlib.source.make_sources(
                reponame, ref, filename, absref, tree, morphology,
                predefined_split_rules)
            for source in sources:
                pool.add(source)

        resolved_morphologies = {}

        with morphlib.util.temp_dir() as definitions_checkout_dir, \
            self.tree_cache_manager.open() as resolved_trees:

            # Resolve the repo, ref pair for definitions repo, cache result
            try:
                definitions_absref, definitions_tree = self._resolve_ref(
                    resolved_trees, definitions_repo, definitions_ref)
            except morphlib.gitdir.InvalidRefError as e:
                raise InvalidDefinitionsRefError(
                    definitions_repo, definitions_ref)

            if definitions_original_ref:
                definitions_ref = definitions_original_ref

            definitions_cached_repo = self.repo_cache.get_updated_repo(
                    repo_name=definitions_repo, ref=definitions_absref)
            definitions_cached_repo.extract_commit(
                definitions_absref, definitions_checkout_dir)

            pool.definitions_version = self._check_version_file(
                definitions_checkout_dir)

            predefined_build_systems, predefined_split_rules = \
                self._get_defaults(
                    definitions_checkout_dir, pool.definitions_version)

            morph_loader = morphlib.morphloader.MorphologyLoader(
                predefined_build_systems=predefined_build_systems)

            # First, process the system and its stratum morphologies. These
            # will all live in the same Git repository, and will point to
            # various chunk morphologies.
            chunk_queue = self._process_definitions_with_children(
                    resolved_morphologies, definitions_checkout_dir,
                    definitions_repo, definitions_ref, definitions_absref,
                    definitions_tree, morph_loader, system_filenames,
                    add_to_pool, predefined_split_rules)

            # Now process all the chunks involved in the build.
            for name, repo, ref, filename, buildsystem in chunk_queue:
                self.process_chunk(resolved_morphologies, resolved_trees,
                                   definitions_checkout_dir, morph_loader,
                                   name, repo, ref, filename, buildsystem,
                                   add_to_pool, predefined_build_systems,
                                   predefined_split_rules)


class DuplicateChunkError(morphlib.Error):

    def _make_msg(self, (name, sources)): # pragma: no cover
        return ("Multiple `%s' chunks detected:\n\t%s"
                % (name, '\n\t'.join((str(s) for s in sources))))

    def __init__(self, duplicate_chunks): # pragma: no cover
        msgs = (self._make_msg(dup) for dup in duplicate_chunks.iteritems())
        msg = '\n'.join(msgs)

        super(DuplicateChunkError, self).__init__(msg)

def _find_duplicate_chunks(sourcepool): #pragma: no cover
    ''' Searches the sourcepool for duplicate chunks
        returns a dictionary of any duplicates keyed on chunk source name,
        the value of each item is a list of duplicate chunk sources
    '''

    chunk_sources = ((s.name, s) for s in sourcepool
                        if s.morphology['kind'] == 'chunk')

    chunk_sources_by_name = collections.defaultdict(list)
    for (name, source) in chunk_sources:
        chunk_sources_by_name[name].append(source)

    return {k: v for (k, v) in chunk_sources_by_name.iteritems() if len(v) > 1}

def create_source_pool(repo_cache, repo, ref, filenames,
                       original_ref=None, status_cb=None):
    '''Find all the sources involved in building a given system.

    Given a system morphology, this function will traverse the tree of stratum
    and chunk morphologies that the system points to and create appropriate
    Source objects. These are added to a new SourcePool object, which is
    returned.

    Note that Git submodules are not considered 'sources' in the current
    implementation, and so they must be handled separately.

    The 'repo_cache' parameter specifies a repo cache which is used when
    accessing the source repos. If a git_resolve_cache_server is set for this
    repo cache, and all repos in the build are known to it, then this function
    will only need the definitions.git repo available locally. If not, then all
    repos must be cloned in order to resolve the refs to tree SHA1s, which is
    a slow process!

    '''
    pool = morphlib.sourcepool.SourcePool()

    tree_cache_manager = PickleCacheManager(
        os.path.join(repo_cache.cachedir, tree_cache_filename),
        tree_cache_size)

    resolver = SourceResolver(repo_cache, tree_cache_manager, status_cb)
    resolver.add_morphs_to_source_pool(repo, ref, filenames, pool,
                                       definitions_original_ref=original_ref)

    # No two chunks may have the same name
    duplicate_chunks = _find_duplicate_chunks(pool)
    if duplicate_chunks:
        raise DuplicateChunkError(duplicate_chunks)

    return pool
