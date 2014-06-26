# beak: tools for writing Baserock importers


import networkx

from logging import debug


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

    def solve(self, chunks, goal_names):
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
            return chunk.name in goal_names

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

