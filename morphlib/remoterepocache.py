# Copyright (C) 2012  Codethink Limited
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
import urllib2
import urlparse


class ResolveRefError(cliapp.AppException):

    def __init__(self, repo_name, ref):
        cliapp.AppException.__init__(
            self, 'Failed to resolve ref %s for repo %s' %
            (ref, repo_name))


class ResolveRefsError(cliapp.AppException):

    def __init__(self, tuples):
        cliapp.AppException.__init__(
                self, 'Failed to resolve refs: %s' % tuples)


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
        except:
            raise ResolveRefError(repo_name, ref)

    def resolve_refs(self, tuples):
        pull_urls = [self._resolver.pull_url(repo) for repo, ref in tuples]
        try:
            return self._resolve_refs_for_repo_urls(tuples, pull_urls)
        except:
            raise ResolveRefsError(tuples)

    def cat_file(self, repo_name, ref, filename):
        repo_url = self._resolver.pull_url(repo_name)
        try:
            return self._cat_file_for_repo_url(repo_url, ref, filename)
        except:
            raise CatFileError(repo_name, ref, filename)

    def ls_tree(self, repo_name, ref):
        repo_url = self._resolver.pull_url(repo_name)
        try:
            info = json.loads(self._ls_tree_for_repo_url(repo_url, ref))
            return info['tree'].keys()
        except:
            raise LsTreeError(repo_name, ref)

    def _resolve_ref_for_repo_url(self, repo_url, ref):  # pragma: no cover
        data = self._make_request('sha1s?repo=%s&ref=%s' % (repo_url, ref))
        info = json.loads(data)
        return info['sha1'], info['tree']

    def _resolve_refs_for_repo_urls(self, tuples, urls): # pragma: no cover
        request_data = []
        for n in xrange(0, len(tuples)):
            request_data.append({'repo': urls[n], 'ref': tuples[n][1]})
        request_data = json.dumps(request_data)
        response_data = self._make_post_request('sha1s', request_data)
        response_data = json.loads(response_data)
        data = {}
        for n in xrange(0, len(tuples)):
            data[tuples[n]] = {
                'repo': tuples[n][0],
                'repo-url': response_data[n]['repo'],
                'ref': response_data[n]['ref'],
            }
            if 'error' in response_data[n]:
                data[tuples[n]]['error'] = response_data[n]['error']
            else:
                data[tuples[n]]['sha1'] = response_data[n]['sha1']
                data[tuples[n]]['tree'] = response_data[n]['tree']
        return data

    def _cat_file_for_repo_url(self, repo_url, ref,
                               filename):  # pragma: no cover
        return self._make_request(
            'files?repo=%s&ref=%s&filename=%s' % (repo_url, ref, filename))

    def _ls_tree_for_repo_url(self, repo_url, ref):  # pragma: no cover
        return self._make_request('trees?repo=%s&ref=%s' % (repo_url, ref))

    def _make_request(self, path):  # pragma: no cover
        server_url = self.server_url
        if not server_url.endswith('/'):
            server_url += '/'
        url = urlparse.urljoin(server_url, '/1.0/%s' % path)
        handle = urllib2.urlopen(url)
        return handle.read()

    def _make_post_request(self, path, data): # pragma: no cover
        server_url = self.server_url
        if not server_url.endswith('/'):
            server_url += '/'
        url = urlparse.urljoin(server_url, '/1.0/%s' % path)
        request = urllib2.Request(
                url, data, {'Content-Type': 'application/json'})
        handle = urllib2.urlopen(request, data)
        return handle.read()
