# Stratum from Ruby Gems, Python edition.

# The Ruby version may not be necessary -- since rubygems.org provides an API,
# we can get platform-neutral data instead of Ruby-specific YAML. The only
# non-trivial thing seems to be comparing versions of Gems, but we could
# perhaps shell out to Ruby to do this anyway.


import requests
import requests_cache
import tarjan.tc
import toposort

import collections
import json
import os
import urlparse
from itertools import chain


# Some random popular Gems
gems = [
    #'capistrano',
    'chef',
    #'gitlab',
    #'heroku',
    #'knife-solo',
    #'ohai',
    #'pry',
    #'puppet',
    #'rails',
    #'sass',
    #'travis',
    #'vagrant',
]

# Shorter!
#gems = ['thor']

# Ruby bundles some Gems! This list was generated with 'gem list' after a Ruby
# 2.0.0p477 install.
built_in_gems = {
    'bigdecimal': '1.2.0',
    'io-console': '0.4.2',
    'json': '1.7.7',
    'minitest': '4.3.2',
    'psych': '2.0.0',
    'rake': '0.9.6',
    'rdoc': '4.0.0',
    'test-unit': '2.0.0.0',
}

# Gems that can't be built from source due to circular dependencies. The set
# of runtime dependencies of these Gems is removed from the stratum.
never_build_these_gems = {
    # Dep loop 1
    'hoe-highline': '0',
    'hoe-mercurial': '0',

    # Dep loop 2 (with utils)
    'gem_hadar': '0',

    # Dep loop 3 (with tst-unit-rr)
    'packnga': 'https://github.com/rails/rails',

    # More things that cause dep loops
    'qed': '0',
    'shoulda': '0',
    'cucumber': '0',
    'rspec': '0',

    'capybara': 'https://github.com/rails/rails',

}

known_source_uris = {
    'actionmailer': 'https://github.com/rails/rails',
    'actionpack': 'https://github.com/rails/rails',
    'actionview': 'https://github.com/rails/rails',
    'activemodel': 'https://github.com/rails/rails',
    'activerecord': 'https://github.com/rails/rails',
    'activesupport': 'https://github.com/rails/rails',
    'rails': 'https://github.com/rails/rails',
}

# Save hammering the rubygems.org API: 'requests' API calls are
# transparently cached in an SQLite database, instead.
requests_cache.install_cache('rubygems_api_cache')


class Chunk(object):
    def __init__(self, name, repo, ref, build_deps=[], runtime_deps=[]):
        self.name = name
        self.repo = repo
        self.ref = ref
        self.build_deps = set(build_deps)
        self.runtime_deps = set(runtime_deps)
        self.artifacts = set()

    def __repr__(self):
        return '<chunk %s>' % self.name

    def __str__(self):
        return self.name

    def add_build_deps(self, dependencies):
        self.build_deps.update(set(dependencies))

    def add_runtime_deps(self, dependencies):
        self.runtime_deps.update(set(dependencies))

    def add_artifact(self, artifact):
        self.artifacts.add(artifact)


class RubyTreasureHunter(object):
    '''Sniff out the upstream source repo for a Ruby Gem.'''

    class Stats(object):
        def __init__(self):
            self.have_source_code_uri = 0
            self.have_homepage_uri = 0
            self.homepage_is_github = 0
            self.no_source_found = 0
            self.hardcoded_uris_used = 0

        def show(self):
            print "Gems with source_code_uri set: ", self.have_source_code_uri
            print "Gems with homepage_uri set: ", self.have_homepage_uri
            print "Gems with homepage_uri pointing to Github: ", \
                self.homepage_is_github
            print "Gems for which we have a hard-coded source URI", \
                self.hardcoded_uris_used
            print "Gems with no source found", self.no_source_found

    def __init__(self):
        self.stats = self.Stats()

    def find_upstream_repo_for_gem(self, gem_info):
        gem_name = gem_info['name']
        source_code_uri = gem_info['source_code_uri']
        if source_code_uri is not None:
            self.stats.have_source_code_uri += 1
            return source_code_uri

        if gem_name in known_source_uris:
            known_uri = known_source_uris[gem_name]
            if source_code_uri is not None and known_uri != source_code_uri:
                raise Exception(
                    '%s: Hardcoded source URI %s doesn\'t match spec URI %s' %
                    (gem_name, known_uri, source_code_uri))
            self.stats.hardcoded_uris_used += 1
            return known_uri

        homepage_uri = gem_info['homepage_uri']
        if homepage_uri is not None:
            self.stats.have_homepage_uri += 1
            netloc = urlparse.urlsplit(homepage_uri)[1]
            if netloc == 'github.com':
                self.stats.homepage_is_github += 1
                return homepage_uri

        # Further possible leads on locating source code.
        # http://ruby-toolbox.com/projects/$gemname -> sometimes contains an
        #   upstream link, even if the gem info does not.
        # https://github.com/search?q=$gemname -> often the first result is
        #   the correct one, but you can never know.

        self.stats.no_source_found += 1
        #print gem_info
        return None


