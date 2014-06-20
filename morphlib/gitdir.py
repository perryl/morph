# Copyright (C) 2013-2014  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import cliapp
import itertools
import os
import re

import morphlib


class NoWorkingTreeError(cliapp.AppException):

    def __init__(self, repo):
        cliapp.AppException.__init__(
            self, 'Git directory %s has no working tree '
                  '(is bare).' % repo.dirname)


class InvalidRefError(cliapp.AppException):
    def __init__(self, repo, ref):
        cliapp.AppException.__init__(
            self, 'Git directory %s has no commit '
                  'at ref %s.' %(repo.dirname, ref))


class ExpectedSha1Error(cliapp.AppException):

    def __init__(self, ref):
        self.ref = ref
        cliapp.AppException.__init__(
            self, 'SHA1 expected, got %s' % ref)


class RefChangeError(cliapp.AppException):
    pass


class RefAddError(RefChangeError):

    def __init__(self, gd, ref, sha1, original_exception):
        self.gd = gd
        self.dirname = dirname = gd.dirname
        self.ref = ref
        self.sha1 = sha1
        self.original_exception = original_exception
        RefChangeError.__init__(self, 'Adding ref %(ref)s '\
            'with commit %(sha1)s failed in git repository '\
            'located at %(dirname)s: %(original_exception)r' % locals())


class RefUpdateError(RefChangeError):

    def __init__(self, gd, ref, old_sha1, new_sha1, original_exception):
        self.gd = gd
        self.dirname = dirname = gd.dirname
        self.ref = ref
        self.old_sha1 = old_sha1
        self.new_sha1 = new_sha1
        self.original_exception = original_exception
        RefChangeError.__init__(self, 'Updating ref %(ref)s '\
            'from %(old_sha1)s to %(new_sha1)s failed in git repository '\
            'located at %(dirname)s: %(original_exception)r' % locals())


class RefDeleteError(RefChangeError):

    def __init__(self, gd, ref, sha1, original_exception):
        self.gd = gd
        self.dirname = dirname = gd.dirname
        self.ref = ref
        self.sha1 = sha1
        self.original_exception = original_exception
        RefChangeError.__init__(self, 'Deleting ref %(ref)s '\
            'expecting commit %(sha1)s failed in git repository '\
            'located at %(dirname)s: %(original_exception)r' % locals())


class InvalidRefSpecError(cliapp.AppException):

    def __init__(self, source, target):
        self.source = source
        self.target = target
        cliapp.AppException.__init__(
            self, 'source or target must be defined, '\
                  'got %(source)r and %(target)r respectively.' % locals())


class PushError(cliapp.AppException):
    pass


class NoRefspecsError(PushError):

    def __init__(self, remote):
        self.remote = remote
        PushError.__init__(
            self, 'Push to remote "%s" was given no refspecs.' % remote)


class PushFailureError(PushError):

    def __init__(self, remote, refspecs, exit, results, stderr):
        self.remote = remote
        self.push_url = push_url = remote.get_push_url()
        self.refspecs = refspecs
        self.exit = exit
        self.results = results
        self.stderr = stderr
        PushError.__init__(self, 'Push to remote "%(remote)s", '\
                                 'push url %(push_url)s '\
                                 'failed with exit code %(exit)s' % locals())


