# Still to do:

#   - not all Gems are resolved to the right source repos so far: that needs to
#   change (just hardcode the unknown ones, for now).

#   - needs to output the 'ruby-core' stratum (stuff that other stuff in Ruby
#   build-depends on, that should probably all be installed using 'Gem' to
#   avoid circular dependencies). 'chef', 'gitlab', 'heroku', etc. strata,
#   which contain just the necessary stuff for those, built from source or
#   Gems, and 'ruby-foundation', which contains the common chunks from those
#   strata (build from source or Gems, again).


import networkx
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

    def __repr__(self):
        return '<chunk %s>' % self.name

    def __str__(self):
        return self.name

    def add_build_deps(self, dependencies):
        self.build_deps.update(set(dependencies))

    def add_runtime_deps(self, dependencies):
        self.runtime_deps.update(set(dependencies))

    def add_artifact(self, artifact):
        assert isinstance(artifact, Artifact)
        self.artifacts.add(artifact)

    def walk_deps(self):
        '''Find all dependencies of this source.

        If it is being built to run in the resulting system, we care only
        about the build dependencies. If it's something that's a build
        dependency of something else, then we care about the runtime
        dependencies too because it's likely to be executed at built time.

        '''
        done = set()

        def depth_first(source):
            if source not in done:
                done.add(source)

                for dep in sorted(source.build_deps):
                    for ret in depth_first(dep.source):
                        yield ret

                yield source

        return depth_first(self)


class Artifact(object):
    def __init__(self, name, source):
        self.name = name
        self.source = source


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
        used_at_build_time = set()

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
                used_at_build_time.add(artifact.source)

        for chunk in sources.itervalues():
            dep_names = chunk.runtime_deps
            dep_artifacts = set(artifacts[name] for name in dep_names)
            dep_artifacts.difference_update(chunk.artifacts)

            # If a chunk is needed at build time, all its dependencies are
            # needed at build time too.
            if chunk in used_at_build_time:
                chunk.build_deps.update(dep_artifacts)
                chunk.runtime_deps = set()
            else:
                chunk.runtime_deps = dep_artifacts


class DependencyGraphSolver(object):
    def solve(self, chunks, goal_chunks, built_in_artifacts):
        bootstrap = set()

        # Eventually this should produce:
        #   - runtime dependency info? yeah, for a -runtime split stratum
        #   - devel dependency info, for -devel split stratum
        # Produce graph from the set of chunks
        graph = networkx.DiGraph()
        for chunk in chunks.itervalues():
            graph.add_node(chunk)
            graph.add_edges_from((chunk, dep.source) for dep in
                                 chunk.build_deps)
            #graph.add_edges_from((chunk, dep.source) for dep in chunk.build_deps)

        def solve_loop(loop):
            # FIXME: this algorithm isn't good enough, what we need to do is
            # compute the shortest path within the cycle and remove that one...
            n_build_deps = lambda chunk: len(list(chunk.walk_deps()))
            to_remove = sorted(loop, key=n_build_deps, reverse=True)[0]
            print 'Moving chunk %s to bootstrap as it has only %i deps' % \
                (to_remove, n_build_deps(to_remove))
            for c in chunks.itervalues():
                c.build_deps.difference_update(to_remove.artifacts)
            # It makes sense to remove the chunk which has the smallest set of
            # dependencies, but because this is a loop, all chunks in the loop
            # will be removed because they all depend on each other. This is
            # dumb but it will have to do for now.
            chunk_and_deps = list(to_remove.walk_deps())
            bootstrap.update(chunk_and_deps)
            graph.remove_nodes_from(chunk_and_deps)

        for i in range(0,10):
            # This outputs ALL cycles (the transitive closure). I don't really
            # want all permutations, just one instance of each cycle. ...
            # FIXME: also, this seems to become infinite quite easily ... maybe
            # I should use tarjan.tc.tc() instead.
            loops = networkx.simple_cycles(graph)
            #for l in loops:
             #   print l
            #loops_by_length = sorted(loops, key=lambda x: len(x))
            #if len(loops_by_length) == 0:
            #    break
            #print '%i dependency loops' % len(loops_by_length)
            #print 'Removing loop %s' % loops_by_length[0]
            #solve_loop(loops_by_length[0])
            # solve the loop
            try:
                loop = next(loops)
            except StopIteration:
                break
            print 'Removing loop %s' % loop
            solve_loop(loop)

        # This is the set we'll install as Gems, systemwide.
        print 'Bootstrap set: %s' % bootstrap

        build_order = networkx.topological_sort(graph)

        print 'Build order: %s' % build_order
        import pdb
        pdb.set_trace()

        return bootstrap, build_order


class CreateStratum(object):
    def solve_build_graph(self, chunks):
        # Construct graph from dependency info. Note that only the 'goal'
        # chunks are the ones we care about running in the build system.
        # Thus, all dependencies become build dependencies except those of the
        # goal chunks, because every other chunk is there because we want it to
        # run as part of the build process.

        def chunk_is_build_tool_only(chunk):
            return (len(chunk.artifacts.intersection(goals)) == 0)

        for chunk in chunks.itervalues():
            if chunk_is_build_tool_only(chunk):
                chunk.build_deps.update(chunk.runtime_deps)
                chunk.runtime_deps = []

        graph = {chunk:chunk.build_deps for chunk in chunks.itervalues()}

        def get_dependency_loops(graph):
            '''Return all dependency loops, shortest first.'''
            transitive_closure = tarjan.tc.tc(graph)
            loops_set = set()
            for key,value in transitive_closure.iteritems():
                if key in value:
                    loops_set.add(value)
            return sorted(loops_set, key=lambda x: len(x))

        loops = get_dependency_loops(graph)
        if len(loops) > 0:
            for loop in loops:
                print 'Dependency loop: ', ', '.join(chunk.name for chunk in loop)
                most_deps = sorted(loop, key=lambda chunk: len(chunk.build_deps))
                print 'Of these, %s has the most build dependencies' % (most_deps[0])
                print '(chunk %s has artifacts: %s)' % (most_deps[0], most_deps[0].artifacts)
                print 'Of these, %s has the least build dependencies' % (most_deps[-1])
                print '(chunk %s has artifacts: %s)' % (most_deps[-1], most_deps[-1].artifacts)

                graph_for_loop = {chunk:chunk.build_deps for chunk in loop}
                loop_tc = tarjan.tc.tc(graph_for_loop)
                print 'TC for loop:'
                for k, v in loop_tc.iteritems():
                    print '\t%s: %s' % (k.name, ', '.join(c.name for c in v))
                print '\n\n'

        return graph

    def _sort_graph(self, graph):
        return toposort.toposort_flatten(graph)

    def _process_chunks(self, chunks):
        graph = self.solve_build_graph(chunks)
        sorted_chunk_list = self._sort_graph(graph)
        chunk_info_list = []
        for chunk in sorted_chunk_list:
            info = {
                'name': chunk.name,
                'repo': chunk.repo,
                'ref': chunk.ref,
                'build-depends': [dep.name for dep in chunk.build_deps],
                # Not used in Baserock, but useful info for debugging.
                'runtime-depends': [dep.name for dep in chunk.runtime_deps],
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

chunks = resolver.resolve_chunks_for_gems(goals)

graph_solver = DependencyGraphSolver()
graphs = graph_solver.solve(chunks, goals, built_in_gems)

print graphs

stratum = CreateStratum().create_stratum('rubytest', chunks)

print stratum
print json.dumps(stratum, indent=4)