class RubyGemsResolver(object):
    def get_gem_info(self, gem_name):
        r = requests.get('http://rubygems.org/api/v1/gems/%s.json' % gem_name)
        return json.loads(r.text)

    def chunk_name_from_repo(self, repo_url):
        if repo_url.endswith('/tree/master'):
            repo_url = repo_url[:-len('/tree/master')]
        if repo_url.endswith('/'):
            repo_url = repo_url[:-1]
        if repo_url.endswith('.git'):
            repo_url = repo_url[:-len('.git')]
        return os.path.basename(repo_url)

    def resolve_chunks_for_gems(self, gem_list):
        source_hunter = RubyTreasureHunter()

        resolved_chunks = dict()
        resolved_gems = dict()
        to_process = collections.deque(gem_list)
        while len(to_process) > 0:
            gem_name = to_process.pop()

            print "[%i processed, %i to go] Fetching info for %s from " \
                "Rubygems.org" % (len(resolved_chunks), len(to_process),
                                  gem_name)

            gem_info = self.get_gem_info(gem_name)

            repo = source_hunter.find_upstream_repo_for_gem(gem_info)

            # Any number of gems can be produced from one source repository,
            # so the chunk name doesn't correspond to the Gem name.
            chunk_name = self.chunk_name_from_repo(repo) if repo else gem_name
            chunk = resolved_chunks.get(chunk_name, None)

            gem_runtime_deps = gem_info['dependencies']['runtime']
            gem_build_deps = gem_info['dependencies']['development']

            chunk_build_deps = set()
            chunk_runtime_deps = set()
            for dep_info in gem_build_deps + gem_runtime_deps:
                dep_name = dep_info['name']
                ignore = chain(to_process, resolved_gems.iterkeys(),
                               built_in_gems)
                if dep_name not in ignore:
                    to_process.append(dep_name)

            # There are version constraints specified here that we
            # currently ignore. Furthermore, the Gemfile.lock (Bundler)
            # file may have an even more specific constraint! I think
            # ideally we want to run 'master' of everything, or at least
            # the last tagged commit of everything, so let's ignore this
            # info for now and start some builds!

            for dep_info in gem_build_deps:
                dep_name = dep_info['name']
                if dep_name not in built_in_gems:
                    chunk_build_deps.add(dep_name)

            for dep_info in gem_runtime_deps:
                dep_name = dep_info['name']
                if dep_name not in built_in_gems:
                    chunk_runtime_deps.add(dep_name)

            if chunk is None:
                ref = 'master'
                chunk = Chunk(chunk_name, repo, ref, chunk_build_deps,
                              chunk_runtime_deps)
                resolved_chunks[chunk_name] = chunk
            else:
                chunk.add_build_deps(chunk_build_deps)
                chunk.add_runtime_deps(chunk_runtime_deps)

            resolved_gems[gem_name] = chunk
            chunk.add_artifact(gem_name)

        # Remove the never_build_these_gems from the graph, and any runtime
        # Gem dependencies they have. We'll install these from Gem files, to
        # avoid cycling dependency issues that they might cause, and all of
        # their runtime dependencies will be installed along with them.
        def remove_chunk_and_its_runtime_deps_from_graph(chunk):
            for dep in chunk.runtime_deps:
                remove_chunk_and_its_runtime_deps_from_graph(dep)
            if chunk_name in resolved_chunks:
                del resolved_chunks[chunk_name]
            for artifact in chunk.artifacts:
                if artifact in resolved_gems:
                    del resolved_gems[artifact]

        gems_to_remove = set()
        def remove_recursive(gem_name):
            if gem_name in gems_to_remove:
                return
            gems_to_remove.add(gem_name)
            chunk = resolved_gems[gem_name]
            for dep in chunk.runtime_deps:
                remove_recursive(dep)

        for gem_name in never_build_these_gems:
            remove_recursive(gem_name)

        core_chunks = set()
        for chunk in resolved_chunks.itervalues():
            if gems_to_remove.issuperset(chunk.artifacts):
                core_chunks.add(chunk)

        for chunk in core_chunks:
            del resolved_chunks[chunk.name]

        print 'Core gems: %s' % gems_to_remove
        print 'Core chunks: %s' % core_chunks

        # Now convert all build dependency lists to point at the chunk,
        # rather than name of the Gem.
        for chunk in resolved_chunks.itervalues():
            deps_as_gems = chunk.build_deps
            deps_as_chunks = set(resolved_gems[name] for name in deps_as_gems)
            # Delete any chunks that we decided not to build
            deps_as_chunks.difference_update(core_chunks)
            # Also stop a chunk depending on itself.
            if chunk in deps_as_chunks:
                deps_as_chunks.remove(chunk)
            chunk.build_deps = deps_as_chunks

            deps_as_gems = chunk.runtime_deps
            deps_as_chunks = set(resolved_gems[name] for name in deps_as_gems)
            deps_as_chunks.difference_update(core_chunks)
            if chunk in deps_as_chunks:
                deps_as_chunks.remove(chunk)
            chunk.runtime_deps = deps_as_chunks

        return resolved_chunks


