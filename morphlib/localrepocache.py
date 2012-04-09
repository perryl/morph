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


import logging
import os
import urllib
import urlparse

import morphlib


# urlparse.urljoin needs to know details of the URL scheme being used.
# It does not know about git:// by default, so we teach it here.
gitscheme=['git']
urlparse.uses_relative.extend(gitscheme)
urlparse.uses_netloc.extend(gitscheme)
urlparse.uses_params.extend(gitscheme)
urlparse.uses_query.extend(gitscheme)
urlparse.uses_fragment.extend(gitscheme)



class CachedRepoPlaceholder(object):

    '''A placeholder until the real CachedRepo exists.'''
    
    def __init__(self, url, dirname):
        pass


class NoRemote(Exception):

    def __init__(self, reponame):
        self.reponame = reponame
    
    def __str__(self):
        return 'Cannot find remote git repository: %s' % self.reponame


class LocalRepoCache(object):

    '''Manage locally cached git repositories.
    
    When we build stuff, we need a local copy of the git repository.
    To avoid having to clone the repositories for every build, we
    maintain a local cache of the repositories: we first clone the
    remote repository to the cache, and then make a local clone from
    the cache to the build environment. This class manages the local
    cached repositories.
    
    Repositories may be specified either using a full URL, in a form
    understood by git(1), or as a repository name to which a base url
    is prepended. The base urls are given to the class when it is
    created.
    
    '''
    
    def __init__(self, cachedir, baseurls):
        self._cachedir = cachedir
        self._baseurls = baseurls
        self._ex = morphlib.execute.Execute(cachedir, logging.debug)

    def _exists(self, filename): # pragma: no cover
        '''Does a file exist?
        
        This is a wrapper around os.path.exists, so that unit tests may
        override it.
        
        '''
        
        return os.path.exists(filename)
    
    def _git(self, args): # pragma: no cover
        '''Execute git command.
        
        This is a method of its own so that unit tests can easily override
        all use of the external git command.
        
        '''
        
        self._ex.runv(['git'] + args)

    def _escape(self, url):
        '''Escape a URL so it can be used as a basename in a file.'''
        return urllib.quote(url, safe='')

    def _cache_name(self, url):
        basename = self._escape(url)
        path = os.path.join(self._cachedir, basename)
        return path
    
    def _base_iterate(self, reponame):
        for baseurl in self._baseurls:
            repourl = urlparse.urljoin(baseurl, reponame)
            path = self._cache_name(repourl)
            yield repourl, path
    
    def has_repo(self, reponame):
        '''Have we already got a cache of a given repo?'''
        for repourl, path in self._base_iterate(reponame):
            if self._exists(path):
                return True
        return False

    def cache_repo(self, reponame):
        '''Clone the given repo into the cache.
        
        If the repo is already clone, do nothing.
        
        '''
        
        for repourl, path in self._base_iterate(reponame):
            if self._exists(path):
                break
            try:
                self._git(['clone', reponame, path])
            except morphlib.execute.CommandFailure:
                pass
            else:
                break
        else:
            raise NoRemote(reponame)

    def get_repo(self, reponame):
        '''Return an object representing a cached repository.'''

        for repourl, path in self._base_iterate(reponame):
            if self._exists(path):
                return CachedRepoPlaceholder(repourl, path)
        raise Exception('Repository %s is not cached yet' % reponame)

