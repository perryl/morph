# Copyright (C) 2011-2016  Codethink Limited
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
# with this program.  If not, see <http://www.gnu.org/licenses/>.


import cliapp
import ConfigParser
import logging
import os
import re
import string
import StringIO
import sys

import morphlib


class NoModulesFileError(cliapp.AppException):

    def __init__(self, repo, ref):
        Exception.__init__(self,
                           '%s:%s has no .gitmodules file.' % (repo, ref))


class Submodule(object):

    def __init__(self, name, url, sha1, path):
        self.name = name
        self.url = url
        self.commit = sha1
        self.path = path

    def __str__(self):
        return "{name}|{url}|{path}".format(name=self.name,
                                            url=self.url,
                                            path=self.path)


class InvalidSectionError(cliapp.AppException):

    def __init__(self, repo, ref, section):
        Exception.__init__(self,
                           '%s:%s:.gitmodules: Found a misformatted section '
                           'title: [%s]' % (repo, ref, section))


class Submodules(object):

    def __init__(self, repo, ref, runcmd_cb=cliapp.runcmd):
        self.repo = repo
        self.ref = ref
        self.submodules = []

        self.runcmd_cb = runcmd_cb

    def load(self):
        content = self._read_gitmodules_file()

        io = StringIO.StringIO(content)
        parser = ConfigParser.RawConfigParser()
        parser.readfp(io)

        self._validate_and_read_entries(parser)

    def _read_gitmodules_file(self):
        try:
            # try to read the .gitmodules file from the repo/ref
            content = gitcmd(self.runcmd_cb, 'cat-file', 'blob',
                             '%s:.gitmodules' % self.ref, cwd=self.repo,
                             ignore_fail=True)

            # drop indentation in sections, as RawConfigParser cannot handle it
            return '\n'.join([line.strip() for line in content.splitlines()])
        except cliapp.AppException:
            raise NoModulesFileError(self.repo, self.ref)

    def _validate_and_read_entries(self, parser):
        gd = morphlib.gitdir.GitDirectory(self.repo)
        for section in parser.sections():
            # validate section name against the 'section "foo"' pattern
            section_pattern = r'submodule "(.*)"'
            if re.match(section_pattern, section):
                # parse the submodule name, URL and path
                name = re.sub(section_pattern, r'\1', section)
                url = parser.get(section, 'url')
                path = parser.get(section, 'path')
                try:
                    sha1 = gd.get_submodule_commit(self.ref, path)
                except morphlib.gitdir.MissingSubmoduleCommitError:
                    # Ignore submodules listed in .gitmodules file that are
                    # not pointing to a git commit object. If you try to clone
                    # a repo with submodules without a commit object (using
                    # Git), nothing will happen, and Git will not even complain
                    continue

                # create a submodule object
                submodule = Submodule(name, url, sha1, path)
                self.submodules.append(submodule)
            else:
                raise InvalidSectionError(self.repo, self.ref, section)

    def __iter__(self):
        for submodule in self.submodules:
            yield submodule

    def __len__(self):
        return len(self.submodules)


def update_submodules(app, repo_dir):  # pragma: no cover
    '''Set up repo submodules, rewriting the URLs to expand prefixes

    We do this automatically rather than leaving it to the user so that they
    don't have to worry about the prefixed URLs manually.
    '''

    if os.path.exists(os.path.join(repo_dir, '.gitmodules')):
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            app.settings['repo-alias'])
        gitcmd(app.runcmd, 'submodule', 'init', cwd=repo_dir)
        submodules = Submodules(app, repo_dir, 'HEAD')
        submodules.load()
        for submodule in submodules:
            gitcmd(app.runcmd, 'config', 'submodule.%s.url' % submodule.name,
                   resolver.pull_url(submodule.url), cwd=repo_dir)
        gitcmd(app.runcmd, 'submodule', 'update', cwd=repo_dir)


class ConfigNotSetException(cliapp.AppException):

    def __init__(self, missing, defaults):
        self.missing = missing
        self.defaults = defaults
        if len(missing) == 1:
            self.preamble = ('Git configuration for %s has not been set. '
                             'Please set it with:' % missing[0])
        else:
            self.preamble = ('Git configuration for keys %s and %s '
                             'have not been set. Please set them with:'
                             % (', '.join(missing[:-1]), missing[-1]))

    def __str__(self):
        lines = [self.preamble]
        lines.extend('git config --global %s \'%s\'' % (k, self.defaults[k])
                     for k in self.missing)
        return '\n    '.join(lines)


class IdentityNotSetException(ConfigNotSetException):

    preamble = 'Git user info incomplete. Please set your identity, using:'

    def __init__(self, missing):
        self.defaults = {"user.name": "My Name",
                         "user.email": "me@example.com"}
        self.missing = missing


def get_user_name(runcmd):
    '''Get user.name configuration setting. Complain if none was found.'''
    if 'GIT_AUTHOR_NAME' in os.environ:
        return os.environ['GIT_AUTHOR_NAME'].strip()
    try:
        config = check_config_set(runcmd, keys={"user.name": "My Name"})
        return config['user.name']
    except ConfigNotSetException as e:
        raise IdentityNotSetException(e.missing)


