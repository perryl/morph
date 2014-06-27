# Still to do:

#   - not all Gems are resolved to the right source repos so far: that needs to
#   change (just hardcode the unknown ones, for now).

#   - needs to output the 'ruby-core' stratum (stuff that other stuff in Ruby
#   build-depends on, that should probably all be installed using 'Gem' to
#   avoid circular dependencies). 'chef', 'gitlab', 'heroku', etc. strata,
#   which contain just the necessary stuff for those, built from source or
#   Gems, and 'ruby-foundation', which contains the common chunks from those
#   strata (build from source or Gems, again).

#   - needs to check out each goal chunk's source code, and look for a
#   Gemfile.lock file.

import requests
import requests_cache
import yaml

import beak

import collections
import logging
import json
import os
import urlparse
from itertools import chain
from logging import debug


logging.basicConfig(level=logging.DEBUG)


# Some random popular Gems
goals = [
    #'capistrano',
    'chef',
    #'gitlab',
    #'heroku',
    #'knife-solo',
    #'ohai',
    #'pry',
    #'puppet',
    #'rails',
    #'sass',
    #'travis',
    #'vagrant',
]

# This tool works to a rather pessimistic rule that any chunk that's used at
# build time requires all of its runtime dependencies available at build time
# too. This might not be the case, and in some cases it causes unsolvable
# dependency loops. Solve them by adding them to this list.
runtime_only_dependencies = [
    # Chef clients require Ohai at runtime. Ohai requires Chef at build time,
    # but this is just to to be present at that point.
    ('chef', 'ohai')
]

# Shorter!
#gems = ['vagrant']

# Ruby bundles some Gems! This list was generated with 'gem list' after a Ruby
# 2.0.0p477 install.
built_in_gems = {
    'bigdecimal': '1.2.0',
    'io-console': '0.4.2',
    'json': '1.7.7',
    'minitest': '4.3.2',
    'psych': '2.0.0',
    'rake': '0.9.6',
    'rdoc': '4.0.0',
    'test-unit': '2.0.0.0',
}

# Gemspecs combine 'tools useful when developing or testing this Gem' with
# 'tools needed to create a .gem file'. Beak will only consider the Gems
# in this list when constructing the build-dependency graph; otherwise too many
# things are included that aren't actually build dependencies and the graph
# usually becomes unsolvable.
build_tool_gems = {
    'hoe': '$version',
}

known_source_uris = {
    'actionmailer': 'https://github.com/rails/rails',
    'actionpack': 'https://github.com/rails/rails',
    'actionview': 'https://github.com/rails/rails',
    'activemodel': 'https://github.com/rails/rails',
    'activerecord': 'https://github.com/rails/rails',
    'activesupport': 'https://github.com/rails/rails',
    'rails': 'https://github.com/rails/rails',
}


# Save hammering the rubygems.org API: 'requests' API calls are
# transparently cached in an SQLite database, instead.
requests_cache.install_cache('rubygems_api_cache')


class RubyTreasureHunter(object):
    '''Sniff out the upstream source repo for a Ruby Gem.'''

    class Stats(object):
        def __init__(self):
            self.have_source_code_uri = 0
            self.have_homepage_uri = 0
            self.homepage_is_github = 0
            self.no_source_found = 0
            self.hardcoded_uris_used = 0

        def show(self):
            print "Gems with source_code_uri set: ", self.have_source_code_uri
            print "Gems with homepage_uri set: ", self.have_homepage_uri
            print "Gems with homepage_uri pointing to Github: ", \
                self.homepage_is_github
            print "Gems for which we have a hard-coded source URI", \
                self.hardcoded_uris_used
            print "Gems with no source found", self.no_source_found

    def __init__(self):
        self.stats = self.Stats()

    def find_upstream_repo_for_gem(self, gem_info):
        gem_name = gem_info['name']
        source_code_uri = gem_info['source_code_uri']
        if source_code_uri is not None:
            self.stats.have_source_code_uri += 1
            return source_code_uri

        if gem_name in known_source_uris:
            known_uri = known_source_uris[gem_name]
            if source_code_uri is not None and known_uri != source_code_uri:
                raise Exception(
                    '%s: Hardcoded source URI %s doesn\'t match spec URI %s' %
                    (gem_name, known_uri, source_code_uri))
            self.stats.hardcoded_uris_used += 1
            return known_uri

        homepage_uri = gem_info['homepage_uri']
        if homepage_uri is not None:
            self.stats.have_homepage_uri += 1
            netloc = urlparse.urlsplit(homepage_uri)[1]
            if netloc == 'github.com':
                self.stats.homepage_is_github += 1
                return homepage_uri

        # Further possible leads on locating source code.
        # http://ruby-toolbox.com/projects/$gemname -> sometimes contains an
        #   upstream link, even if the gem info does not.
        # https://github.com/search?q=$gemname -> often the first result is
        #   the correct one, but you can never know.

        self.stats.no_source_found += 1
        #print gem_info
        return None


