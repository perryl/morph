# Copyright (C) 2012, 2013, 2014  Codethink Limited
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
import os

import morphlib


class GraphArtifact(object):
    def __init__(self, source):
        self.name = source.name
        self.source = source

class GraphingPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('graph-sources',
                                self.graph_sources,
                                arg_synopsis='REPO REF SYSTEM')

        self.app.add_subcommand(
            'graph-artifacts',
            self.graph_artifacts,
            arg_synopsis='REPO REF STRATUM')

        group_graphing = 'Graphing Options'

        self.app.settings.boolean(
            ['show-all-edges'],
            "A chunk 'foo' in stratum A build depends on "
            'a stratum B if stratum A depends on B, '
            "these 'implicit' dependencies are not shown "
            'by default',
            group=group_graphing)

    def disable(self):
        pass

    def add_edge(self, source, dest, f):
        f.write('  "%s" -> "%s";\n' % (source, dest))

    def add_source_to_graph(self, source, f):
        shape_name = {
            'system': 'octagon',
            'stratum': 'box',
            'chunk': 'ellipse',
        }

        f.write('  "%s" [shape=%s];\n' % (source.name,
                                          shape_name[source.kind]))

    def add_source_artifacts_to_graph(self, source, f):
        for artifact_name in source.artifacts:
            self.add_edge(artifact_name, source.name, f)

    def add_source_dependencies_to_graph(self, source, deps, f):
        for dep in deps:
            if self.app.settings['show-all-edges']:
                self.add_edge(source.name, dep.name, f)
            elif (source.kind in ['stratum', 'system']
                  or dep.source.kind != 'stratum'):
                # We don't want to draw edges between chunks
                # and the strata they depend on, this dependency
                # is implicit
                self.add_edge(source.name, dep.name, f)

    def graph_build_prep(self, args):
        for repo_name, ref, filename in self.app.itertriplets(args):
            self.app.status(msg='Creating build order for '
                                '%(repo_name)s %(ref)s %(filename)s',
                            repo_name=repo_name, ref=ref, filename=filename)

            builder = morphlib.buildcommand.BuildCommand(self.app)
            srcpool = builder.create_source_pool(repo_name, ref, filename)

            self.app.status(msg='Creating artifact resolver', chatty=True)
            ar = morphlib.artifactresolver.ArtifactResolver()

            root_artifacts = ar.resolve_root_artifacts(srcpool)

            path, ext = os.path.splitext(filename)
            _, tail = os.path.split(path)
            dot_filename = tail + '.gv'

        return srcpool, root_artifacts, dot_filename

    def graph_sources(self, args):
        '''Create a visualisation of sources in a system.

        Command line arguments:

        * `REPO` is a repository URL.
        * `REF` is a git reference (usually branch name).
        * `SYSTEM` is a system morphology.

        This produces a GraphViz DOT file representing all the build
        dependencies within a system, based on information in the
        morphologies.  The GraphViz `dot` program can then be used to
        create a graphical representation of the dependencies. This
        can be helpful for inspecting whether there are any problems in
        the dependencies.

        Example:

            morph graph-sources baserock:baserock/definitions master \
systems/devel-system-x86_64-generic.morph
            dot -T png devel-system-x86_64-generic.gv \
> devel-system-x86_64-generic.gv

        The above creates a picture showing \
all the sources in the devel system.

        Note that edges between chunks that come from different strata are not
        shown since that dependency is implied by one stratum depending on
        another. To show all edges regardless you can use the --show-all-edges
        option.

        GraphViz is not currently part of Baserock so you need to run
        `dot` on another system.

        '''

        _, root_artifacts, dot_filename = self.graph_build_prep(args)

        if len(root_artifacts) > 1:
            raise cliapp.AppException('Resolved multiple root artifacts')

        root_artifact = root_artifacts[0]

        if root_artifact.source.kind != 'system':
            cliapp.AppException(
                'graph-sources expects a system but got a %s: %s'
                % (root_artifact.kind, root_artifact.name))

        self.app.status(msg='Writing DOT file to %(filename)s',
                        filename=dot_filename)

        with open(dot_filename, 'w') as f:
            f.write('digraph "%s" {\n' % dot_filename)
            sources = set(a.source for a in root_artifact.walk())

            for source in sources:
                self.add_source_to_graph(source, f)

                deps = set(GraphArtifact(a.source)
                            for a in source.dependencies)
                self.add_source_dependencies_to_graph(source, deps, f)

            f.write('}\n')

    def graph_stratum_root(self, artifact, srcpool, f):
        if artifact.source.kind != 'stratum':
            raise cliapp.AppException(
                'graph-artifacts expects a stratum but got a %s: %s'
                % (artifact.kind, artifact.name))

        strata = [a for a in artifact.walk() if a.source.kind == 'stratum']
        strata.remove(artifact)

        foreign_chunks = []

        for stratum in strata:
            for info in stratum.source.morphology['chunks']:
                filename = morphlib.util.sanitise_morphology_path(
                    info.get('morph', info['name']))
                chunk_source = srcpool.lookup(info['repo'],
                                              info['ref'], filename)[0]
                foreign_chunks.append(chunk_source)

            self.add_source_to_graph(stratum.source, f)

        self.add_source_to_graph(artifact.source, f)
        self.add_source_artifacts_to_graph(artifact.source, f)
        self.add_source_dependencies_to_graph(
            artifact.source, artifact.source.dependencies, f)

        sources = set(a.source for a in artifact.walk()
                       if a.source.kind != 'stratum')

        if not all(True for source in sources if source.kind == 'chunk'):
            raise morphlib.Error('Expected only chunk sources')

        for source in sources:
            if source in foreign_chunks:
                # skip chunks that aren't in the stratum we're graphing
                continue

            self.add_source_to_graph(source, f)
            self.add_source_artifacts_to_graph(source, f)
            self.add_source_dependencies_to_graph(source,
                                                  source.dependencies, f)

    def graph_artifacts(self, args):
        '''Create a visualisation of artifacts in a stratum.

        Command line arguments:

        * `REPO` is a repository URL.
        * `REF` is a git reference (usually branch name).
        * `STRATUM` is a system morphology.

        This produces a GraphViz DOT file representing all the build
        dependencies within a system, based on information in the
        morphologies.  The GraphViz `dot` program can then be used to
        create a graphical representation of the dependencies. This
        can be helpful for inspecting whether there are any problems in
        the dependencies.

        Example:

            morph graph-artifacts baserock:baserock/definitions master \
strata/build-essential.morph
            dot -T png build-essential-minimal.gv > build-essential-minimal.png
            dot -T png build-essential-devel.gv > build-essential-devel.png
            dot -T png build-essential-runtime.gv > build-essential-runtime.png

        The above creates a picture for each stratum split in the
        build-essential stratum. These pictures won't include artifacts
        that are included as build dependencies from other strata.

        Note that edges between chunks that come from different strata are not
        shown since that dependency is implied by one stratum depending on
        another. To show all edges regardless you can use the --show-all-edges
        option.

        GraphViz is not currently part of Baserock so you need to run
        `dot` on another system.

        '''
        srcpool, root_artifacts, _ = self.graph_build_prep(args)

        for artifact in root_artifacts:
            dot_filename = artifact.name + '.gv'
            self.app.status(msg='Writing DOT file to %(filename)s',
                            filename=dot_filename)

            with open(dot_filename, 'w') as f:
                f.write('digraph "%s" {\n' % dot_filename)
                self.graph_stratum_root(artifact, srcpool, f)
                f.write('}\n')