def get_user_email(runcmd):
    '''Get user.email configuration setting. Complain if none was found.'''
    if 'GIT_AUTHOR_EMAIL' in os.environ:
        return os.environ['GIT_AUTHOR_EMAIL'].strip()
    try:
        cfg = check_config_set(runcmd, keys={"user.email": "me@example.com"})
        return cfg['user.email']
    except ConfigNotSetException as e:
        raise IdentityNotSetException(e.missing)

def check_config_set(runcmd, keys, cwd='.'):
    ''' Check whether the given keys have values in git config. '''
    missing = []
    found = {}
    for key in keys:
        try:
            value = gitcmd(runcmd, 'config', key, cwd=cwd, 
                           print_command=False).strip()
            found[key] = value
        except cliapp.AppException:
            missing.append(key)
    if missing:
        raise ConfigNotSetException(missing, keys)
    return found


def copy_repository(runcmd, repo, destdir, is_mirror=True):
    '''Copies a cached repository into a directory using cp.

    This also fixes up the repository afterwards, so that it can contain
    code etc.  It does not leave any given branch ready for use.

    This is slightly faster than `git clone` for large repositories,
    as of Git 2.3.0. Long term, we should fix `git clone` to be as fast
    as possible, and use that.

    '''
    if is_mirror == False:
        runcmd(['cp', '-a', os.path.join(repo, '.git'),
                os.path.join(destdir, '.git')])
        return

    runcmd(['cp', '-a', repo, os.path.join(destdir, '.git')])
    runcmd(['chown', '-R', '%s:%s' % (os.getuid(), os.getgid()), destdir])
    # core.bare should be false so that git believes work trees are possible
    gitcmd(runcmd, 'config', 'core.bare', 'false', cwd=destdir)
    # we do not want the origin remote to behave as a mirror for pulls
    gitcmd(runcmd, 'config', '--unset', 'remote.origin.mirror', cwd=destdir)
    # we want a traditional refs/heads -> refs/remotes/origin ref mapping
    gitcmd(runcmd, 'config', 'remote.origin.fetch',
           '+refs/heads/*:refs/remotes/origin/*', cwd=destdir)
    # set the origin url to the cached repo so that we can quickly clean up
    gitcmd(runcmd, 'config', 'remote.origin.url', repo, cwd=destdir)
    # by packing the refs, we can then edit then en-masse easily
    gitcmd(runcmd, 'pack-refs', '--all', '--prune', cwd=destdir)
    # turn refs/heads/* into refs/remotes/origin/* in the packed refs
    # so that the new copy behaves more like a traditional clone.
    logging.debug("Adjusting packed refs for %s" % destdir)
    with open(os.path.join(destdir, ".git", "packed-refs"), "r") as ref_fh:
        pack_lines = ref_fh.read().split("\n")
    with open(os.path.join(destdir, ".git", "packed-refs"), "w") as ref_fh:
        ref_fh.write(pack_lines.pop(0) + "\n")
        for refline in pack_lines:
            if ' refs/remotes/' in refline:
                continue
            if ' refs/heads/' in refline:
                sha, ref = refline[:40], refline[41:]
                if ref.startswith("refs/heads/"):
                    ref = "refs/remotes/origin/" + ref[11:]
                refline = "%s %s" % (sha, ref)
            ref_fh.write("%s\n" % (refline))
    # Finally run a remote update to clear up the refs ready for use.
    gitcmd(runcmd, 'remote', 'update', 'origin', '--prune', cwd=destdir)


def reset_workdir(runcmd, gitdir):
    '''Removes any differences between the current commit '''
    '''and the status of the working directory'''
    gitcmd(runcmd, 'clean', '-fxd', cwd=gitdir)
    gitcmd(runcmd, 'reset', '--hard', 'HEAD', cwd=gitdir)


def is_valid_sha1(ref):
    '''Checks whether a string is a valid SHA1.'''

    return len(ref) == 40 and all(x in string.hexdigits for x in ref)


def gitcmd(runcmd, *args, **kwargs):
    '''Run git commands safely'''
    if 'env' not in kwargs:
        kwargs['env'] = dict(os.environ)
    # git replace means we can't trust that just the sha1 of the branch
    # is enough to say what it contains, so we turn it off by setting
    # the right flag in an environment variable.
    kwargs['env']['GIT_NO_REPLACE_OBJECTS'] = '1'

    cmdline = ['git']

    echo_stderr = kwargs.pop('echo_stderr', False)
    if echo_stderr:
        if 'stderr' not in kwargs:
            # Ensure status output is visible. Git will hide it if stderr is
            # redirected somewhere else (the --progress flag overrides this
            # behaviour for the 'clone' command, but not others).
            kwargs['stderr'] = sys.stderr

    cmdline.extend(args)
    return runcmd(cmdline, **kwargs)
