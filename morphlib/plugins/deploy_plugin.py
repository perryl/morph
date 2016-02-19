# Copyright (C) 2013-2016  Codethink Limited
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


import collections
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import warnings

import cliapp

import morphlib
from morphlib.artifactcachereference import ArtifactCacheReference


def configuration_for_system(system_id, vars_from_commandline,
                             deploy_defaults, deploy_params):
    '''Collect all configuration variables for deploying one system.

    This function collects variables from the following places:

      - the values specified in the 'deploy-defaults' section of the cluster
        .morph file.
      - values specified in the stanza for the system in the cluster.morph file
      - environment variables of the running `morph deploy` process
      - values specified on the `morph deploy` commandline, for example
        `mysystem.HOSTNAME=foo`.

    Later values override earlier ones, so 'deploy-defaults' has the lowest
    precidence and the `morph deploy` commandline has highest precidence.

    '''
    commandline_vars_for_system = [
        pair[len(system_id)+1:] for pair in vars_from_commandline
        if pair.startswith(system_id)]

    user_env = morphlib.util.parse_environment_pairs(
        os.environ, commandline_vars_for_system)

    # Order is important here: the second dict overrides the first, the third
    # overrides the second.
    final_env = dict(deploy_defaults.items() +
                     deploy_params.items() +
                     user_env.items())

    morphlib.util.sanitize_environment(final_env)

    return final_env


def determine_if_upgrade(deploy_env, upgrade_config, is_subsystem):
    if 'UPGRADE' not in deploy_env:
        if is_subsystem:
            return False
        return upgrade_config
    return deploy_env['UPGRADE'].lower() in ('1', 'true', 'yes')


def deployment_type_and_location(system_id, config, is_upgrade):
    '''Get method and location for deploying a given system.

    The rules for this depend on whether the user is running `morph deploy`
    (initial deployment) or `morph upgrade`. The latter honours 'upgrade-type'
    and 'upgrade-location' if they are set, falling back to 'type' and
    'location' if they are not. The former only honours 'type' and 'location'.

    In the past, only the 'type' and 'location' fields existed. So `morph
    upgrade` needs to handle the case where only these are set, to avoid
    breaking existing cluster .morph files.

    '''
    if is_upgrade and ('upgrade-type' in config or 'upgrade-location' in \
                       config):
        if 'upgrade-type' not in config:
            raise morphlib.Error(
                '"upgrade-location" was set for system %s, but not '
                '"upgrade-type"' % system_id)

        if 'upgrade-location' not in config:
            raise morphlib.Error(
                '"upgrade-type" was set for system %s, but not '
                '"upgrade-location"' % system_id)

        deployment_type = config['upgrade-type']
        location = config['upgrade-location']
    else:
        if 'type' not in config:
            raise morphlib.Error(
                '"type" is undefined for system "%s"' % system_id)

        if 'location' not in config:
            raise morphlib.Error(
                '"location" is undefined for system "%s"' % system_id)

        if is_upgrade:
            warnings.warn(
                '"upgrade-type" and "upgrade-location" were not specified for '
                'system %s, using "type" and "location"\n' % system_id)

        deployment_type = config['type']
        location = config['location']

    return deployment_type, location


class NotYetBuiltError(morphlib.Error):

    def __init__(self, artifact, rac):
        self.msg = ('Deployment failed as %s is not present in the '
                    'artifact cache.\nPlease ensure that %s is built '
                    'before deployment, and the artifact-cache-server (%s) is '
                    'the correct one.' % (artifact.basename(), artifact.name,
                                          rac))


