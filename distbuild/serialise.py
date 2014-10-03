# distbuild/serialise.py -- (de)serialise Artifact object graphs
#
# Copyright (C) 2012, 2014  Codethink Limited
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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA..


import base64
import json
import yaml

import morphlib
import logging


def serialise_artifact(artifact):
    '''Serialise an Artifact object and its dependencies into string form.'''

    def encode_morphology(morphology):
        result = {}
        for key in morphology.keys():
            result[key] = morphology[key]
        return result
    
    def encode_source(source, prune_leaf=False):
        source_dic = {
            'name': source.name,
            'repo': None,
            'repo_name': source.repo_name,
            'original_ref': source.original_ref,
            'sha1': source.sha1,
            'tree': source.tree,
            'morphology': id(source.morphology),
            'filename': source.filename,
            'artifact_ids': [],
            'cache_id': source.cache_id,
            'cache_key': source.cache_key,
            'dependencies': [],
        }
        if not prune_leaf:
            source_dic['artifact_ids'].extend(id(artifact) for (_, artifact)
                                              in source.artifacts.iteritems())
            source_dic['dependencies'].extend(id(d)
                                              for d in source.dependencies)

        if source.morphology['kind'] == 'chunk':
            source_dic['build_mode'] = source.build_mode
            source_dic['prefix'] = source.prefix
        return source_dic

    def encode_artifact(a):
        if artifact.source.morphology['kind'] == 'system': # pragma: no cover
            arch = artifact.source.morphology['arch']
        else:
            arch = artifact.arch

        return {
            'source_id': id(a.source),
            'name': a.name,
            'arch': arch,
            'dependents': [id(d)
                for d in a.dependents],
        }

    encoded_artifacts = {}
    encoded_sources = {}
    encoded_morphologies = {}
    visited_artifacts = {}

    for a in artifact.walk():
        if id(a.source) not in encoded_sources:
            for sa in a.source.artifacts.itervalues():
                if id(sa) not in encoded_artifacts:
                    visited_artifacts[id(sa)] = sa
                    encoded_artifacts[id(sa)] = encode_artifact(sa)
            encoded_morphologies[id(a.source.morphology)] = \
                encode_morphology(a.source.morphology)
            encoded_sources[id(a.source)] = encode_source(a.source)

        if id(a) not in encoded_artifacts: # pragma: no cover
            visited_artifacts[id(a)] = a
            encoded_artifacts[id(a)] = encode_artifact(a)

    # Include one level of dependents above encoded artifacts, as we need
    # them to be able to tell whether two sources are in the same stratum.
    for a in visited_artifacts.itervalues():
        for source in a.dependents: # pragma: no cover
            if id(source) not in encoded_sources:
                encoded_morphologies[id(source.morphology)] = \
                    encode_morphology(source.morphology)
                encoded_sources[id(source)] = \
                    encode_source(source, prune_leaf=True)

    content = {
        'sources': encoded_sources,
        'artifacts': encoded_artifacts,
        'morphologies': encoded_morphologies,
        'root_artifact': id(artifact),
        'default_split_rules': {
            'chunk': morphlib.artifactsplitrule.DEFAULT_CHUNK_RULES,
            'stratum': morphlib.artifactsplitrule.DEFAULT_STRATUM_RULES,
        },
    }
    return json.dumps(base64.standard_b64encode(yaml.dump(content)))


def deserialise_artifact(encoded):
    '''Re-construct the Artifact object (and dependencies).
    
    The argument should be a string returned by ``serialise_artifact``.
    The reconstructed Artifact objects will be sufficiently like the
    originals that they can be used as a build graph, and other such
    purposes, by Morph.
    
    '''

    def decode_morphology(le_dict):
        '''Convert a dict into something that kinda acts like a Morphology.
        
        As it happens, we don't need the full Morphology so we cheat.
        Cheating is good.
        
        '''
        
        return morphlib.morphology.Morphology(le_dict)

    def decode_source(le_dict, morphology, split_rules):
        '''Convert a dict into a Source object.'''

        source = morphlib.source.Source(le_dict['name'],
                                        le_dict['repo_name'],
                                        le_dict['original_ref'],
                                        le_dict['sha1'],
                                        le_dict['tree'],
                                        morphology,
                                        le_dict['filename'],
                                        split_rules)

        if morphology['kind'] == 'chunk':
            source.build_mode = le_dict['build_mode']
            source.prefix = le_dict['prefix']
        source.cache_id =  le_dict['cache_id']
        source.cache_key = le_dict['cache_key']
        return source
        
    def decode_artifact(artifact_dict, source):
        '''Convert dict into an Artifact object.
        
        Do not set dependencies, that will be dealt with later.
        
        '''

        artifact = morphlib.artifact.Artifact(source, artifact_dict['name'])
        artifact.arch = artifact_dict['arch']
        artifact.source = source

        return artifact

    le_dicts = yaml.load(base64.standard_b64decode(json.loads(encoded)))
    artifacts_dict = le_dicts['artifacts']
    sources_dict = le_dicts['sources']
    morphologies_dict = le_dicts['morphologies']
    root_artifact = le_dicts['root_artifact']
    assert root_artifact in artifacts_dict

    artifacts = {}
    sources = {}
    morphologies = {id: decode_morphology(d)
                    for (id, d) in morphologies_dict.iteritems()}

    # Decode sources
    for source_id, source_dict in sources_dict.iteritems():
        morphology = morphologies[source_dict['morphology']]
        kind = morphology['kind']
        ruler = getattr(morphlib.artifactsplitrule, 'unify_%s_matches' % kind)
        if kind in ('chunk', 'stratum'):
            rules = ruler(morphology, le_dicts['default_split_rules'][kind])
        else: # pragma: no cover
            rules = ruler(morphology)
        sources[source_id] = decode_source(source_dict, morphology, rules)

    # decode artifacts
    for artifact_id, artifact_dict in artifacts_dict.iteritems():
        source_id = artifact_dict['source_id']
        source = sources[source_id]
        artifact = decode_artifact(artifact_dict, source)
        artifacts[artifact_id] = artifact

    # add source artifacts reference
    for source_id, source in sources.iteritems():
        source_dict = sources_dict[source_id]
        source.artifacts = {artifacts[a].name: artifacts[a]
                            for a in source_dict['artifact_ids']}

    # add source dependencies
    for source_id, source_dict in sources_dict.iteritems():
        source = sources[source_id]
        source.dependencies = [artifacts[aid]
                               for aid in source_dict['dependencies']]

    # add artifact dependents
    for artifact_id, artifact in artifacts.iteritems():
        artifact_dict = artifacts_dict[artifact_id]
        artifact.dependents = [sources[sid]
                               for sid in artifact_dict['dependents']]

    return artifacts[root_artifact]
