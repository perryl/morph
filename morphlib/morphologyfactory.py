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

    def __init__(self, local_repo_cache, remote_repo_cache=None,
                 status_cb=None):
        self._lrc = local_repo_cache
        self._rrc = remote_repo_cache

        null_status_function = lambda **kwargs: None
        self.status = status_cb or null_status_function

    def get_morphology(self, reponame, sha1, filename):
        morph_name = os.path.splitext(os.path.basename(filename))[0]
        loader = morphlib.morphloader.MorphologyLoader()
        if self._lrc.has_repo(reponame):
            self.status(msg="Looking for %s in local repo cache" % filename,
                        chatty=True)
            try:
                repo = self._lrc.get_repo(reponame)
                text = repo.read_file(filename, sha1)
                morph = loader.load_from_string(text)
            except IOError:
                morph = None
                file_list = repo.list_files(ref=sha1, recurse=False)
        elif self._rrc is not None:
            self.status(msg="Retrieving %(reponame)s %(sha1)s %(filename)s"
                        " from the remote git cache.",
                        reponame=reponame, sha1=sha1, filename=filename,
                        chatty=True)
            try:
                text = self._rrc.cat_file(reponame, sha1, filename)
                morph = loader.load_from_string(text)
            except morphlib.remoterepocache.CatFileError:
                morph = None
                file_list = self._rrc.ls_tree(reponame, sha1)
        else:
            raise NotcachedError(reponame)

        if morph is None:
            self.status(msg="File %s doesn't exist: attempting to infer "
                            "chunk morph from repo's build system"
                        % filename, chatty=True)
            bs = morphlib.buildsystem.detect_build_system(file_list)
            if bs is None:
                raise MorphologyNotFoundError(filename)
            morph = bs.get_morphology(morph_name)
            loader.validate(morph)
            loader.set_commands(morph)
            loader.set_defaults(morph)
        return morph