class DeployPlugin(cliapp.Plugin):

    def enable(self):
        group_deploy = 'Deploy Options'
        self.app.settings.boolean(['upgrade'],
                                  'specify that you want to upgrade an '
                                  'existing cluster. Deprecated: use the '
                                  '`morph upgrade` command instead',
                                  group=group_deploy)
        self.app.add_subcommand(
            'deploy', self.deploy,
            arg_synopsis='CLUSTER [DEPLOYMENT...] [SYSTEM.KEY=VALUE]')
        self.app.add_subcommand(
            'upgrade', self.upgrade,
            arg_synopsis='CLUSTER [DEPLOYMENT...] [SYSTEM.KEY=VALUE]')

    def disable(self):
        pass

    def deploy(self, args):
        '''Deploy a built system image or a set of images.

        Command line arguments:

        * `CLUSTER` is the name of the cluster to deploy.

        * `DEPLOYMENT...` is the name of zero or more deployments in the
          morphology to deploy. If none are specified then all deployments
          in the morphology are deployed.

        * `SYSTEM.KEY=VALUE` can be used to assign `VALUE` to a parameter
          named `KEY` for the system identified by `SYSTEM` in the cluster
          morphology (see below). This will override parameters defined
          in the morphology.

        Morph deploys a set of systems listed in a cluster morphology.
        "Deployment" here is quite a general concept: it covers anything
        where a system image is taken, configured, and then put somewhere
        where it can be run. The deployment mechanism is quite flexible,
        and can be extended by the user.

        A cluster morphology defines a list of systems to deploy, and
        for each system a list of ways to deploy them. It contains the
        following fields:

        * **name**: MUST be the same as the basename of the morphology
         filename, sans .morph suffix.

        * **kind**: MUST be `cluster`.

        * **systems**: a list of systems to deploy;
         the value is a list of mappings, where each mapping has the
         following keys:

           * **morph**: the system morphology to use in the specified
             commit.

           * **deploy**: a mapping where each key identifies a
             system and each system has at least the following keys:

               * **type**: identifies the type of development e.g. (kvm,
                 pxeboot) (see below).
               * **location**: where the deployed system should end up
                 at. The syntax depends on the deployment type (see below).

             Optionally, it can specify **upgrade-type** and
             **upgrade-location** as well for use with `morph upgrade`. Any
             additional item on the dictionary will be added to the environment
             as `KEY=VALUE`.

            * **deploy-defaults**: allows multiple deployments of the same
             system to share some settings, when they can. Default settings
             will be overridden by those defined inside the deploy mapping.

         # Example

            name: cluster-foo
            kind: cluster
            systems:
                - morph: devel-system-x86_64-generic.morph
                  deploy:
                      cluster-foo-x86_64-1:
                          type: kvm
                          location: kvm+ssh://user@host/x86_64-1/x86_64-1.img
                          upgrade-type: ssh-rsync
                          upgrade-location: root@localhost
                          HOSTNAME: cluster-foo-x86_64-1
                          DISK_SIZE: 4G
                          RAM_SIZE: 4G
                          VCPUS: 2
                - morph: devel-system-armv7-highbank
                  deploy-defaults:
                      type: pxeboot
                      location: cluster-foo-pxeboot-server
                  deploy:
                      cluster-foo-armv7-1:
                          HOSTNAME: cluster-foo-armv7-1
                      cluster-foo-armv7-2:
                          HOSTNAME: cluster-foo-armv7-2

        Each system defined in a cluster morphology can be deployed in
        multiple ways (`type` in a cluster morphology). These methods are
        implemented by .write extensions. There are some built into Morph,
        and you can also store them in a definitions.git repo.

        See `morph help-extensions` for a full list of these extensions. If you
        run this command in a system branch, it will list those that are
        available in the definitions.git repo that is checked out as well as
        those built-in to Morph. Each extension can provide its own
        documentation. To see help for the 'tar' write extension, for example,
        run `morph help tar.write`.

        In addition to the deployment type, the user must also give
        a value for `location`. Its syntax depends on the deployment
        method. See the help file for the given write extension to find out
        how to format the 'location' field.

        Deployments take additional `KEY=VALUE` parameters as well. These can
        be provided in the following ways:

        1. In the cluster definition file, e.g.

            ...
            systems:
            - morph: systems/foo-system.morph
              deploy:
                foo:
                  HOSTNAME: foo

        2.  In the environment before running e.g.

            `HOSTNAME=foo morph deploy ...`

        3.  On the command-line e.g.
         `morph deploy clusters/foo.morph foo.HOSTNAME=foo`

        For any boolean `KEY=VALUE` parameters, allowed values are:

        +ve `yes`, `1`, `true`;

        -ve `no`, `0`, `false`;

        Some extensions require certain parameters to be set, be sure to read
        the documentation of the extension you are using.

        Regardless of the type of deployment, the image may be
        configured for a specific deployment by using **configuration
        extensions**. The extensions are listed in the system morphology
        file:

            ...
            configuration-extensions:
                - set-hostname

        The above specifies that the extension `set-hostname` is to
        be run.  Morph will run all the configuration extensions listed
        in the system morphology, and no others. (This way, configuration
        is more easily tracked in git.)

        Configuration extensions are scripts that get the unpacked
        directory tree of the system as their parameter, and do whatever
        is needed to configure the tree. Available .configuration extensions
        can be found with `morph help-extensions`, as with .write extensions.

        Any `KEY=VALUE` parameters given in `deploy` or `deploy-defaults`
        sections of the cluster morphology, or given through the command line
        are set as environment variables when either the configuration or the
        write extension runs.

        You can write your own .write and .configure extensions, in any
        format that Morph can execute at deploy-time. They must be committed
        to your definitions.git repository for Morph to find them.
        A .configure extension is passed one argument: the path to an unpacked
        directory tree containing the system files. A write extension is passed
        two command line parameters: the path to the unpacked system, and the
        `location` parameter. The .configure and .write extensions have full
        'root' access to the build machine, so write them carefully!

        Deployment configuration is stored in the deployed system as
        /baserock/deployment.meta. THIS CONTAINS ALL ENVIRONMENT VARIABLES SET
        DURING DEPLOYMENT, so make sure you have no sensitive information in
        your environment that is being leaked. As a special case, any
        environment/deployment variable that contains 'PASSWORD' in its name is
        stripped out and not stored in the final system.

        '''

        # Nasty hack to allow deploying things of a different architecture
        def validate(self, root_artifact):
            pass
        morphlib.buildcommand.BuildCommand._validate_architecture = validate

        if not args:
            raise cliapp.AppException(
                'Too few arguments to deploy command (see help)')

        # Raise an exception if there is not enough space in tempdir
        # / for the path and 0 for the minimum size is a no-op
        # it exists because it is complicated to check the available
        # disk space given dirs may be on the same device
        morphlib.util.check_disk_available(
            self.app.settings['tempdir'],
            self.app.settings['tempdir-min-space'],
            '/', 0)

        definitions_repo = morphlib.definitions_repo.open(
            '.', search_for_root=True, app=self.app)

        cluster_filename = morphlib.util.sanitise_morphology_path(args[0])
        cluster_filename = definitions_repo.relative_path(cluster_filename)

        loader = morphlib.morphloader.MorphologyLoader()
        cluster_text = definitions_repo.read_file(cluster_filename)
        cluster_morphology = loader.load_from_string(cluster_text,
                                                     filename=cluster_filename)

        if cluster_morphology['kind'] != 'cluster':
            raise cliapp.AppException(
                "Error: morph deployment commands are only supported for "
                "cluster morphologies.")

        # parse the rest of the args
        all_subsystems = set()
        all_deployments = set()
        deployments = set()
        for system in cluster_morphology['systems']:
            all_deployments.update(system['deploy'].iterkeys())
            if 'subsystems' in system:
                all_subsystems.update(loader._get_subsystem_names(system))
        for item in args[1:]:
            if not item in all_deployments:
                break
            deployments.add(item)
        env_vars = args[len(deployments) + 1:]
        self.validate_deployment_options(
            env_vars, all_deployments, all_subsystems)

        self.deploy_cluster(definitions_repo, cluster_morphology,
                            env_vars, deployments)

        self.app.status(msg='Finished deployment')
        if self.app.settings['partial']:
            self.app.status(msg='WARNING: This was a partial deployment. '
                                'Configuration extensions have not been '
                                'run. Applying the result to an existing '
                                'system may not have reproducible results.')

    def validate_deployment_options(
            self, env_vars, all_deployments, all_subsystems):
        for var in env_vars:
            for subsystem in all_subsystems:
                if subsystem == var:
                    raise cliapp.AppException(
                        'Cannot directly deploy subsystems. Create a top '
                        'level deployment for the subsystem %s instead.' %
                        subsystem)
                if (not any(deployment in var
                            for deployment in all_deployments)
                    and not subsystem in var):
                    raise cliapp.AppException(
                        'Variable referenced a non-existent deployment '
                        'name: %s' % var)

    def deploy_cluster(self, definitions_repo, cluster_morphology,
                       env_vars, deployments):
        # Create a tempdir for this deployment to work in
        tmp_basedir = os.path.join(self.app.settings['tempdir'], 'deployments')
        with morphlib.util.temp_dir(dir=tmp_basedir) as deploy_tempdir:
            for system in cluster_morphology['systems']:
                self.deploy_system(deploy_tempdir, definitions_repo,
                                   system, env_vars, deployments,
                                   parent_location='')

    def _sanitise_morphology_paths(self, paths, definitions_repo):
        sanitised_paths = []
        for path in paths:
            path = morphlib.util.sanitise_morphology_path(path)
            sanitised_paths.append(definitions_repo.relative_path(path))
            sanitised_paths.append(path)
        return sanitised_paths

    def _find_artifacts(self, filenames, root_artifact):
        found = collections.OrderedDict()
        not_found = filenames
        for a in root_artifact.walk():
            if a.source.filename in filenames:
                if a.source.name in found:
                    found[a.source.name].append(a)
                else:
                    found[a.source.name] = [a]
        for name, artifacts in found.iteritems():
            if artifacts[0].source.filename in not_found:
                not_found.remove(artifacts[0].source.filename)
        return found, not_found

    def _validate_partial_deployment(self, deployment_type,
                                     artifact, component_names):
        supported_types = ('tar', 'sysroot')
        if deployment_type not in supported_types:
            raise cliapp.AppException('Not deploying %s, --partial was '
                                      'set and partial deployment only '
                                      'supports %s deployments.' %
                                      (artifact.source.name,
                                       ', '.join(supported_types)))
        components, not_found = self._find_artifacts(component_names,
                                                     artifact)
        if not_found:
            raise cliapp.AppException('Components %s not found in system %s.' %
                                      (', '.join(not_found),
                                       artifact.source.name))
        return components

    def deploy_system(self, deploy_tempdir, definitions_repo, system, env_vars,
                      deployment_filter, parent_location):
        sys_ids = set(system['deploy'].iterkeys())
        if deployment_filter and not \
                any(sys_id in deployment_filter for sys_id in sys_ids):
            return

        # FIXME: right now we create a new source pool and possibly a new
        # temporary branch, for each system and subsystem being deployed.
        # We could do a much better job if a source pool could contain
        # multiple systems of different architectures.
        morph = morphlib.util.sanitise_morphology_path(system['morph'])

        source_pool_context = definitions_repo.source_pool(
            definitions_repo.HEAD, morph)
        with source_pool_context as source_pool:
            self.deploy_system_with_source_pool(
                deploy_tempdir, definitions_repo, source_pool, system,
                env_vars, deployment_filter, parent_location)

    def deploy_system_with_source_pool(self, deploy_tempdir, definitions_repo,
                                       source_pool, system, env_vars,
                                       deployment_filter, parent_location):
        old_status_prefix = self.app.status_prefix
        system_status_prefix = '%s[%s]' % (old_status_prefix, system['morph'])
        self.app.status_prefix = system_status_prefix
        try:
            build_command = morphlib.buildcommand.BuildCommand(self.app)
            artifact = build_command.resolve_artifacts(source_pool)

            deploy_defaults = system.get('deploy-defaults') or {}
            for system_id, deploy_params in system['deploy'].iteritems():
                if not system_id in deployment_filter and deployment_filter:
                    continue
                deployment_status_prefix = '%s[%s]' % (
                    system_status_prefix, system_id)
                self.app.status_prefix = deployment_status_prefix
                try:
                    final_env = configuration_for_system(
                        system_id, env_vars, deploy_defaults, deploy_params)

                    is_upgrade = determine_if_upgrade(
                            deploy_env=final_env,
                            upgrade_config=self.app.settings['upgrade'],
                            is_subsystem=(parent_location != ''))
                    final_env['UPGRADE'] = ('yes' if is_upgrade else 'no')

                    deployment_type, location = deployment_type_and_location(
                        system_id, final_env, is_upgrade)

                    extensions_dir = os.path.join(
                        definitions_repo.dirname,
                        os.path.dirname(deployment_type))
                    if 'PYTHONPATH' in final_env:
                        final_env['PYTHONPATH'] += ':%s' % extensions_dir
                    else:
                        final_env['PYTHONPATH'] = extensions_dir

                    components = self._sanitise_morphology_paths(
                        deploy_params.get('partial-deploy-components', []),
                        definitions_repo)
                    if self.app.settings['partial']:
                        components = self._validate_partial_deployment(
                            deployment_type, artifact, components)

                    self.check_deploy(definitions_repo, deployment_type,
                                      location, final_env)
                    system_tree = self.setup_deploy(build_command,
                                                    deploy_tempdir,
                                                    definitions_repo,
                                                    artifact,
                                                    deployment_type,
                                                    location, final_env,
                                                    components=components)
                    for subsystem in system.get('subsystems', []):
                        self.deploy_system(deploy_tempdir, definitions_repo,
                                           subsystem, env_vars, [],
                                           parent_location=system_tree)
                    if parent_location:
                        deploy_location = os.path.join(parent_location,
                                                       location.lstrip('/'))
                    else:
                        deploy_location = location
                    self.run_deploy_commands(deploy_tempdir, final_env,
                                             artifact, definitions_repo,
                                             deployment_type, system_tree,
                                             deploy_location)
                finally:
                    self.app.status_prefix = system_status_prefix
        finally:
            self.app.status_prefix = old_status_prefix

    def upgrade(self, args):
        '''Upgrade an existing set of instances using built images.

        This command is very similar to `morph deploy`. Please read `morph help
        deploy` first for an introduction to deployment (cluster) .morph files.

        To allow upgrading a system after the initial deployment, you need to
        set two extra fields: **upgrade-type** and **upgrade-location**.

        The most common .write extension for upgrades is the `ssh-rsync` write
        extension. See `morph help ssh-rsync.write` to read its documentation

        To deploy a development system that can then deploy upgrades to itself
        using passwordless SSH access, adapt the following example cluster:

            name: devel-system
            kind: cluster
            systems:
                - morph: systems/devel-system-x86_64-generic.morph
                  deploy:
                      devel-system:
                          type: kvm
                          location: kvm+ssh://...

                          upgrade-type: ssh-rsync
                          upgrade-location: root@localhost

                          HOSTNAME: my-devel-system
                          ..

        '''

        if not args:
            raise cliapp.AppException(
                'Too few arguments to upgrade command (see `morph help '
                'deploy`)')

        self.app.settings['upgrade'] = True
        self.deploy(args)

    def check_deploy(self, definitions_repo, deployment_type, location, env):
        # Run optional write check extension. These are separate from the write
        # extension because it may be several minutes before the write
        # extension itself has the chance to raise an error.
        try:
            self._run_extension(
                definitions_repo, deployment_type, '.check',
                [location], env)
        except morphlib.extensions.ExtensionNotFoundError:
            pass

    def unpack_stratum(self, path, artifact, lac, rac, unpacked):
        """Fetch the chunks in a stratum, then unpack them into `path`.

        This reads a stratum artifact and fetches the chunks it contains from
        the remote into the local artifact cache if they are not already
        cached locally. Each of these chunks is then unpacked into `path`.

        Also download the stratum metadata into the local cache, then place
        it in the baserock subdirectory directory of `path`.

        If any of the chunks have not been cached either locally or remotely,
        a morphlib.remoteartifactcache.GetError is raised.

        """
        with lac.get(artifact) as stratum:
            chunks = [ArtifactCacheReference(c) for c in json.load(stratum)]
        morphlib.builder.download_depends(chunks, lac, rac)
        for chunk in chunks:
            if chunk.basename() in unpacked:
                continue
            self.app.status(msg='Unpacking chunk %(name)s.',
                            name=chunk.basename(), chatty=True)
            handle = lac.get(chunk)
            tf = tarfile.open(fileobj=handle)
            tf.extractall(path=path)
            unpacked.add(chunk.basename())

        metadata = os.path.join(path, 'baserock', '%s.meta' % artifact.name)
        with lac.get_artifact_metadata(artifact, 'meta') as meta_src:
            with morphlib.savefile.SaveFile(metadata, 'w') as meta_dst:
                shutil.copyfileobj(meta_src, meta_dst)

    def unpack_system(self, build_command, artifact, path):
        """Unpack a system into `path`.

        This unpacks the system artifact into the directory given by
        `path`. If the system is not in the local cache, it is first fetched
        from the remote cache.

        Raises a NotYetBuiltError if the system artifact isn't cached either
        locally or remotely.

        """
        # Unpack the artifact (tarball) to a temporary directory.
        self.app.status(msg='Unpacking system for configuration')

        if build_command.lac.has(artifact):
            f = build_command.lac.get(artifact)
        elif build_command.rac.has(artifact):
            build_command.cache_artifacts_locally([artifact])
            f = build_command.lac.get(artifact)
        else:
            raise NotYetBuiltError(artifact, build_command.rac)

        tf = tarfile.open(fileobj=f)
        tf.extractall(path=path)

        self.app.status(
            msg='System unpacked at %(system_tree)s',
            system_tree=path)

    def unpack_components(self, bc, components, path):
        if not components:
            raise cliapp.AppException('Deployment failed as no components '
                                      'were specified for deployment and '
                                      '--partial was set.')

        self.app.status(msg='Unpacking components for deployment')
        unpacked = set()
        for name, artifacts in components.iteritems():
            for artifact in artifacts:
                if not (bc.lac.has(artifact) or bc.rac.has(artifact)):
                    raise NotYetBuiltError(name, bc.rac)

                for a in artifact.walk():
                    if a.basename() in unpacked:
                        continue
                    if not bc.lac.has(a):
                        if bc.rac.has(a):
                            bc.cache_artifacts_locally([a])
                        else:
                            raise NotYetBuiltError(a.name, bc.rac)
                    if a.source.morphology['kind'] == 'stratum':
                        self.unpack_stratum(path, a, bc.lac, bc.rac, unpacked)
                    elif a.source.morphology['kind'] == 'chunk':
                        if a.source.morphology['build-mode'] == 'bootstrap':
                            continue
                        self.app.status(msg='Unpacking chunk %(name)s.',
                                        name=a.basename(), chatty=True)
                        handle = bc.lac.get(a)
                        tf = tarfile.open(fileobj=handle)
                        tf.extractall(path=path)
                    unpacked.add(a.basename())

        self.app.status(
            msg='Components %(components)s unpacked at %(path)s',
            components=', '.join(components), path=path)

    def setup_deploy(self, build_command, deploy_tempdir, definitions_repo,
                     artifact, deployment_type, location, env, components=[]):
        # Create a tempdir to extract the rootfs in
        with morphlib.util.temp_dir(dir=deploy_tempdir,
                                    cleanup_on_success=False) as system_tree:
            # FIXME: This should be fixed in morphloader.
            morphlib.util.fix_chunk_build_mode(artifact)
            if self.app.settings['partial']:
                self.unpack_components(build_command, components, system_tree)
            else:
                self.unpack_system(build_command, artifact, system_tree)

            self.app.status(
                msg='Writing deployment metadata file')
            metadata = self.create_metadata(
                    artifact, definitions_repo, deployment_type, location, env)
            metadata_path = os.path.join(
                    system_tree, 'baserock', 'deployment.meta')
            with morphlib.savefile.SaveFile(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=4,
                          sort_keys=True, encoding='unicode-escape')
            return system_tree

    def run_deploy_commands(self, deploy_tempdir, env, artifact,
                            definitions_repo, deployment_type, system_tree,
                            location):
        # Extensions get a private tempdir so we can more easily clean
        # up any files an extension left behind
        with morphlib.util.temp_dir(dir=deploy_tempdir) \
             as deploy_private_tempdir:
            env['TMPDIR'] = deploy_private_tempdir
            # Run configuration extensions.
            if not self.app.settings['partial']:
                self.app.status(msg='Configure system')
                names = artifact.source.morphology['configuration-extensions']
                for name in names:
                    self._run_extension(
                        definitions_repo,
                        name,
                        '.configure',
                        [system_tree],
                        env)
            else:
                self.app.status(msg='WARNING: Not running configuration '
                                    'extensions as --partial is set!')

            # Run write extension.
            self.app.status(msg='Writing to device')
            self._run_extension(
                definitions_repo,
                deployment_type,
                '.write',
                [system_tree, location],
                env)

    def _report_extension_stdout(self, line):
        self.app.status(msg=line.replace('%', '%%'))
    def _report_extension_stderr(self, error_list):
        def cb(line):
            error_list.append(line)
            sys.stderr.write('%s\n' % line)
        return cb
    def _report_extension_logger(self, name, kind):
        return lambda line: logging.debug('%s%s: %s', name, kind, line)
    def _run_extension(self, definitions_repo, name, kind, args, env):
        '''Run an extension.

        The ``kind`` should be either ``.configure`` or ``.write``,
        depending on the kind of extension that is sought.

        The extension is found either in the git repository of the
        system morphology (repo, ref), or with the Morph code.

        '''
        error_list = []
        filename_context = morphlib.extensions.get_extension_filename(
            definitions_repo, name, kind)
        with filename_context as fn:
            ext = morphlib.extensions.ExtensionSubprocess(
                report_stdout=self._report_extension_stdout,
                report_stderr=self._report_extension_stderr(error_list),
                report_logger=self._report_extension_logger(name, kind),
            )
            returncode = ext.run(fn, args, env=env,
                                 cwd=definitions_repo.dirname)
        if returncode == 0:
            logging.info('%s%s succeeded', name, kind)
        else:
            message = '%s%s failed with code %s: %s' % (
                name, kind, returncode, '\n'.join(error_list))
            raise cliapp.AppException(message)

    def create_metadata(self, system_artifact, definitions_repo,
                        deployment_type, location, env, components=[]):
        '''Deployment-specific metadata.

        The `build` and `deploy` operations must be from the same ref, so full
        info on the root repo that the system came from is in
        /baserock/${system_artifact}.meta and is not duplicated here. We do
        store a `git describe` of the definitions.git repo as a convenience for
        post-upgrade hooks that we may need to implement at a future date:
        the `git describe` output lists the last tag, which will hopefully help
        us to identify which release of a system was deployed without having to
        keep a list of SHA1s somewhere or query a Trove.

        '''

        def remove_passwords(env):
            is_password = morphlib.util.env_variable_is_password
            return { k:v for k, v in env.iteritems() if not is_password(k) }

        meta = {
            'system-artifact-name': system_artifact.name,
            'configuration': remove_passwords(env),
            'deployment-type': deployment_type,
            'location': location,
            'definitions-version': {
                'describe': definitions_repo.describe(),
            },
            'morph-version': {
                'ref': morphlib.gitversion.ref,
                'tree': morphlib.gitversion.tree,
                'commit': morphlib.gitversion.commit,
                'version': morphlib.gitversion.version,
            },
            'partial': self.app.settings['partial'],
        }
        if self.app.settings['partial']:
            meta['partial-components'] = components

        return meta