class RubyGemsResolver(object):
    def get_gem_info(self, gem_name):
        r = requests.get('http://rubygems.org/api/v1/gems/%s.json' % gem_name)
        return json.loads(r.text)

    def chunk_name_from_repo(self, repo_url):
        if repo_url.endswith('/tree/master'):
            repo_url = repo_url[:-len('/tree/master')]
        if repo_url.endswith('/'):
            repo_url = repo_url[:-1]
        if repo_url.endswith('.git'):
            repo_url = repo_url[:-len('.git')]
        return os.path.basename(repo_url)

    def resolve_chunks_for_gems(self, gem_list):
        source_hunter = RubyTreasureHunter()

        resolved_chunks = dict()
        resolved_gems = dict()
        to_process = collections.deque(gem_list)
        while len(to_process) > 0:
            gem_name = to_process.pop()

            print "[%i processed, %i to go] Fetching info for %s from " \
                "Rubygems.org" % (len(resolved_chunks), len(to_process),
                                  gem_name)

            gem_info = self.get_gem_info(gem_name)

            repo = source_hunter.find_upstream_repo_for_gem(gem_info)

            # Any number of gems can be produced from one source repository,
            # so the chunk name doesn't correspond to the Gem name.
            chunk_name = self.chunk_name_from_repo(repo) if repo else gem_name
            chunk = resolved_chunks.get(chunk_name, None)

            gem_runtime_deps = gem_info['dependencies']['runtime']

            # These are dependencies you want to have installed when working on
            # the code, not necessarily just for constructing a Gem file. We
            # include them in the stratum but do not link them as build
            # dependencies based on this information -- most of the time they
            # won't actually be required just to get a .gem, they'll be for
            # running tests and the like.
            gem_development_deps = gem_info['dependencies']['development']

            # There are version constraints specified here that we
            # currently ignore. Furthermore, the Gemfile.lock (Bundler)
            # file may have an even more specific constraint! I think
            # ideally we want to run 'master' of everything, or at least
            # the last tagged commit of everything, so let's ignore this
            # info for now and start some builds!

            for dep_info in gem_development_deps + gem_runtime_deps:
                dep_name = dep_info['name']
                ignore = chain(to_process, resolved_gems.iterkeys(),
                               built_in_gems)
                if dep_name not in ignore:
                    to_process.append(dep_name)

            chunk_build_deps = set()
            chunk_runtime_deps = set()
            chunk_test_deps = set()

            for dep_info in gem_development_deps:
                dep_name = dep_info['name']
                if dep_name in built_in_gems:
                    pass
                elif dep_name in test_tool_gems:
                    chunk_test_deps.add(dep_name)
                else:
                    chunk_build_deps.add(dep_name)

            for dep_info in gem_runtime_deps:
                dep_name = dep_info['name']
                if dep_name not in built_in_gems:
                    chunk_runtime_deps.add(dep_name)

            if chunk is None:
                ref = 'master'
                chunk = beak.Source(chunk_name, repo, ref, chunk_build_deps,
                                    chunk_runtime_deps)
                resolved_chunks[chunk_name] = chunk
            else:
                chunk.add_build_deps(chunk_build_deps)
                chunk.add_runtime_deps(chunk_runtime_deps)

            artifact = beak.Artifact(gem_name, chunk)
            resolved_gems[gem_name] = artifact
            chunk.add_artifact(artifact)

        self.resolve_dependencies(resolved_chunks, resolved_gems)

        return resolved_chunks

    def resolve_dependencies(self, sources, artifacts):
        # Convert the dependencies from being lists of names to being the
        # actual artifact objects.
        for chunk in sources.itervalues():
            dep_names = chunk.build_deps
            dep_artifacts = set(artifacts[name] for name in dep_names)
            # Dependencies between artifacts from the same source cause the
            # source to depend on itself. Remove those.
            dep_artifacts.difference_update(chunk.artifacts)
            chunk.build_deps = dep_artifacts

            for artifact in dep_artifacts:
                artifact.source.used_at_build_time = True

        for chunk in sources.itervalues():
            dep_names = chunk.runtime_deps
            dep_artifacts = set(artifacts[name] for name in dep_names)
            dep_artifacts.difference_update(chunk.artifacts)

            chunk.runtime_deps = dep_artifacts


resolver = RubyGemsResolver()

chunks = resolver.resolve_chunks_for_gems(goals)

graph_solver = beak.DependencyGraphSolver()
bootstrap_set, build_order = graph_solver.solve(chunks, goals)

# Create a shell script that installs bootstrap Gems manually.
with open('bootstrap.sh', 'w') as f:
    f.write('# Minimal set of Gems required to build all other dependencies\n'
            '# of: %s\n\n' % ', '.join(goals))
    for source in sorted(bootstrap_set, key=lambda s: s.name):
        runtime_deps = [a.name for a in source.runtime_deps]
        artifacts_str = ' '.join([a.name for a in source.artifacts])
        f.write('\n# Source: %s\n' % source.name)
        f.write('# Depends on: %s\n' % ', '.join(runtime_deps))
        f.write('gem install --ignore-dependencies %s\n' % artifacts_str)

stratum = beak.CreateStratum().create_stratum('rubytest', build_order, bootstrap_set)

with open('rubytest.morph', 'w') as f:
    yaml.safe_dump(stratum, f, encoding='utf-8', allow_unicode=True)
