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


import cliapp
import collections

import morphlib


class MutualDependencyError(cliapp.AppException):

    def __init__(self, a, b):
        cliapp.AppException.__init__(
            self, 'Cyclic dependency between %s and %s detected' % (a, b))


class DependencyOrderError(cliapp.AppException):

    def __init__(self, stratum, chunk, dependency_name):
        cliapp.AppException.__init__(
            self, 'In stratum %s, chunk %s references its dependency %s '
            'before it is defined' %
            (stratum.source, chunk, dependency_name))


class DependencyFormatError(cliapp.AppException):

    def __init__(self, stratum, chunk):
        cliapp.AppException.__init__(
            self, 'In stratum %s, chunk %s uses an invalid '
            'build-depends format' % (stratum.source, chunk))


class UndefinedChunkArtifactError(cliapp.AppException):

    '''Exception raised when non-existent artifacts are referenced.

    Usually, this will only occur when a stratum refers to a chunk
    artifact that is not defined in a chunk.

    '''

    def __init__(self, parent, reference):
        cliapp.AppException.__init__(
            self, 'Undefined chunk artifact "%s" referenced in '
            'stratum %s' % (reference, parent))


class ArtifactResolver(object):

    '''Resolves sources into artifacts that would be build from the sources.

    This class takes a CacheKeyComputer and a SourcePool, analyses the
    sources and their dependencies and creates a list of artifacts
    (represented by Artifact objects) that are involved in building the
    sources in the pool.

    '''

    def __init__(self):
        self._added_artifacts = None
        self._source_pool = None

    def resolve_artifacts(self, source_pool):
        self._source_pool = source_pool
        self._added_artifacts = set()

        artifacts = self._resolve_artifacts_recursively()
        # TODO perform cycle detection, e.g. based on:
        # http://stackoverflow.com/questions/546655/finding-all-cycles-in-graph
        return artifacts

    def _resolve_artifacts_recursively(self):
        artifacts = []

        queue = self._create_initial_queue()
        while queue:
            source = queue.popleft()

            if source.morphology['kind'] == 'system':
                systems = [source.get_artifact(a)
                           for a in source.morphology.builds_artifacts]

                if any(a not in self._added_artifacts for a in systems):
                    artifacts.extend(systems)
                    self._added_artifacts.update(systems)

                resolved_artifacts = self._resolve_system_dependencies(
                    systems, source, queue)

                for artifact in resolved_artifacts:
                    if not artifact in self._added_artifacts:
                        artifacts.append(artifact)
                        self._added_artifacts.add(artifact)
            elif source.morphology['kind'] == 'stratum':
                assert len(source.morphology.builds_artifacts) == 1
                artifact = source.get_artifact(
                    source.morphology.builds_artifacts[0])

                if not artifact in self._added_artifacts:
                    artifacts.append(artifact)
                    self._added_artifacts.add(artifact)

                resolved_artifacts = self._resolve_stratum_dependencies(
                    artifact, queue)

                for artifact in resolved_artifacts:
                    if not artifact in self._added_artifacts:
                        artifacts.append(artifact)
                        self._added_artifacts.add(artifact)
            elif source.morphology['kind'] == 'chunk':
                names = source.morphology.builds_artifacts
                for name in names:
                    artifact = source.get_artifact(name)
                    if not artifact in self._added_artifacts:
                        artifacts.append(artifact)
                        self._added_artifacts.add(artifact)

        return artifacts

    def _create_initial_queue(self):
        if all([x.morphology['kind'] == 'chunk' for x in self._source_pool]):
            return collections.deque(self._source_pool)
        else:
            sources = [x for x in self._source_pool
                       if x.morphology['kind'] != 'chunk']
            return collections.deque(sources)

    def _resolve_system_dependencies(self, systems, source, queue):
        artifacts = []

        for info in source.morphology['strata']:
            stratum_source = self._source_pool.lookup(
                info['repo'] or source.repo_name,
                info['ref'] or source.original_ref,
                '%s.morph' % info['morph'])

            stratum_name = stratum_source.morphology.builds_artifacts[0]
            stratum = stratum_source.get_artifact(stratum_name)

            for system in systems:
                system.add_dependency(stratum)
            queue.append(stratum_source)

            artifacts.append(stratum)

        return artifacts

    def _resolve_stratum_dependencies(self, stratum, queue):
        artifacts = []

        strata = []

        if stratum.source.morphology['build-depends']:
            for stratum_info in stratum.source.morphology['build-depends']:
                other_source = self._source_pool.lookup(
                    stratum_info['repo'] or stratum.source.repo_name,
                    stratum_info['ref'] or stratum.source.original_ref,
                    '%s.morph' % stratum_info['morph'])

                other_stratum = other_source.get_artifact(
                    other_source.morphology.builds_artifacts[0])

                strata.append(other_stratum)

                artifacts.append(other_stratum)

                if other_stratum.depends_on(stratum):
                    raise MutualDependencyError(stratum, other_stratum)

                stratum.add_dependency(other_stratum)
                queue.append(other_source)

        # 'name' here is the chunk artifact name
        chunk_artifacts = []
        processed_artifacts = []
        name_to_processed_artifact = {}

        for info in stratum.source.morphology['chunks']:
            chunk_source = self._source_pool.lookup(
                info['repo'],
                info['ref'],
                '%s.morph' % info['morph'])

            possible_names = chunk_source.morphology.builds_artifacts
            if not info['name'] in possible_names:
                raise UndefinedChunkArtifactError(stratum.source, info['name'])

            chunk_artifact = chunk_source.get_artifact(info['name'])
            chunk_artifacts.append(chunk_artifact)

            artifacts.append(chunk_artifact)

            stratum.add_dependency(chunk_artifact)

            for other_stratum in strata:
                chunk_artifact.add_dependency(other_stratum)

            # Resolve now to avoid a search for the parent morphology later
            chunk_source.build_mode = info['build-mode']
            chunk_source.prefix = info['prefix']

            build_depends = info.get('build-depends', None)

            if build_depends is None:
                for earlier_artifact in processed_artifacts:
                    if earlier_artifact.depends_on(chunk_artifact):
                        raise MutualDependencyError(
                            chunk_artifact, earlier_artifact)
                    chunk_artifact.add_dependency(earlier_artifact)
            elif isinstance(build_depends, list):
                for name in build_depends:
                    other_artifact = name_to_processed_artifact.get(name, None)
                    if other_artifact:
                        chunk_artifact.add_dependency(other_artifact)
                    else:
                        raise DependencyOrderError(
                            stratum, info['name'], name)
            else:
                raise DependencyFormatError(stratum, info['name'])
            processed_artifacts.append(chunk_artifact)
            name_to_processed_artifact[info['name']] = chunk_artifact

        return artifacts
