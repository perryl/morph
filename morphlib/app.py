# Copyright (C) 2011-2012  Codethink Limited
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
import collections
import logging
import os
import sys
import time
import warnings

import morphlib


defaults = {
    'trove-host': 'git.baserock.org',
    'trove-prefix': [ ],
    'repo-alias': [
        ('freedesktop='
            'git://anongit.freedesktop.org/#'
            'ssh://git.freedesktop.org/'),
        ('gnome='
            'git://git.gnome.org/%s#'
            'ssh://git.gnome.org/git/%s'),
        ('github='
            'git://github.com/%s#'
            'ssh://git@github.com/%s'),
    ],
    'cachedir': os.path.expanduser('~/.cache/morph'),
    'max-jobs': morphlib.util.make_concurrency(),
    'prefix': '/usr',
    'toolchain-target': '%s-baserock-linux-gnu' % os.uname()[4],
    'build-ref-prefix': 'baserock/builds'
}


class Morph(cliapp.Application):

    def add_settings(self):
        self.settings.boolean(['verbose', 'v'],
                              'show what is happening in much detail')
        self.settings.boolean(['quiet', 'q'],
                              'show no output unless there is an error')

        self.settings.string(['cachedir'],
                             'cache git repositories and build results in DIR',
                             metavar='DIR',
                             default=defaults['cachedir'])
        self.settings.string(['compiler-cache-dir'],
                             'cache compiled objects in DIR/REPO. If not '
                             'provided, defaults to CACHEDIR/ccache/',
                             metavar='DIR',
                             default=None)
        self.settings.string(['build-ref-prefix'],
                             'Prefix to use for temporary build refs',
                             metavar='PREFIX',
                             default=defaults['build-ref-prefix'])
        self.settings.string(['trove-host'],
                             'hostname of Trove instance',
                             metavar='TROVEHOST',
                             default=defaults['trove-host'])
        self.settings.string_list(['trove-prefix'],
                                  'list of URL prefixes that should be '
                                  'resolved to Trove',
                                  metavar='PREFIX, ...',
                                  default=defaults['trove-prefix'])

        group_advanced = 'Advanced Options'
        self.settings.boolean(['no-git-update'],
                              'do not update the cached git repositories '
                              'automatically',
                              group=group_advanced)
        self.settings.string_list(['repo-alias'],
                                  'list of URL prefix definitions, in the '
                                  'form: example=git://git.example.com/%s'
                                  '#git@git.example.com/%s',
                                  metavar='ALIAS=PREFIX#PULL#PUSH',
                                  default=defaults['repo-alias'],
                                  group=group_advanced)
        self.settings.string(['cache-server'],
                             'HTTP URL of the morph cache server to use. '
                             'If not provided, defaults to '
                             'http://TROVEHOST:8080/',
                             metavar='URL',
                             default=None,
                             group=group_advanced)
        self.settings.string(['tarball-server'],
                             'base URL to download tarballs. '
                             'If not provided, defaults to '
                             'http://TROVEHOST/tarballs/',
                             metavar='URL',
                             default=None,
                             group=group_advanced)

        # Build Options
        group_build = 'Build Options'
        self.settings.boolean(['bootstrap'],
                              'build stuff in bootstrap mode; this is '
                              'DANGEROUS and will install stuff on your '
                              'system',
                              group=group_build)
        self.settings.boolean(['keep-path'],
                              'do not touch the PATH environment variable',
                              group=group_build)
        self.settings.integer(['max-jobs'],
                              'run at most N parallel jobs with make (default '
                              'is to a value based on the number of CPUs '
                              'in the machine running morph',
                              metavar='N',
                              default=defaults['max-jobs'],
                              group=group_build)
        self.settings.boolean(['no-ccache'], 'do not use ccache',
                              group=group_build)
        self.settings.boolean(['no-distcc'], 'do not use distcc',
                              group=group_build)
        self.settings.string(['prefix'],
                             'build chunks with prefix PREFIX',
                             metavar='PREFIX', default=defaults['prefix'],
                             group=group_build)
        self.settings.boolean(['push-build-branches'],
                              'always push temporary build branches to the '
                              'remote repository',
                              group=group_build)
        self.settings.boolean(['staging-chroot'],
                              'build things in an isolated chroot '
                              '(default: true)',
                              group=group_build)
        self.settings.string_list(['staging-filler'],
                                  'use FILE as contents of build chroot',
                                  metavar='FILE',
                                  group=group_build)
        self.settings.string(['target-cflags'],
                             'inject additional CFLAGS into the environment '
                             'that is used to build chunks',
                             metavar='CFLAGS',
                             default='',
                             group=group_build)
        self.settings.string(['tempdir'],
                             'temporary directory to use for builds '
                             '(this is separate from just setting $TMPDIR '
                             'or /tmp because those are used internally '
                             'by things that cannot be on NFS, but '
                             'this setting can point at a directory in '
                             'NFS)',
                             metavar='DIR',
                             default=os.environ.get('TMPDIR'),
                             group=group_build)
        self.settings.string(['toolchain-target'],
                             'set the TOOLCHAIN_TARGET variable which is used '
                             'in some chunks to determine which architecture '
                             'to build tools for',
                             metavar='TOOLCHAIN_TARGET',
                             default=defaults['toolchain-target'],
                             group=group_build)

    def check_time(self):
        # Check that the current time is not far in the past.
        if time.localtime(time.time()).tm_year < 2012:
            raise morphlib.Error(
                'System time is far in the past, please set your system clock')

    def process_args(self, args):
        self.check_time()

        # Combine the aliases into repo-alias before passing on to normal
        # command processing.  This means everything from here on down can
        # treat settings['repo-alias'] as the sole source of prefixes for git
        # URL expansion.
        self.settings['repo-alias'] = morphlib.util.combine_aliases(self)
        if self.settings['cache-server'] is None:
            self.settings['cache-server'] = 'http://%s:8080/' % (
                self.settings['trove-host'])
        if self.settings['tarball-server'] is None:
            self.settings['tarball-server'] = 'http://%s/tarballs/' % (
                self.settings['trove-host'])
        if self.settings['compiler-cache-dir'] is None:
            self.settings['compiler-cache-dir'] = os.path.join(
                    self.settings['cachedir'], 'ccache')
        if 'MORPH_DUMP_PROCESSED_CONFIG' in os.environ:
            self.settings.dump_config(sys.stdout)
            sys.exit(0)
        cliapp.Application.process_args(self, args)

    def setup_plugin_manager(self):
        cliapp.Application.setup_plugin_manager(self)

        self.pluginmgr.locations += os.path.join(
            os.path.dirname(morphlib.__file__), 'plugins')

        s = os.environ.get('MORPH_PLUGIN_PATH', '')
        self.pluginmgr.locations += s.split(':')

        self.hookmgr = cliapp.HookManager()
        self.hookmgr.new('new-build-command', cliapp.FilterHook())
        self.system_kind_builder_factory = \
            morphlib.builder2.SystemKindBuilderFactory()

    def itertriplets(self, args):
        '''Generate repo, ref, filename triples from args.'''

        if (len(args) % 3) != 0:
            raise cliapp.AppException('Argument list must have full triplets')

        while args:
            assert len(args) >= 2, args
            yield args[0], args[1], args[2] + ".morph"
            args = args[3:]

    def _itertriplets(self, *args):
        warnings.warn('_itertriplets is deprecated, '
                      'use itertriplets instead', stacklevel=1,
                      category=DeprecationWarning)
        return self.itertriplets(*args)

    def create_source_pool(self, lrc, rrc, triplet):
        pool = morphlib.sourcepool.SourcePool()

        def add_to_pool(reponame, ref, filename, absref, tree, morphology):
            source = morphlib.source.Source(reponame, ref, absref, tree,
                                            morphology, filename)
            pool.add(source)

        self.traverse_morphs([triplet], lrc, rrc,
                             update=not self.settings['no-git-update'],
                             visit=add_to_pool)
        return pool

    def _create_source_pool(self, *args):
        warnings.warn('_create_source_pool is deprecated, '
                      'use create_source_pool instead', stacklevel=1,
                      category=DeprecationWarning)
        return self.create_source_pool(*args)

    def resolve_ref(self, lrc, rrc, reponame, ref, update=True):
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating
        or cloning the repository into the local repo cache.
        '''
        absref = None
        if lrc.has_repo(reponame):
            repo = lrc.get_repo(reponame)
            if update:
                self.status(msg='Updating cached git repository %(reponame)s',
                            reponame=reponame)
                repo.update()
            absref, tree = repo.resolve_ref(ref)
        elif rrc is not None:
            try:
                absref, tree = rrc.resolve_ref(reponame, ref)
                if absref is not None:
                    self.status(msg='Resolved %(reponame)s %(ref)s via remote '
                                'repo cache',
                                reponame=reponame,
                                ref=ref,
                                chatty=True)
            except:
                pass
        if absref is None:
            if update:
                self.status(msg='Caching git repository %(reponame)s',
                            reponame=reponame)
                repo = lrc.cache_repo(reponame)
                repo.update()
            else:
                repo = lrc.get_repo(reponame)
            absref, tree = repo.resolve_ref(ref)
        return absref, tree

    def resolve_refs(self, refs, lrc, rrc, update=True):
        resolved = {}

        # First resolve refs in all repositories that are already cached.
        local_references = [x for x in refs if lrc.has_repo(x[0])]
        for reponame, ref in local_references:
            repo = lrc.get_repo(reponame)
            if update:
                self.status(msg='Updating cached git repository %(reponame)s',
                            reponame=reponame)
                repo.update()
            absref, tree = repo.resolve_ref(ref)
            resolved[(reponame, ref)] = {
                    'repo': reponame,
                    'repo-url': repo.url,
                    'ref': ref,
                    'sha1': absref,
                    'tree': tree
            }

        # Then, if we have a remote repo cache, resolve refs in all
        # repositories that we haven't cached locally yet.
        if rrc:
            remote_references = [x for x in refs if not x in local_references]
            if remote_references:
                self.status(msg='Resolving %(count)i references via '
                                'remote repository cache',
                            count=len(remote_references))
                resolved_remote_refs = rrc.resolve_refs(remote_references)
                for reponame, ref in remote_references:
                    for reference in resolved_remote_refs.keys():
                            del resolved_remote_refs[reference]
                    resolved.update(resolved_remote_refs)

        # Lastly, attempt to cache repositories for any ref that has not
        # been resolved successfully so far.
        #
        # FIXME Doesn't this only ever cache repositories from the remote
        # repo cache that don't have the ref anyway? It is the same that
        # the resolve_ref() method does though...
        uncached_references = [x for x in refs if not x in resolved]
        for reponame, ref in uncached_references:
            if update:
                self.status(msg='Caching git repository %(reponame)s',
                            reponame=reponame)
                repo = lrc.cache_repo(reponame)
                repo.update()
            else:
                repo = lrc.get_repo(reponame)
            absref, tree = repo.resolve_ref(ref)
            resolved[(reponame, ref)] = {
                    'repo': reponame,
                    'repo-url': repo.url,
                    'ref': ref,
                    'sha1': absref,
                    'tree': tree
            }

        return resolved

    def traverse_morphs(self, triplets, lrc, rrc, update=True,
                        visit=lambda rn, rf, fn, arf, m: None):
        morph_factory = morphlib.morphologyfactory.MorphologyFactory(lrc, rrc,
                                                                     self)
        queue = collections.deque(triplets)
        updated_repos = set()
        resolved_refs = {}
        resolved_morphologies = {}

        def resolve_refs(morphology, *fields):
            # Resolve the references used in morphology at once.
            refs = []
            for field in fields:
                if field in morphology and morphology[field]:
                    refs.extend([(s['repo'], s['ref'])
                                 for s in morphology[field]])
            sha1s = self.resolve_refs(refs, lrc, rrc, update)

            # Mark them all as resolved so they are not resolved twice.
            for info in sha1s.itervalues():
                if 'error' in info:
                    raise cliapp.AppException(
                            'Failed to resolve reference "%s" '
                            'in repository %s' % (info['ref'], info['repo']))
                else:
                    reference = (info['repo'], info['ref'])
                    resolved_refs[reference] = (info['sha1'], info['tree'])

        def load_morphology(reponame, absref, filename):
            reference = (reponame, absref, filename)
            if not reference in resolved_morphologies:
                resolved_morphologies[reference] = \
                    morph_factory.get_morphology(*reference)
            return resolved_morphologies[reference]

        while queue:
            reponame, ref, filename = queue.popleft()
            update_repo = update and reponame not in updated_repos

            # Resolve the (repo, ref) reference, cache result.
            reference = (reponame, ref)
            if not reference in resolved_refs:
                resolved_refs[reference] = self.resolve_ref(
                        lrc, rrc, reponame, ref, update_repo)
            absref, tree = resolved_refs[reference]

            updated_repos.add(reponame)

            # Fetch the (repo, ref, filename) morphology, cache result.
            morphology = load_morphology(reponame, absref, filename)

            visit(reponame, ref, filename, absref, tree, morphology)

            # Resolve the refs of all strata and/or chunks in the
            # morphology at once.
            if morphology['kind'] == 'system':
                resolve_refs(morphology, 'strata')
                queue.extend((s['repo'], s['ref'], '%s.morph' % s['morph'])
                             for s in morphology['strata'])
            elif morphology['kind'] == 'stratum':
                resolve_refs(morphology, 'build-depends', 'chunks')
                if morphology['build-depends']:
                    queue.extend((s['repo'], s['ref'], '%s.morph' % s['morph'])
                                 for s in morphology['build-depends'])
                queue.extend((c['repo'], c['ref'], '%s.morph' % c['morph'])
                             for c in morphology['chunks'])

    def _traverse_morphs(self, *args):
        warnings.warn('_traverse_morphs is deprecated, '
                      'use traverse_morphs instead', stacklevel=1,
                      category=DeprecationWarning)
        return self.traverse_morphs(*args)

    def cache_repo_and_submodules(self, cache, url, ref, done):
        subs_to_process = set()
        subs_to_process.add((url, ref))
        while subs_to_process:
            url, ref = subs_to_process.pop()
            done.add((url, ref))
            cached_repo = cache.cache_repo(url)
            cached_repo.update()

            try:
                submodules = morphlib.git.Submodules(self, cached_repo.path,
                                                     ref)
                submodules.load()
            except morphlib.git.NoModulesFileError:
                pass
            else:
                for submod in submodules:
                    if (submod.url, submod.commit) not in done:
                        subs_to_process.add((submod.url, submod.commit))

    def _cache_repo_and_submodules(self, *args):
        warnings.warn('_cache_repo_and_submodules is deprecated, '
                      'use cache_repo_and_submodules instead', stacklevel=1,
                      category=DeprecationWarning)
        return self.cache_repo_and_submodules(*args)

    def status(self, **kwargs):
        '''Show user a status update.

        The keyword arguments are formatted and presented to the user in
        a pleasing manner. Some keywords are special:

        * ``msg`` is the message text; it can use ``%(foo)s`` to embed the
          value of keyword argument ``foo``
        * ``chatty`` should be true when the message is only informative,
          and only useful for users who want to know everything (--verbose)
        * ``error`` should be true when it is an error message

        All other keywords are ignored unless embedded in ``msg``.

        '''

        assert 'msg' in kwargs
        text = kwargs['msg'] % kwargs

        error = kwargs.get('error', False)
        chatty = kwargs.get('chatty', False)
        quiet = self.settings['quiet']
        verbose = self.settings['verbose']

        if error:
            logging.error(text)
        elif chatty:
            logging.debug(text)
        else:
            logging.info(text)

        ok = verbose or error or (not quiet and not chatty)
        if ok:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
            self.output.write('%s %s\n' % (timestamp, text))
            self.output.flush()

    def runcmd(self, argv, *args, **kwargs):
        if 'env' not in kwargs:
            kwargs['env'] = dict(os.environ)

        # convert the command line arguments into a string
        commands = [argv] + list(args)
        for command in commands:
            if isinstance(command, list):
                for i in xrange(0, len(command)):
                    command[i] = str(command[i])
        commands = [' '.join(command) for command in commands]

        # print the command line
        self.status(msg='# %(cmdline)s',
                    cmdline=' | '.join(commands),
                    chatty=True)

        # Log the environment.
        for name in kwargs['env']:
            logging.debug('environment: %s=%s' % (name, kwargs['env'][name]))

        # run the command line
        return cliapp.Application.runcmd(self, argv, *args, **kwargs)
