# Copyright (C) 2012-2013  Codethink Limited
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
import json
import logging
import urllib2
import urlparse
import urllib


class ResolveRefError(cliapp.AppException):

    def __init__(self, repo_name, ref):
        cliapp.AppException.__init__(
            self, 'Failed to resolve ref %s for repo %s' %
            (ref, repo_name))


class CatFileError(cliapp.AppException):

    def __init__(self, repo_name, ref, filename):
        cliapp.AppException.__init__(
            self, 'Failed to cat file %s in ref %s of repo %s' %
            (filename, ref, repo_name))

class LsTreeError(cliapp.AppException):

    def __init__(self, repo_name, ref):
        cliapp.AppException.__init__(
            self, 'Failed to list tree in ref %s of repo %s' %
            (ref, repo_name))


class RemoteRepoCache(object):

    def __init__(self, server_url, resolver):
        self.server_url = server_url
        self._resolver = resolver

    def resolve_ref(self, repo_name, ref):
        repo_url = self._resolver.pull_url(repo_name)
        try:
            return self._resolve_ref_for_repo_url(repo_url, ref)
        except urllib2.URLError, e:
            logging.error('Caught exception: %s' % str(e))
            raise ResolveRefError(repo_name, ref)

    def resolve_ref_batch(self, references):
        if len(references) == 0:
            return
        request = []
        for repo_name, ref in references:
            repo_url = self._resolver.pull_url(repo_name)
            request.append(
                dict(repo=repo_url, ref=ref))
        result = self._make_request(
            'sha1s', json_post_data=json.dumps(request))
        return json.loads(result)

    def cat_file(self, repo_name, ref, filename):
        repo_url = self._resolver.pull_url(repo_name)
        try:
            return self._cat_file_for_repo_url(repo_url, ref, filename)
        except BaseException, e:
            logging.error('Caught exception: %s' % str(e))
            raise CatFileError(repo_name, ref, filename)

    def ls_tree(self, repo_name, ref):
        repo_url = self._resolver.pull_url(repo_name)
        try:
            info = json.loads(self._ls_tree_for_repo_url(repo_url, ref))
            return info['tree'].keys()
        except BaseException, e:
            logging.error('Caught exception: %s' % str(e))
            raise LsTreeError(repo_name, ref)

    def cat_file_multiple(self, triplets):
        if len(triplets) == 0:
            return
        request = []
        for repo_name, ref, filename in triplets:
            repo_url = self._resolver.pull_url(repo_name)
            request.append(
                dict(repo=repo_url, ref=ref, filename=filename))
        result = self._make_request(
            'files', json_post_data=json.dumps(request))
        return json.loads(result)

    def _resolve_ref_for_repo_url(self, repo_url, ref):  # pragma: no cover
        data = self._make_request(
            'sha1s?repo=%s&ref=%s' % self._quote_strings(repo_url, ref))
        info = json.loads(data)
        return info['sha1'], info['tree']

    def _cat_file_for_repo_url(self, repo_url, ref,
                               filename):  # pragma: no cover
        return self._make_request(
            'files?repo=%s&ref=%s&filename=%s'
            % self._quote_strings(repo_url, ref, filename))

    def _ls_tree_for_repo_url(self, repo_url, ref):  # pragma: no cover
        return self._make_request(
            'trees?repo=%s&ref=%s' % self._quote_strings(repo_url, ref))

    def _quote_strings(self, *args):  # pragma: no cover
        return tuple(urllib.quote(string) for string in args)

    def _make_request(self, path, json_post_data=None):  # pragma: no cover
        server_url = self.server_url
        if not server_url.endswith('/'):
            server_url += '/'
        url = urlparse.urljoin(server_url, '/1.0/%s' % path)
        if json_post_data is None:
            headers = {}
        else:
            headers = {'Content-type': 'application/json'}
        request = urllib2.Request(url, data=json_post_data, headers=headers)
        handle = urllib2.urlopen(request)
        return handle.read()
