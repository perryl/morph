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
                        " from the remote git cache.",
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

        loader = morphlib.morphloader.MorphologyLoader()
        morphology = loader.load_from_string(text)

        method_name = '_check_and_tweak_%s' % morphology['kind']
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            method(morphology, reponame, sha1, filename)

        return morphology

    def _check_and_tweak_system(self, morphology, reponame, sha1, filename):
        '''Check and tweak a system morphology.'''

        name = morphology['name']
        morphology.builds_artifacts = [name + '-rootfs']

        morphology.needs_artifact_metadata_cached = False

    def _check_and_tweak_stratum(self, morphology, reponame, sha1, filename):
        '''Check and tweak a stratum morphology.'''

        morphology.builds_artifacts = [morphology['name']]
        morphology.needs_artifact_metadata_cached = True

    def _check_and_tweak_chunk(self, morphology, reponame, sha1, filename):
        '''Check and tweak a chunk morphology.'''

        if 'products' in morphology and len(morphology['products']) > 1:
            morphology.builds_artifacts = [d['artifact']
                                           for d in morphology['products']]
        else:
            morphology.builds_artifacts = [morphology['name']]

        morphology.needs_artifact_metadata_cached = False
