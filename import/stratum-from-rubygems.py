# Still to do:

#   - not all Gems are resolved to the right source repos so far: that needs to
#   change (just hardcode the unknown ones, for now).

#   - needs to output the 'ruby-core' stratum (stuff that other stuff in Ruby
#   build-depends on, that should probably all be installed using 'Gem' to
#   avoid circular dependencies). 'chef', 'gitlab', 'heroku', etc. strata,
#   which contain just the necessary stuff for those, built from source or
#   Gems, and 'ruby-foundation', which contains the common chunks from those
#   strata (build from source or Gems, again).

#   - needs to check out each goal chunk's source code, and look for a
#   Gemfile.lock file.


import networkx
import requests
import requests_cache
import tarjan.tc
import toposort
import yaml

import collections
import logging
import json
import os
import urlparse
from itertools import chain
from logging import debug


logging.basicConfig(level=logging.DEBUG)


# Some random popular Gems
goals = [
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

# This tool works to a rather pessimistic rule that any chunk that's used at
# build time requires all of its runtime dependencies available at build time
# too. This might not be the case, and in some cases it causes unsolvable
# dependency loops. Solve them by adding them to this list.
runtime_only_dependencies = [
    # Chef clients require Ohai at runtime. Ohai requires Chef at build time,
    # but this is just to to be present at that point.
    ('chef', 'ohai')
]

# Shorter!
#gems = ['vagrant']

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


class Source(object):
    def __init__(self, name, repo, ref, build_deps=[], runtime_deps=[]):
        self.name = name
        self.repo = repo
        self.ref = ref
        self.build_deps = set(build_deps)
        self.runtime_deps = set(runtime_deps)
        self.artifacts = set()

        self.used_at_build_time = False

    def __repr__(self):
        return '<source %s>' % self.name

    def __str__(self):
        return self.name

    def add_build_deps(self, dependencies):
        self.build_deps.update(set(dependencies))

    def add_runtime_deps(self, dependencies):
        self.runtime_deps.update(set(dependencies))

    def add_artifact(self, artifact):
        assert isinstance(artifact, Artifact)
        self.artifacts.add(artifact)

    def walk_build_deps(self):
        '''Find all build-dependencies of this source.

        If it is being built to run in the resulting system, we care only
        about the build dependencies. If it's something that's a build
        dependency of something else, then we care about the runtime
        dependencies too because it's likely to be executed at built time.

        '''
        done = set()

        def depth_first(list, source):
            if source not in done:
                done.add(source)

                for dep in sorted(source.build_deps):
                    for ret in depth_first(dep.source):
                        yield ret

                yield source

        return depth_first(self)

    def walk_runtime_deps(self):
        '''Find all runtime dependencies of this source.'''
        done = set()

        def depth_first(source):
            if source not in done:
                done.add(source)

                for dep in sorted(source.runtime_deps):
                    for ret in depth_first(dep.source):
                        yield ret

                yield source

        return depth_first(self)

class Artifact(object):
    def __init__(self, name, source):
        self.name = name
        self.source = source

    def __repr__(self):
        return '<artifact %s>' % self.name

    def __str__(self):
        return self.name


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

            # There are version constraints specified here that we
            # currently ignore. Furthermore, the Gemfile.lock (Bundler)
            # file may have an even more specific constraint! I think
            # ideally we want to run 'master' of everything, or at least
            # the last tagged commit of everything, so let's ignore this
            # info for now and start some builds!

            for dep_info in gem_build_deps + gem_runtime_deps:
                dep_name = dep_info['name']
                ignore = chain(to_process, resolved_gems.iterkeys(),
                               built_in_gems)
                if dep_name not in ignore:
                    to_process.append(dep_name)

            chunk_build_deps = set()
            chunk_runtime_deps = set()

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
                chunk = Source(chunk_name, repo, ref, chunk_build_deps,
                               chunk_runtime_deps)
                resolved_chunks[chunk_name] = chunk
            else:
                chunk.add_build_deps(chunk_build_deps)
                chunk.add_runtime_deps(chunk_runtime_deps)

            artifact = Artifact(gem_name, chunk)
            resolved_gems[gem_name] = artifact
            chunk.add_artifact(artifact)

        self.resolve_dependencies(resolved_chunks, resolved_gems)

        return resolved_chunks

    def resolve_dependencies(self, sources, artifacts):
        # Convert the dependencies from being lists of names to being the
        # actual artifact objects.
        for chunk in sources.itervalues():
            dep_names = chunk.build_deps
            dep_artifacts = set(artifacts[name] for name in dep_names)
            # Dependencies between artifacts from the same source cause the
            # source to depend on itself. Remove those.
            dep_artifacts.difference_update(chunk.artifacts)
            chunk.build_deps = dep_artifacts

            for artifact in dep_artifacts:
                artifact.source.used_at_build_time = True

        for chunk in sources.itervalues():
            dep_names = chunk.runtime_deps
            dep_artifacts = set(artifacts[name] for name in dep_names)
            dep_artifacts.difference_update(chunk.artifacts)

            chunk.runtime_deps = dep_artifacts


class DependencyGraphSolver(object):
    def get_dependency_loops(self, graph):
        '''Return a subgraph for each cycle in the build graph.'''

        subgraphs = networkx.strongly_connected_component_subgraphs(
            graph, copy=False)

        # Nodes with no edges at all are considered strongly connected, but
        # these are not important to us.
        loop_subgraphs = [g for g in subgraphs if g.number_of_nodes() > 1]

        return loop_subgraphs

    def save_as_dot(self, graph, path):
        # requires pygraphviz
        networkx.write_dot(graph, path)

    def solve(self, chunks, goal_chunks):
        # Eventually this should produce:
        #   - runtime dependency info? yeah, for a -runtime split stratum
        #   - devel dependency info, for -devel split stratum
        # Produce graph from the set of chunks
        graph = networkx.DiGraph()
        for chunk in chunks.itervalues():
            graph.add_node(chunk)
            graph.add_edges_from((chunk, dep.source) for dep in
                                 chunk.build_deps)
            if chunk.used_at_build_time:
                graph.add_edges_from((chunk, dep.source) for dep in
                                    chunk.runtime_deps)

        bootstrap = networkx.DiGraph()

        def chunk_is_goal(chunk):
            return chunk.name in goals

        def graph_to_string(graph):
            return ', '.join(n.name for n in graph.nodes())

        def move_chunk_to_bootstrap(chunk, loop_graph):
            chunk_and_deps = set(chunk.walk_runtime_deps())

            for chunk in chunk_and_deps:
                if chunk_is_goal(chunk):
                    raise Exception(
                        'Unable to build chunk %s from source, due to '
                        'the following loop: %s' % (chunk.name,
                        graph_to_string(loop_graph)))

            graph.remove_nodes_from(chunk_and_deps)
            loop_graph.remove_nodes_from(chunk_and_deps)

            bootstrap.add_node(chunk)

        def solve_loop(loop, n):
            debug('%i: Found dependency loop of %i chunks.', n,
                  loop.number_of_nodes())

            cut = networkx.minimum_node_cut(loop)
            for chunk in cut:
                # FIXME: this'll raise an exception if the minimum cut
                # includes a goal chunk. Right now the user needs to
                # solve the circular dep themselves, if that happens.
                debug('%i: Removing %s and runtime deps', n, cut)
                move_chunk_to_bootstrap(chunk, loop)

            subloops = self.get_dependency_loops(loop)
            if len(subloops) > 0:
                solve_loops(subloops, n=n+1)

        def solve_loops(loops, n=0):
            all_loops = networkx.union_all(loops)
            self.save_as_dot(all_loops, 'loops-%i.dot' % n)

            for loop in loops:
                solve_loop(loop, n)

        loops = self.get_dependency_loops(graph)
        if len(loops) > 0:
            solve_loops(loops)

        bootstrap_order = bootstrap.nodes()
        build_order = networkx.topological_sort(graph, reverse=True)

        print bootstrap_order

        return bootstrap_order, build_order


class CreateStratum(object):
    def _process_chunks(self, sorted_chunks, bootstrap_set):
        chunk_info_list = []
        for chunk in sorted_chunks:
            info = {
                'name': chunk.name,
                'repo': chunk.repo,
                'ref': chunk.ref,
                'build-depends': [dep.name for dep in chunk.build_deps if
                                  dep.source not in bootstrap_set],
                # Not used in Baserock, but useful info for debugging.
                'runtime-depends': [dep.name for dep in chunk.runtime_deps if
                                    dep.source not in bootstrap_set],
            }
            chunk_info_list.append(info)
        return chunk_info_list

    def create_stratum(self, name, sorted_chunks, bootstrap_set):
        stratum = {
            'name': name,
            'kind': 'stratum',
            'chunks': self._process_chunks(sorted_chunks, bootstrap_set),
        }
        return stratum


resolver = RubyGemsResolver()

chunks = resolver.resolve_chunks_for_gems(goals)

graph_solver = DependencyGraphSolver()
bootstrap_set, build_order = graph_solver.solve(chunks, goals)

# Create a shell script that installs bootstrap Gems manually.
with open('bootstrap.sh', 'w') as f:
    f.write('# Minimal set of Gems required to build all other dependencies\n'
            '# of: %s\n\n' % ', '.join(goals))
    for source in sorted(bootstrap_set, key=lambda s: s.name):
        runtime_deps = [a.name for a in source.runtime_deps]
        artifacts_str = ' '.join([a.name for a in source.artifacts])
        f.write('\n# Source: %s\n' % source.name)
        f.write('# Depends on: %s\n' % ', '.join(runtime_deps))
        f.write('gem install --ignore-dependencies %s\n' % artifacts_str)

stratum = CreateStratum().create_stratum('rubytest', build_order, bootstrap_set)

with open('rubytest.morph', 'w') as f:
    yaml.safe_dump(stratum, f, encoding='utf-8', allow_unicode=True)
