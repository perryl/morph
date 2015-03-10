# distbuild/serialise.py -- (de)serialise Artifact object graphs
#
# Copyright (C) 2012, 2014, 2015  Codethink Limited
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


import json
import logging
import yaml

import morphlib


class ArtifactReference(object): # pragma: no cover

    '''Container for some basic information about an artifact.'''

    def __init__(self, basename, encoded):
        self._basename = basename
        self._dict = encoded

    def __getattr__(self, name):
        if not name.startswith('_'):
            return self._dict.get(name)
        else:
            super(ArtifactReference, self).__getattr(name)

    def __setattr__(self, name, val):
        if not name.startswith('_'):
            self._dict[name] = val
        else:
            super(ArtifactReference, self).__setattr__(name, val)

    def basename(self):
        return self._basename


def serialise_artifact(artifact, repo, ref):
    '''Serialise an Artifact object and its dependencies into string form.'''

    def encode_source(source):
        s_dict = {
            'filename': source.filename,
            'kind': source.morphology['kind'],
            'source_repo': source.repo_name,
            'source_ref': source.sha1,
            'source_artifacts': [],
            'dependencies': []
        }
        for dep in source.dependencies:
            s_dict['dependencies'].append(dep.basename())
        for sa in source.artifacts:
            s_dict['source_artifacts'].append(sa)
        return s_dict

    def encode_artifact(a):
        if artifact.source.morphology['kind'] == 'system': # pragma: no cover
            arch = artifact.source.morphology['arch']
        else:
            arch = artifact.arch

        a_dict = {
            'arch': arch,
            'cache_key': a.source.cache_key,
            'name': a.name,
            'repo': repo,
            'ref': ref,
        }
        return a_dict

    def encode_artifact_reference(a): # pragma: no cover
        a_dict = {
            'arch': a.arch,
            'cache_key': a.cache_key,
            'name': a.name,
            'repo': a.repo,
            'ref': a.ref
        }
        s_dict = {
            'filename': a.filename,
            'kind': a.kind,
            'source_repo': a.source_repo,
            'source_ref': a.source_ref,
            'source_artifacts': [],
            'dependencies': []
        }
        for dep in a.dependencies:
            s_dict['dependencies'].append(dep.basename())
        for sa in a.source_artifacts:
            s_dict['source_artifacts'].append(sa)
        return a_dict, s_dict

    encoded_artifacts = {}
    encoded_sources = {}

    if isinstance(artifact, ArtifactReference): # pragma: no cover
        root_filename = artifact.root_filename
        a_dict, s_dict = encode_artifact_reference(artifact)
        encoded_artifacts[artifact.basename()] = a_dict
        encoded_sources[artifact.cache_key] = s_dict
    else:
        root_filename = artifact.source.filename
        for a in artifact.walk():
            if a.basename() not in encoded_artifacts: # pragma: no cover
                encoded_artifacts[a.basename()] = encode_artifact(a)
                encoded_sources[a.source.cache_key] = encode_source(a.source)

    content = {
        'root-artifact': artifact.basename(),
        'root-filename': root_filename,
        'artifacts': encoded_artifacts,
        'sources': encoded_sources
    }

    return json.dumps(yaml.dump(content))


def deserialise_artifact(encoded):
    '''Re-construct the Artifact object (and dependencies).
    
    The argument should be a string returned by ``serialise_artifact``.
    The reconstructed Artifact objects will be sufficiently like the
    originals that they can be used as a build graph, and other such
    purposes, by Morph.
    
    '''
    content = yaml.load(json.loads(encoded))
    root = content['root-artifact']
    encoded_artifacts = content['artifacts']
    encoded_sources = content['sources']

    artifacts = {}

    # decode artifacts
    for basename, artifact_dict in encoded_artifacts.iteritems():
        artifact_dict.update(encoded_sources[artifact_dict['cache_key']])
        artifact = ArtifactReference(basename, artifact_dict)
        artifact.root_filename = content['root-filename']
        artifacts[basename] = artifact

    # add dependencies
    for basename, a_dict in encoded_artifacts.iteritems():
        artifact = artifacts[basename]
        artifact.dependencies = [artifacts.get(dep)
                                 for dep in artifact.dependencies]

    return artifacts[root]
