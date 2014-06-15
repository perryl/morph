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


import logging
import re


class RepoAlias(object):

    def __init__(self, alias, prefix, pullpat, pushpat):
        self.alias = alias
        self.prefix = prefix
        self.pullpat = pullpat
        self.pushpat = pushpat

    def _pattern_to_regex(self, pattern):
        if '%s' in pattern:
            return r'(?P<path>.+)'.join(map(re.escape, pattern.split('%s')))
        else:
            return re.escape(pattern) + r'(?P<path>.+)'

    def match_url(self,  url):
        '''Given a URL, return what its alias would be if it matches'''
        for pat in (self.pullpat, self.pushpat):
            m = re.match(self._pattern_to_regex(pat), url)
            if m:
                return '%s:%s' % (self.prefix, m.group('path'))
        return None

class RepoAliasResolver(object):

    def __init__(self, aliases):
        self.aliases = {}

        alias_pattern = (r'^(?P<prefix>[a-z][a-z0-9-]+)'
                         r'=(?P<pullpat>[^#]+)#(?P<pushpat>[^#]+)$')
        for alias in aliases:
            m = re.match(alias_pattern, alias)
            if not m:
                logging.warning('Alias %s is malformed' % alias)
                continue
            prefix = m.group('prefix')
            self.aliases[prefix] = RepoAlias(alias, prefix, m.group('pullpat'),
                                             m.group('pushpat'))


    def pull_url(self, reponame):
        '''Expand a possibly shortened repo name to a pull url.'''
        return self._expand_reponame(reponame, 'pullpat')

    def push_url(self, reponame):
        '''Expand a possibly shortened repo name to a push url.'''
        return self._expand_reponame(reponame, 'pushpat')

    def aliases_from_url(self, url):
        '''Find aliases the url could have expanded from.

           Returns an ascii-betically sorted list.
        '''
        potential_matches = (repo_alias.match_url(url)
                             for repo_alias in self.aliases.itervalues())
        known_aliases = (url_alias for url_alias in potential_matches
                         if url_alias is not None)
        return sorted(known_aliases)

    def _expand_reponame(self, reponame, patname):
        prefix, suffix = self._split_reponame(reponame)

        # There was no prefix.
        if prefix is None:
            result = reponame
        elif prefix not in self.aliases:
            # Unknown prefix. Which means it may be a real URL instead.
            # Let the caller deal with it.
            result = reponame
        else:
            pat = getattr(self.aliases[prefix], patname)
            result = self._apply_url_pattern(pat, suffix)

        return result

    def _split_reponame(self, reponame):
        '''Split reponame into prefix and suffix.

        The prefix is returned as None if there was no prefix.

        '''

        pat = r'^(?P<prefix>[a-z][a-z0-9-]+):(?P<rest>.*)$'
        m = re.match(pat, reponame)
        if m:
            return m.group('prefix'), m.group('rest')
        else:
            return None, reponame

    def _apply_url_pattern(self, pattern, shortname):
        if '%s' in pattern:
            return shortname.join(pattern.split('%s'))
        else:
            return pattern + shortname