class CreateStratum(object):
    def _sort_chunks(self, chunks):
        graph = {chunk:chunk.build_deps for chunk in chunks.itervalues()}
        return toposort.toposort_flatten(graph)

    def _sort_chunks_2(self, chunk_dict):
        sort_order = list(chunk_dict.keys())
        sort_order.sort(key=lambda x: x.lower())

        sorted_chunks = []
        satisfied_list = []

        # Simple try-try-again algorithm to satisfy dependency ordering too
        repeat_count = 0
        while len(sort_order) > 0:
            postponed_list = []

            for chunk_name in sort_order:
                deps_satisfied = True

                chunk = chunk_dict[chunk_name]
                for dep in chunk.build_deps:
                    assert dep != chunk
                    if dep not in satisfied_list:
                        deps_satisfied = False
                        break

                if deps_satisfied:
                    sorted_chunks.append(chunk)
                    satisfied_list.append(chunk_name)
                else:
                    postponed_list.append(chunk_name)

            if len(postponed_list) == len(sort_order):
                # We're probably stuck
                repeat_count += 1
                if repeat_count > 100:
                    raise Exception(
                        'Cannot order these chunks: %s. Probably circular '
                        'dependencies.' % ', '.join(postponed_list))

            sort_order = sorted(postponed_list, reverse=True)
        return sorted_chunks

    def _process_chunks(self, chunks):
        sorted_chunk_list = self._sort_chunks(chunks)
        chunk_info_list = []
        for chunk in sorted_chunk_list:
            info = {
                'name': chunk.name,
                'repo': chunk.repo,
                'ref': chunk.ref,
                'build-depends': [dep.name for dep in chunk.build_deps]
            }
            chunk_info_list.append(info)
        return chunk_info_list

    def create_stratum(self, name, chunks):
        stratum = {
            'name': name,
            'kind': 'stratum',
            'chunks': self._process_chunks(chunks),
        }
        return stratum


resolver = RubyGemsResolver()

chunks = resolver.resolve_chunks_for_gems(gems)

def get_reverse_dependencies(chunks):
    for chunk_info in chunks.itervalues():
        for dep_chunk in chunk_info.build_deps:
            chunk_rdeps = getattr(dep_chunk, 'n_reverse_dependencies', 0) + 1
            dep_chunk.n_reverse_dependencies = chunk_rdeps

    rdeps = {}
    for chunk_name, chunk_info in chunks.iteritems():
        rdeps[chunk_name] = getattr(chunk_info, 'n_reverse_dependencies', 0)
    n_reverse_dependencies = lambda x: x[1]
    return sorted(rdeps.iteritems(), key=n_reverse_dependencies)


def get_dependency_loops(chunks):
    '''Return all dependency loops, shorted first.'''
    graph = {chunk:chunk.build_deps for chunk in chunks.itervalues()}
    transitive_closure = tarjan.tc.tc(graph)
    loops_set = set()
    for key,value in transitive_closure.iteritems():
        if key in value:
            loops_set.add(value)
    return sorted(loops_set, key=lambda x: len(x))


print get_reverse_dependencies(chunks)
loops = get_dependency_loops(chunks)

if len(loops) > 0:
    for loop in loops:
        print 'Dependency loop: ', ', '.join(chunk.name for chunk in loop)
        most_deps = sorted(loop, key=lambda chunk: len(chunk.build_deps))
        print 'Of these, %s has the most build dependencies' % (most_deps[0])
        print '(chunk %s has artifacts: %s)' % (most_deps[0], most_deps[0].artifacts)
        print 'Of these, %s has the least build dependencies' % (most_deps[-1])
        print '(chunk %s has artifacts: %s)' % (most_deps[-1], most_deps[-1].artifacts)

stratum = CreateStratum().create_stratum('rubytest', chunks)

print stratum
print json.dumps(stratum, indent=4)
