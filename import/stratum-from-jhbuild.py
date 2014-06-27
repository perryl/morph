# This could be written a lot more clearly using a decent Python XML module...

import requests
import requests_cache
import yaml

import beak

import logging
import xml.dom.minidom
from itertools import chain
from logging import debug


version = '3.14'

modulesets = [
    'gnome-apps',
    'gnome-suites-core',
    'gnome-suites-core-deps',
    'gnome-world',
]

ignore_list = set([
    # systembuild-deps (listed as dependencies but not actual jhbuild modules)
    # FIXME: must be a better trick here than just ignoring them: we should be
    # able to ignore anything that's a sysdep.
    'bison', 'flex', 'gl', 'libdb', 'libffi', 'libjpeg', 'libpng',
    'libtiff', 'libtool-ltdl', 'libusb1', 'libuuid', 'libvorbis',
    'libXcomposite',
    'libXft', 'libXinerama', 'libxkbfile', 'libXrandr',
    'pam', 'python-devel', 'xcb-util', 'xkeyboard-config',
    'zlib',

    # things we don't actually have in Baserock but also disable
    'ppp', 'wireless-tools',

    # In foundation / Gtk+ under different names
    'expat',
    'gtk-doc',
    'gudev',

    # Nonsense
    'ConsoleKit',
    'gnome-packagekit',
    'gnome-screensaver',
    'PackageKit',

    # Keeps the dependencies down for now, we will probably need it later
    'gnome-control-center',

    # I'd like to keep a11y stuff in wherever possible, but this is big
    'mousetweaks',

    'avahi',
    'telepathy-mission-control',

    # Requires WebKit, which requires Gtk+-2, generally not want.
    # We need to configure evolution-data-server with --disable-goa.
    'gnome-online-accounts',

    # Conditional dep of gnome-settings-daemon, not useful in embedded
    'libwacom',

    # Don't want
    'bluez',
])


logging.basicConfig(level=logging.DEBUG)

requests_cache.install_cache('jhbuild_cache')


class JhbuildModulesets(object):
    def __init__(self):
        moduleset_url_pattern = \
            'https://git.gnome.org/browse/jhbuild/plain/modulesets/%s-%s.modules'

        self.chunks = {}
        self.metamodule_deps = {}

        repo_dict = {}
        for moduleset in modulesets:
            url = moduleset_url_pattern % (moduleset, version)
            debug('Requesting %s' % url)
            r = requests.get(url)

            chunks, metamodule_deps = self.parse_jhbuild_moduleset(
                repo_dict, r.text)

            self.chunks.update(chunks)
            self.metamodule_deps.update(metamodule_deps)

        # Convert the dependencies from being lists of names to being the
        # actual artifact objects. Also, create the artifact objects.
        for chunk in self.chunks.itervalues():
            # Temporary!
            assert chunk.build_deps == chunk.runtime_deps

            dep_artifacts = set()
            for name in chunk.build_deps:
                if name in chunks:
                    dep_artifacts.update(chunks[name].artifacts)
                else:
                    print 'Unknown dep: %s' % name
            chunk.build_deps = dep_artifacts
            chunk.runtime_deps = dep_artifacts

    def jhbuild_to_morph_repo(self, repo_dict, repo, module):
        if repo == 'git.gnome.org':
            return "gnome:%s" % module

        if repo in repo_dict:
            repo_href = repo_dict[repo]
            if repo_href.startswith('git://anongit.freedesktop.org/'):
                return "freedesktop:%s" % (repo_href[30:] + module)
            else:
                return repo_dict[repo] + '/' + module

        print "%s: Unknown repo: %s" % (module, repo)
        return None

    def parse_jhbuild_moduleset(self, repo_dict, text):
        chunks = {}
        metamodule_deps = {}

        def get_element_by_tag_name(parent, tagname):
            element_list = parent.getElementsByTagName(tagname)
            if len(element_list) > 1:
                raise Exception('Multiple %s entries found in %s' % (tagname,
                                                                     parent))
            if len(element_list) == 0:
                return None
            return element_list[0]

        dom = xml.dom.minidom.parseString(text)
        base = get_element_by_tag_name(dom, "moduleset")

        def parse_repository_entries():
            repo_dict = {}
            default_repo = None
            for repo in base.getElementsByTagName("repository"):
                # FIXME: should lorry these things ...
                if repo.getAttribute("type") != "git":
                    continue

                name = repo.getAttribute("name")
                href = repo.getAttribute("href")
                repo_dict[name] = href

                if repo.getAttribute("default") == "yes":
                    default_repo = name
            return repo_dict, default_repo

        repo_dict, default_repo = parse_repository_entries()

        def parse_module_deps(deps_node):
            dependencies = set()
            for component in deps_node.getElementsByTagName("dep"):
                dep_name = component.getAttribute("package")
                dependencies.add(dep_name)
            return dependencies

        def parse_module(module_node):
            name = module_node.getAttribute("id")

            if module_node.getAttribute("supports-parallel-builds") == "no":
                print "%s: no parallel builds" % name

            deps_node = get_element_by_tag_name(module_node, "dependencies")
            dependencies = parse_module_deps(deps_node) if deps_node else []

            branch = get_element_by_tag_name(module_node, "branch")
            if branch is None:
                print 'No branch for %s!' % name
                return None

            for p in branch.getElementsByTagName("patch"):
                print "%s: patch: %s" % (name, p.getAttribute("file"))
            repo_str = branch.getAttribute("repo") or default_repo
            module = branch.getAttribute("module") or name

            repo = self.jhbuild_to_morph_repo(repo_dict, repo_str, name)

            # FIXME: assuming runtime-deps == build-time deps, really?
            return beak.Source(name, repo, None, dependencies, dependencies)

        # FIXME: I guess you're ignoring some build-system types here, you
        # should warn the user!
        modules = chain(
            base.getElementsByTagName("autotools"),
            base.getElementsByTagName("tarball"),
            base.getElementsByTagName("cmake"))

        for module_element in modules:
            chunk = parse_module(module_element)
            if chunk is not None:
                chunks[chunk.name] = chunk
                artifact = beak.Artifact(chunk.name, chunk)
                chunk.add_artifact(artifact)

        for element in base.getElementsByTagName("metamodule"):
            name = element.getAttribute("id")
            dependencies_node = get_element_by_tag_name(
                element, "dependencies")
            deps = parse_module_deps(dependencies_node)

            metamodule_deps[name] = deps

        return chunks, metamodule_deps

    def chunks_for_metamodule(self, metamodule):
        return self.metamodule_deps[metamodule]


jhbuild = JhbuildModulesets()

graph_solver = beak.DependencyGraphSolver()

goals = jhbuild.chunks_for_metamodule('meta-gnome-core-shell')
bootstrap_set, build_order = graph_solver.solve(jhbuild.chunks, goals)
print bootstrap_set
print build_order

stratum = beak.CreateStratum().create_stratum('gnome', build_order, bootstrap_set)
import sys
yaml.safe_dump(stratum, sys.stdout, encoding='utf-8', allow_unicode=True)