class RefSpec(object):
    '''Class representing how to push or pull a ref.

    `source` is a reference to the local commit/tag you want to push to
    the remote.
    `target` is the ref on the remote you want to push to.
    `require` is the value that the remote is expected to currently be.
    Currently `require` is only used to provide a reverse of the respec,
    but future versions of Git will support requiring the value of
    `target` on the remote to be at a certain commit, or fail.
    `force` defaults to false, and if set adds the flag to push even if
    it's non-fast-forward.

    If `source` is not provided, but `target` is, then the refspec will
    delete `target` on the remote.
    If `source` is provided, but `target` is not, then `source` is used
    as the `target`, since if you specify a ref for the `source`, you
    can push the same local branch to the same remote branch.

    '''

    def __init__(self, source=None, target=None, require=None, force=False):
        if source is None and target is None:
            raise InvalidRefSpecError(source, target)
        self.source = source
        self.target = target
        self.require = require
        self.force = force
        if target is None:
            # Default to source if target not given, source must be a
            # branch name, or when this refspec is pushed it will fail.
            self.target = target = source
        if source is None: # Delete if source not given
            self.source = source = '0' * 40

    @property
    def push_args(self):
        '''Arguments to pass to push to push this ref.

        Returns an iterable of the arguments that would need to be added
        to a push command to push this ref spec.

        This currently returns a single-element tuple, but it may expand
        to multiple arguments, e.g.
        1.  tags expand to `tag "$name"`
        2.  : expands to all the matching refs
        3.  When Git 1.8.5 becomes available,
            `"--force-with-lease=$target:$required"  "$source:$target"`.

        '''

        # TODO: Use require parameter when Git 1.8.5 is available,
        #       to allow the push to fail if the target ref is not at
        #       that commit by using the --force-with-lease option.
        return ('%(force)s%(source)s:%(target)s' % {
            'force': '+' if self.force else '',
            'source': self.source,
            'target': self.target
        }),

    def revert(self):
        '''Create a respec which will undo the effect of pushing this one.

        If `require` was not specified, the revert refspec will delete
        the branch.

        '''

        return self.__class__(source=(self.require or '0' * 40),
                              target=self.target, require=self.source,
                              force=self.force)


PUSH_FORMAT = re.compile(r'''
# Match flag, this is the eventual result in a nutshell
(?P<flag>[- +*=!])\t
# The refspec is colon separated and separated from the rest by another tab.
(?P<from>[^:]*):(?P<to>[^\t]*)\t
# Two possible formats remain, so separate the two with a capture group
(?:
    # Summary is an arbitrary string, separated from the reason by a space
    (?P<summary>.*)[ ]
    # Reason is enclosed in parenthesis and ends the line
    \((?P<reason>.*)\)
    # The reason is optional, so we may instead only have the summary
    |  (?P<summary_only>.*)
)
''', re.VERBOSE)


class Remote(object):
    '''Represent a remote git repository.

    This can either be nascent or concrete, depending on whether the
    name is given.

    Changes to a concrete remote's config are written-through to git's
    config files, while a nascent remote keeps changes in-memory.

    '''

    def __init__(self, gd, name=None):
        self.gd = gd
        self.name = name
        self.push_url = None
        self.fetch_url = None

    def __str__(self):
        return self.name or '(nascent remote)'

    def set_fetch_url(self, url):
        self.fetch_url = url
        if self.name is not None:
            self.gd._runcmd(['git', 'remote', 'set-url', self.name, url])

    def set_push_url(self, url):
        self.push_url = url
        if self.name is not None:
            self.gd._runcmd(['git', 'remote', 'set-url', '--push',
                             self.name, url])

    def _get_remote_url(self, remote_name, kind):
        # As distasteful as it is to parse the output of porcelain
        # commands, this is the best option.
        # Git config can be used to get the raw value, but this is
        # incorrect when url.*.insteadof rules are involved.
        # Re-implementing the rewrite logic in morph is duplicated effort
        # and more work to keep it in sync.
        # It's possible to get the fetch url with `git ls-remote --get-url
        # <remote>`, but this will just print the remote's name if it
        # is not defined.
        # It is only possible to use git to get the push url by parsing
        # `git remote -v` or `git remote show -n <remote>`, and `git
        # remote -v` is easier to parse.
        output = self.gd._runcmd(['git', 'remote', '-v'])
        for line in output.splitlines():
            words = line.split()
            if (len(words) == 3 and
                words[0] == remote_name and
                words[2] == '(%s)' % kind):
                return words[1]

        return None

    def get_fetch_url(self):
        if self.name is None:
            return self.fetch_url
        return self._get_remote_url(self.name, 'fetch')

    def get_push_url(self):
        if self.name is None:
            return self.push_url or self.get_fetch_url()
        return self._get_remote_url(self.name, 'push')

    @staticmethod
    def _parse_push_output(output):
        for line in output.splitlines():
            m = PUSH_FORMAT.match(line)
            # Push may output lines that are not related to the status,
            # so ignore any that don't match the status format.
            if m is None:
                continue
            # Ensure the same number of arguments
            ret = list(m.group('flag', 'from', 'to'))
            ret.append(m.group('summary') or m.group('summary_only'))
            ret.append(m.group('reason'))
            yield tuple(ret)

    def push(self, *refspecs):
        '''Push given refspecs to the remote and return results.

        If no refspecs are given, an exception is raised.

        Returns an iterable of (flag, from_ref, to_ref, summary, reason)

        If the push fails, a PushFailureError is raised, from which the
        result can be retrieved with the `results` field.

        '''

        if not refspecs:
            raise NoRefspecsError(self)
        push_name = self.name or self.get_push_url()
        cmdline = ['git', 'push', '--porcelain', push_name]
        cmdline.extend(itertools.chain.from_iterable(
            rs.push_args for rs in refspecs))
        exit, out, err = self.gd._runcmd_unchecked(cmdline)
        if exit != 0:
            raise PushFailureError(self, refspecs, exit,
                                   self._parse_push_output(out), err)
        return self._parse_push_output(out)

    def pull(self, branch=None): # pragma: no cover
        if branch:
            repo = self.get_fetch_url()
            ret = self.gd._runcmd(['git', 'pull', repo, branch])
        else:
            ret = self.gd._runcmd(['git', 'pull'])
        return ret


