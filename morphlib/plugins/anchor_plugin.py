# -*- coding: utf-8 -*-
# Copyright © 2015  Codethink Limited
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


from collections import defaultdict

import cliapp

from morphlib.branchmanager import RemoteRefManager
from morphlib.buildcommand import BuildCommand
from morphlib.gitdir import (PushFailureError, RefSpec, Remote)
from morphlib.repoaliasresolver import RepoAliasResolver


TAG_PUSH_ERR = 'error: Trying to write non-commit object'


INVALID_TAGS_MESSAGE = '''\

Some refs pointed to tag objects and the anchor-ref-format option was
configured to push anchor refs to refs/heads.
Unfortunately git does not allow tags to be pushed there, so the commit objects
they point to have been pushed instead.
As a result the anchored systems cannot be built with the current definitions.

To remedy this either:

1.  Re-configure the git server to allow pushes to outside of refs/heads and
    change anchor-ref-format to the new namespace

    i.e. Allow pushes to refs/tags/{trove_id} and run with
    --anchor-ref-format=refs/tags/{trove_id}/anchors/{name}/{commit_sha1}

2.  Amend definitions so that the following refs are replaced with their listed
    commit. The anchors that were pushed will remain appropriate to preserve
    reproducibility with the amended definitions.

---
'''


class AnchorPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'anchor', self.anchor, arg_synopsis='NAME REPO REF SYSTEM...')
        self.app.settings.string(
            ['anchor-ref-format'],
            'python format string with {trove_id}, {name} and '
            '{commit_sha1} interpolated in to produce the name of the '
            'anchor refs to push',
            metavar='FORMAT',
            default='refs/heads/{trove_id}/anchors/{name}/{commit_sha1}',
            group='anchor options')

    def disable(self):
        pass

    @staticmethod
    def _push(status, rrm, remote, refspecs):
        status(msg='Pushing %(targets)s to %(repo)s',
               targets=', '.join(refspec.target for refspec in refspecs),
               repo=remote.get_push_url())
        rrm.push(remote, *refspecs)

    def anchor(self, args):
        '''Push anchoring commits for listed systems.

        Command line arguments:

        *   `NAME` - semantic name to anchor systems by.

            If the purpose of anchoring is to make sure a release can be
            reproducibly built, then you would use `NAME` to know which
            anchor refs are used to keep a release buildable, so when
            support for the release is dropped, the anchors may be
            dropped.

        *   `REPO` - repository url to definitions repository.

            For a locally checked out repository, this would be
            `file://$(pwd)`

        *   `REF` - name of branch in definitions repository.

            For a locally checked out repository, this would be `HEAD`

        *   `SYSTEM...` - list of systems to create anchors for

        '''
        if len(args) < 4:
            raise cliapp.AppException(
                'Insufficient args to anchor command, '
                'see morph help anchor')
        anchor_name, branch_repo, branch_ref = args[0:3]
        systems = args[3:]
        anchor_ref_format = self.app.settings['anchor-ref-format']

        trove_ids = self.app.settings['trove-id']
        if not trove_ids and '{trove_id}' in anchor_ref_format:
            raise cliapp.AppException(
                'No trove-id configured and anchor-ref-format has not '
                'been adjusted to remove it.')
        trove_id = trove_ids[0]

        resolver = RepoAliasResolver(self.app.settings['repo-alias'])

        with RemoteRefManager(cleanup_on_success=False) as rrm:
            unpushable_tags = set()
            # We must use the build logic to resolve the build graph as a
            # naive traversal of the morphologies would not determine that
            # some sources weren't required because even though it is in a
            # stratum morphology we used, none of its artifacts were used
            # to construct our system.
            sources_by_reponame = defaultdict(set)
            for system in systems:
                bc = BuildCommand(self.app)
                srcpool = bc.create_source_pool(branch_repo, branch_ref,
                                                [system])
                artifact = bc.resolve_artifacts(srcpool)
                sources = set(a.source for a in artifact.walk())
                for source in sources:
                    sources_by_reponame[source.repo_name].add(source)

            for reponame, sources in sources_by_reponame.iteritems():
                # UGLY HACK we need to push *FROM* our local repo cache to
                # avoid cloning everything multiple times.
                repo = bc.repo_cache.get_updated_repo(
                    reponame, refs=(s.original_ref for s in sources))
                remote = Remote(repo)

                push_url = resolver.push_url(reponame)
                remote.set_push_url(push_url)

                lsinfo = dict((ref, sha1) for (sha1, ref) in remote.ls())
                refspecparams = defaultdict(set)
                for source in sources:
                    sha1 = source.sha1
                    anchor_ref_name = anchor_ref_format.format(
                        name=anchor_name, trove_id=trove_id,
                        commit_sha1=sha1)
                    existing_anchor = lsinfo.get(anchor_ref_name)
                    params = (sha1, anchor_ref_name, existing_anchor)
                    refspecparams[params].add(source.original_ref)

                refspecs = dict(
                    (RefSpec(source=sha1, target=anchor_ref_name,
                            require=existing_anchor),
                     original_refs)
                    for ((sha1, anchor_ref_name, existing_anchor),
                         original_refs)
                    in refspecparams.iteritems())

                try:
                    self._push(status=self.app.status, rrm=rrm,
                               remote=remote, refspecs=refspecs.keys())
                except PushFailureError as e:
                    if TAG_PUSH_ERR not in e.stderr:
                        raise
                    results = set(e.results)
                    newrefspecs = set()

                    # We need to check the state of the remote so that we can
                    # re-send updates if one of the updates failed.
                    lsinfo = dict((ref, sha1) for (sha1, ref) in remote.ls())

                    for flag, sha1, target, summary, reason in results:
                        commit = repo.resolve_ref_to_commit(sha1)

                        # Fail if we failed to push something other than a tag
                        # pushed to a branch
                        if (flag == '!' and
                            not (commit != sha1
                                 and target.startswith('refs/heads/'))):
                            raise

                        for rs, original_refs in refspecs.iteritems():
                            if rs.source == sha1 and rs.target == target:
                                break

                        if flag != '!':
                            # We assert that if any of the pushes failed, then
                            # they were all rolled back, as otherwise we can't
                            # clean up properly.
                            assert (rs.source == rs.require
                                    or lsinfo.get(target) == rs.require)
                            # Because even successfull pushes were rolled back
                            # in the case of failure, we need to re-push the
                            # changes that had succeeded.
                            newrefspecs.add(
                                RefSpec(source=sha1, target=target,
                                        require=lsinfo.get(target)))
                            continue

                        unpushable_tags.add(
                            (remote, anchor_ref_name,
                             tuple(original_refs), sha1, commit))
                        newrefspecs.add(
                            RefSpec(source=commit, target=target,
                                    require=lsinfo.get(target)))

                    # Re-attempt the push with the new refspecs
                    self._push(status=self.app.status, rrm=rrm,
                               remote=remote, refspecs=newrefspecs)

            if unpushable_tags:
                self.app.status(msg=INVALID_TAGS_MESSAGE, error='very yes')
                for remote, pushed_ref, refs, tag, commit in unpushable_tags:
                    self.app.output.write(
                        'Replace {} with {}\n'.format(', '.join(refs), commit))
                self.app.output.flush()
