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


import os

import morphlib
import cliapp


class MorphologyFactoryError(cliapp.AppException):
    pass


class MorphologyNotFoundError(MorphologyFactoryError):
    def __init__(self, filename):
        MorphologyFactoryError.__init__(
            self, "Couldn't find morphology: %s" % filename)


class NotcachedError(MorphologyFactoryError):
    def __init__(self, repo_name):
        MorphologyFactoryError.__init__(
            self, "Repository %s is not cached locally and there is no "
                  "remote cache specified" % repo_name)


class StratumError(MorphologyFactoryError):
    pass


class NoChunkBuildDependsError(StratumError):
    def __init__(self, stratum, chunk):
        StratumError.__init__(
            self, 'No build dependencies in stratum %s for chunk %s '
                  '(build-depends is a mandatory field)' % (stratum, chunk))


class EmptyStratumError(StratumError):

    def __init__(self, stratum):
        cliapp.AppException.__init__(self,
            "Stratum %s is empty (has no dependencies)" % stratum)


class NoStratumBuildDependsError(StratumError):
    def __init__(self, stratum):
        StratumError.__init__(
            self, 'Stratum %s has no build-dependencies listed '
                  'and has no bootstrap chunks.' % stratum)


class MorphologyFactory(object):

    '''A way of creating morphologies which will provide a default'''

    def __init__(self, local_repo_cache, remote_repo_cache=None, app=None):
        self._lrc = local_repo_cache
        self._rrc = remote_repo_cache
        self._app = app

    def status(self, *args, **kwargs):  # pragma: no cover
        if self._app is not None:
            self._app.status(*args, **kwargs)

    def _get_morphology_text(self, reponame, sha1, filename):
        morph_name = os.path.splitext(os.path.basename(filename))[0]
        if self._lrc.has_repo(reponame):
            self.status(msg="Looking for %s in local repo cache" % filename,
                        chatty=True)
            try:
                repo = self._lrc.get_repo(reponame)
                text = repo.cat(sha1, filename)
            except IOError:
                text = None
                file_list = repo.ls_tree(sha1)
        elif self._rrc is not None:
            self.status(msg="Retrieving %(reponame)s %(sha1)s %(filename)s"
                        " from the remote artifact cache.",
                        reponame=reponame, sha1=sha1, filename=filename,
                        chatty=True)
            try:
                text = self._rrc.cat_file(reponame, sha1, filename)
            except morphlib.remoterepocache.CatFileError:
                text = None
                file_list = self._rrc.ls_tree(reponame, sha1)
        else:
            raise NotcachedError(reponame)

        if text is None:
            self.status(msg="File %s doesn't exist: attempting to infer "
                            "chunk morph from repo's build system"
                        % filename, chatty=True)
            bs = morphlib.buildsystem.detect_build_system(file_list)
            if bs is None:
                raise MorphologyNotFoundError(filename)
            text = bs.get_morphology_text(morph_name)
        return morph_name, text

    def get_morphology(self, reponame, sha1, filename):
        morph_name, text = self._get_morphology_text(reponame, sha1, filename)

        try:
            morphology = morphlib.morph2.Morphology(text)
        except morphlib.YAMLError as e: # pragma: no cover
            raise morphlib.Error("Error parsing %s: %s" %
                                 (filename, str(e)))

        if morph_name != morphology['name']:
            raise morphlib.Error(
                "Name %s does not match basename of morphology file %s" %
                (morphology['name'], filename))

        method_name = '_check_and_tweak_%s' % morphology['kind']
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            method(morphology, reponame, sha1, filename)

        return morphology

    def _check_and_tweak_system(self, morphology, reponame, sha1, filename):
        '''Check and tweak a system morphology.'''

        if morphology['arch'] is None:  # pragma: no cover
            raise morphlib.Error('No arch specified in system %s '
                                 '(arch is a mandatory field)' %
                                 filename)

        if morphology['arch'] == 'armv7':
            morphology._dict['arch'] = 'armv7l'

        if morphology['arch'] not in morphlib.valid_archs:
            raise morphlib.Error('Unknown arch %s. This version of Morph '
                                 'supports the following architectures: %s' %
                                 (morphology['arch'],
                                  ', '.join(morphlib.valid_archs)))

        name = morphology['name']
        morphology.builds_artifacts = [name + '-rootfs']

        morphology.needs_artifact_metadata_cached = False

        morphlib.morphloader.MorphologyLoader._validate_stratum_specs_fields(
            morphology, 'strata')
        morphlib.morphloader.MorphologyLoader._set_stratum_specs_defaults(
            morphology, 'strata')

    def _check_and_tweak_stratum(self, morphology, reponame, sha1, filename):
        '''Check and tweak a stratum morphology.'''

        if len(morphology['chunks']) == 0:
            raise EmptyStratumError(morphology['name'])

        for source in morphology['chunks']:
            if source.get('build-depends', None) is None:
                name = source.get('name', source.get('repo', 'unknown'))
                raise NoChunkBuildDependsError(filename, name)

        if (len(morphology['build-depends'] or []) == 0 and
            not any(c.get('build-mode') in ('bootstrap', 'test')
                    for c in morphology['chunks'])):
            raise NoStratumBuildDependsError(filename)

        morphology.builds_artifacts = [morphology['name']]
        morphology.needs_artifact_metadata_cached = True

        morphlib.morphloader.MorphologyLoader._validate_stratum_specs_fields(
            morphology, 'build-depends')
        morphlib.morphloader.MorphologyLoader._set_stratum_specs_defaults(
            morphology, 'build-depends')

    def _check_and_tweak_chunk(self, morphology, reponame, sha1, filename):
        '''Check and tweak a chunk morphology.'''

        if 'products' in morphology and len(morphology['products']) > 1:
            morphology.builds_artifacts = [d['artifact']
                                           for d in morphology['products']]
        else:
            morphology.builds_artifacts = [morphology['name']]

        morphology.needs_artifact_metadata_cached = False

        morphlib.morphloader.MorphologyLoader._validate_chunk(morphology)