class GitDirectory(object):

    '''Represent a git working tree + .git directory.

    This class represents a directory that is the result of a
    "git clone". It includes both the .git subdirectory and
    the working tree. It is a thin abstraction, meant to make
    it easier to do certain git operations.

    '''

    def __init__(self, dirname):
        self.dirname = morphlib.util.find_root(dirname, '.git')
        # if we are in a bare repo, self.dirname will now be None
        # so we just use the provided dirname
        if not self.dirname:
            self.dirname = dirname

    def _runcmd(self, argv, **kwargs):
        '''Run a command at the root of the git directory.

        See cliapp.runcmd for arguments.

        Do NOT use this from outside the class. Add more public
        methods for specific git operations instead.

        '''

        return cliapp.runcmd(argv, cwd=self.dirname, **kwargs)

    def _runcmd_unchecked(self, *args, **kwargs):
        return cliapp.runcmd_unchecked(*args, cwd=self.dirname, **kwargs)

    def checkout(self, branch_name): # pragma: no cover
        '''Check out a git branch.'''
        self._runcmd(['git', 'checkout', branch_name])
        if self.has_fat():
            self.fat_init()
            self.fat_pull()

    def branch(self, new_branch_name, base_ref): # pragma: no cover
        '''Create a git branch based on an existing ref.

        This does not automatically check out the branch.

        base_ref may be None, in which case the current branch is used.

        '''

        argv = ['git', 'branch', new_branch_name]
        if base_ref is not None:
            argv.append(base_ref)
        self._runcmd(argv)

    def is_currently_checked_out(self, ref): # pragma: no cover
        '''Is ref currently checked out?'''

        # Try the ref name directly first. If that fails, prepend origin/
        # to it. (FIXME: That's a kludge, and should be fixed.)
        try:
            parsed_ref = self._runcmd(['git', 'rev-parse', ref]).strip()
        except cliapp.AppException:
            parsed_ref = self._runcmd(
                ['git', 'rev-parse', 'origin/%s' % ref]).strip()
        parsed_head = self._runcmd(['git', 'rev-parse', 'HEAD']).strip()
        return parsed_ref == parsed_head

    def get_file_from_ref(self, ref, filename): # pragma: no cover
        '''Get file contents from git by ref and filename.

        `ref` should be a tree-ish e.g. HEAD, master, refs/heads/master,
        refs/tags/foo, though SHA1 tag, commit or tree IDs are also valid.

        `filename` is the path to the file object from the base of the
        git directory.

        Returns the contents of the referred to file as a string.

        '''

        # Blob ID is left as the git revision, rather than SHA1, since
        # we know get_blob_contents will accept it
        blob_id = '%s:%s' % (ref, filename)
        return self.get_blob_contents(blob_id)

    def get_blob_contents(self, blob_id): # pragma: no cover
        '''Get file contents from git by ID'''
        return self._runcmd(
            ['git', 'cat-file', 'blob', blob_id])

    def get_commit_contents(self, commit_id): # pragma: no cover
        '''Get commit contents from git by ID'''
        return self._runcmd(
            ['git', 'cat-file', 'commit', commit_id])

    def update_submodules(self, app): # pragma: no cover
        '''Change .gitmodules URLs, and checkout submodules.'''
        morphlib.git.update_submodules(app, self.dirname)

    def set_config(self, key, value):
        '''Set a git repository configuration variable.

        The key must have at least one period in it: foo.bar for example,
        not just foo. The part before the first period is interpreted
        by git as a section name.

        '''

        self._runcmd(['git', 'config', key, value])

    def get_config(self, key):
        '''Return value for a git repository configuration variable.'''

        value = self._runcmd(['git', 'config', '-z', key])
        return value.rstrip('\0')

    def get_remote(self, *args, **kwargs):
        '''Get a remote for this Repository.

        Gets a previously configured remote if a remote name is given.
        Otherwise a nascent one is created.

        '''
        return Remote(self, *args, **kwargs)

    def update_remotes(self): # pragma: no cover
        '''Run "git remote update --prune".'''
        self._runcmd(['git', 'remote', 'update', '--prune'])

    def is_bare(self):
        '''Determine whether the repository has no work tree (is bare)'''
        return self.get_config('core.bare') == 'true'

    def list_files(self, ref=None):
        '''Return an iterable of the files in the repository.

        If `ref` is specified, list files at that ref, otherwise
        use the working tree.

        If this is a bare repository and no ref is specified, raises
        an exception.

        '''
        if ref is None and self.is_bare():
            raise NoWorkingTreeError(self)
        if ref is None:
            return self._list_files_in_work_tree()
        else:
            return self._list_files_in_ref(ref)

    def _rev_parse(self, ref):
        try:
            return self._runcmd(['git', 'rev-parse', '--verify', ref]).strip()
        except cliapp.AppException as e:
            raise InvalidRefError(self, ref)

    def resolve_ref_to_commit(self, ref):
        return self._rev_parse('%s^{commit}' % ref)

    def resolve_ref_to_tree(self, ref):
        return self._rev_parse('%s^{tree}' % ref)

    def _list_files_in_work_tree(self):
        for dirpath, subdirs, filenames in os.walk(self.dirname):
            if dirpath == self.dirname and '.git' in subdirs:
                subdirs.remove('.git')
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                yield os.path.relpath(filepath, start=self.dirname)

    def _list_files_in_ref(self, ref):
        tree = self.resolve_ref_to_tree(ref)
        output = self._runcmd(['git', 'ls-tree', '--name-only', '-rz', tree])
        # ls-tree appends \0 instead of interspersing, so we need to
        # strip the trailing \0 before splitting
        paths = output.strip('\0').split('\0')
        return paths

    def read_file(self, filename, ref=None):
        if ref is None and self.is_bare():
            raise NoWorkingTreeError(self)
        if ref is None:
            with open(os.path.join(self.dirname, filename)) as f:
                return f.read()
        tree = self.resolve_ref_to_tree(ref)
        return self.get_file_from_ref(tree, filename)

    def is_symlink(self, filename, ref=None):
        if ref is None and self.is_bare():
            raise NoWorkingTreeError(self)
        if ref is None:
            filepath = os.path.join(self.dirname, filename.lstrip('/'))
            return os.path.islink(filepath)
        tree_entry = self._runcmd(['git', 'ls-tree', ref, filename])
        file_mode = tree_entry.split(' ', 1)[0]
        return file_mode == '120000'

    @property
    def HEAD(self):
        output = self._runcmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        return output.strip()

    def get_index(self, index_file=None):
        return morphlib.gitindex.GitIndex(self, index_file)

    def store_blob(self, blob_contents):
        '''Hash `blob_contents`, store it in git and return the sha1.

        `blob_contents` must either be a string or a value suitable to
        pass to subprocess.Popen i.e. a file descriptor or file object
        with fileno() method.

        '''
        if isinstance(blob_contents, basestring):
            kwargs = {'feed_stdin': blob_contents}
        else:
            kwargs = {'stdin': blob_contents}
        return self._runcmd(['git', 'hash-object', '-t', 'blob',
                             '-w', '--stdin'], **kwargs).strip()

    def commit_tree(self, tree, parent, message, **kwargs):
        '''Create a commit'''
        # NOTE: Will need extension for 0 or N parents.
        env = {}
        for who, info in itertools.product(('committer', 'author'),
                                           ('name', 'email')):
            argname = '%s_%s' % (who, info)
            envname = 'GIT_%s_%s' % (who.upper(), info.upper())
            if argname in kwargs:
                env[envname] = kwargs[argname]
        for who in ('committer', 'author'):
            argname = '%s_date' % who
            envname = 'GIT_%s_DATE' % who.upper()
            if argname in kwargs:
                env[envname] = kwargs[argname].isoformat()
        return self._runcmd(['git', 'commit-tree', tree,
                             '-p', parent, '-m', message],
                            env=env).strip()

    @staticmethod
    def _check_is_sha1(string):
        if not morphlib.git.is_valid_sha1(string):
            raise ExpectedSha1Error(string)

    def _update_ref(self, ref_args, message):
        args = ['git', 'update-ref']
        # No test coverage, since while this functionality is useful,
        # morph does not need an API for inspecting the reflog, so
        # it existing purely to test ref updates is a tad overkill.
        if message is not None: # pragma: no cover
            args.extend(('-m', message))
        args.extend(ref_args)
        self._runcmd(args)

    def add_ref(self, ref, sha1, message=None):
        '''Create a ref called `ref` in the repository pointing to `sha1`.

        `message` is a string to add to the reflog about this change
        `ref` must not already exist, if it does, use `update_ref`
        `sha1` must be a 40 character hexadecimal string representing
        the SHA1 of the commit or tag this ref will point to, this is
        the result of the commit_tree or resolve_ref_to_commit methods.

        '''
        self._check_is_sha1(sha1)
        # 40 '0' characters is code for no previous value
        # this ensures it will fail if the branch already exists
        try:
            return self._update_ref((ref, sha1, '0' * 40), message)
        except Exception, e:
            raise RefAddError(self, ref, sha1, e)

    def update_ref(self, ref, sha1, old_sha1, message=None):
        '''Change the commit the ref `ref` points to, to `sha1`.

        `message` is a string to add to the reflog about this change
        `sha1` and `old_sha` must be 40 character hexadecimal strings
        representing the SHA1 of the commit or tag this ref will point
        to and currently points to respectively. This is the result of
        the commit_tree or resolve_ref_to_commit methods.
        `ref` must exist, and point to `old_sha1`.
        This is to avoid unexpected results when multiple processes
        attempt to change refs.

        '''
        self._check_is_sha1(sha1)
        self._check_is_sha1(old_sha1)
        try:
            return self._update_ref((ref, sha1, old_sha1), message)
        except Exception, e:
            raise RefUpdateError(self, ref, old_sha1, sha1, e)

    def delete_ref(self, ref, old_sha1, message=None):
        '''Remove the ref `ref`.

        `message` is a string to add to the reflog about this change
        `old_sha1` must be a 40 character hexadecimal string representing
        the SHA1 of the commit or tag this ref will point to, this is
        the result of the commit_tree or resolve_ref_to_commit methods.
        `ref` must exist, and point to `old_sha1`.
        This is to avoid unexpected results when multiple processes
        attempt to change refs.

        '''
        self._check_is_sha1(old_sha1)
        try:
            return self._update_ref(('-d', ref, old_sha1), message)
        except Exception, e:
            raise RefDeleteError(self, ref, old_sha1, e)

    def describe(self):
        version = self._runcmd(
            ['git', 'describe', '--always', '--dirty=-unreproducible'])
        return version.strip()

    def fat_init(self): # pragma: no cover
        return self._runcmd(['git', 'fat', 'init'])

    def fat_push(self): # pragma: no cover
        return self._runcmd(['git', 'fat', 'push'])

    def fat_pull(self): # pragma: no cover
        return self._runcmd(['git', 'fat', 'pull'])

    def has_fat(self): # pragma: no cover
        return os.path.isfile(self.join_path('.gitfat'))

    def join_path(self, path): # pragma: no cover
        return os.path.join(self.dirname, path)

    def get_relpath(self, path): # pragma: no cover
        return os.path.relpath(path, self.dirname)


def init(dirname):
    '''Initialise a new git repository.'''

    cliapp.runcmd(['git', 'init'], cwd=dirname)
    gd = GitDirectory(dirname)
    return gd


def clone_from_cached_repo(cached_repo, dirname, ref): # pragma: no cover
    '''Clone a CachedRepo into the desired directory.

    The given ref is checked out (or git's default branch is checked out
    if ref is None).

    '''

    cached_repo.clone_checkout(ref, dirname)
    return GitDirectory(dirname)

