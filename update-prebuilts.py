#!/usr/bin/env python
#
# Copyright (C) 2015 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Update the prebuilt GCC from the build server."""
from __future__ import print_function

import argparse
import inspect
import os
import shutil
import subprocess
import sys


THIS_DIR = os.path.realpath(os.path.dirname(__name__))
ANDROID_DIR = os.path.realpath(os.path.join(THIS_DIR, '../..'))

BRANCH = 'aosp-gcc'


def android_path(*args):
    return os.path.join(ANDROID_DIR, *args)


class ArgParser(argparse.ArgumentParser):
    def __init__(self):
        super(ArgParser, self).__init__(
            description=inspect.getdoc(sys.modules[__name__]))

        self.add_argument(
            'build', metavar='BUILD',
            help='Build number to pull from the build server.')

        self.add_argument(
            '--dryrun', action='store_true',
            help='Dry run mode: echo commands but do not execute them.')

        self.add_argument(
            '--use-current-branch', action='store_true',
            help='Do not repo start a new branch for the update.')

        self.add_argument(
            '--cachedir', metavar='CACHEDIR',
            help='Draw build artifacts from cache dir.')

        self.add_argument(
            '--message', '-m', metavar='MESSAGE',
            help='Override the git commit message.')


def build_target(host, arch):
    """Gets the toolchain build target name for the specified host and arch.

    The builds targets are named by combining the host and arch values.

    >>> build_target('darwin', 'arm')
    'arm_mac'

    >>> build_target('darwin', 'aarch64')
    'arm64_mac'

    >>> build_target('linux', 'x86')
    'linux_x86'
    """
    build_arch = arch
    if arch == 'aarch64':
        build_arch = 'arm64'

    if host == 'darwin':
        return build_arch + '_mac'

    return host + '_' + build_arch


def package_name(host, arch):
    """Returns the file name for a given package configuration.

    >>> package_name('linux', 'arm')
    'gcc-arm-linux-x86_64.tar.bz2'

    >>> package_name('linux', 'aarch64')
    'gcc-arm64-linux-x86_64.tar.bz2'

    >>> package_name('darwin', 'x86')
    'gcc-x86-darwin-x86_64.tar.bz2'
    """
    build_arch = arch
    if arch == 'aarch64':
        build_arch = 'arm64'
    return 'gcc-{}-{}-x86_64.tar.bz2'.format(build_arch, host)


def invoke_cmd(dryrun, cmds, outfile=None):
    """Invoke specified command (or echo command if dry-run mode)."""
    if dryrun:
        print('cmd: %s' % ' '.join(cmds))
        return
    subprocess.check_call(cmds, stdout=outfile)


def download_build(host, arch, build_number, download_dir, dryrun, cachedir):
    """Download a specific build artifact."""
    pkg_name = package_name(host, arch)
    if cachedir:
        cached_pkg = os.path.join(cachedir, pkg_name)
        if os.path.exists(cached_pkg):
            print('Reusing existing copy of {} from '
                  '{}'.format(pkg_name, cachedir))
            return cached_pkg

    out_file_path = os.path.join(download_dir, pkg_name)
    print('Downloading {} to {}'.format(pkg_name, out_file_path))
    invoke_cmd(dryrun,
               ['/google/data/ro/projects/android/fetch_artifact',
                '--branch={}'.format(BRANCH),
                '--bid={}'.format(build_number),
                '--target={}'.format(build_target(host, arch)),
                pkg_name, out_file_path])
    return out_file_path


def extract_package(package, install_dir, dryrun):
    # The --strip-components is needed because the git project is in
    # prebuilts/gcc/$HOST/$ARCH/$TRIPLE, rather than a directory above that
    # like it really should have been.
    cmd = ['tar', 'xf', package, '-C', install_dir, '--strip-components=1']
    print('Extracting {}...'.format(package))
    invoke_cmd(dryrun, cmd)


def delete_old_toolchain(path, dryrun):
    print('Removing old files in {}...'.format(path))
    invoke_cmd(dryrun, ['git', '-C', path,
                        'rm', '-rf', '--ignore-unmatch', '.'])

    # Git doesn't believe in directories, so `git rm -rf` might leave behind
    # empty directories.
    invoke_cmd(dryrun, ['git', '-C', path, 'clean', '-df'])


def get_prebuilt_arch(arch):
    return {
        'arm': 'arm',
        'aarch64': 'aarch64',
        'mips64': 'mips',
        'x86_64': 'x86',
    }[arch]


def get_triple(arch):
    triple_arch = arch
    if arch == 'mips64':
        triple_arch = 'mips64el'

    triple = '{}-linux-android'.format(triple_arch)
    if arch == 'arm':
        triple += 'eabi'

    return triple


def get_prebuilt_subdir(host, arch):
    """Returns the install path for a GCC prebuilt relative to the root.

    Thanks to historical project naming conventions, these paths are a little
    non-obvious. The toolchains are installed to paths such as:
    "prebuilts/gcc/$HOST/$ARCH/$TRIPLE-$VERSION", but $ARCH isn't the arch
    you'd expect for anything but the two ARMs.

    For x86 and mips, we use a multilib toolchain. In other words, we don't
    have both an x86 and x86_64 toolchain, we have just the x86_64 toolchain.
    Unfortunately, the install path for the x86_64 toolchain is
    prebuilts/gcc/$HOST/x86/x86_64-linux-android, because reasons.

    >>> get_prebuilt_subdir('linux-x86', 'arm')
    'prebuilts/gcc/linux-x86/arm/arm-linux-androideabi-4.9'

    >>> get_prebuilt_subdir('linux-x86', 'aarch64')
    'prebuilts/gcc/linux-x86/aarch64/aarch64-linux-android-4.9'

    >>> get_prebuilt_subdir('linux-x86', 'x86_64')
    'prebuilts/gcc/linux-x86/x86/x86_64-linux-android-4.9'

    >>> get_prebuilt_subdir('linux-x86', 'mips64')
    'prebuilts/gcc/linux-x86/mips/mips64el-linux-android-4.9'

    >>> get_prebuilt_subdir('darwin-x86', 'mips64')
    'prebuilts/gcc/darwin-x86/mips/mips64el-linux-android-4.9'
    """

    prebuilt_arch = get_prebuilt_arch(arch)
    triple = get_triple(arch) + '-4.9'

    return os.path.join('prebuilts/gcc', host, prebuilt_arch, triple)


# This is a separate function from get_prebuilt_subdir just to simplify the
# doctests (no need to know absolute path).
def get_prebuilt_path(host, arch):
    return android_path(get_prebuilt_subdir(host, arch))


def generate_androidkernel_symlinks(arch, prebuilt_dir, dryrun):
    """Generate an -androidkernel toolchain.

    The kernel doesn't correctly link with gold, the default on x86 and ARM.
    Generate a fake toolchain consisting of symlinks, with ld pointing to bfd.
    """

    files = {
        'ar': 'ar',
        'as': 'as',
        'size': 'size',
        'strip': 'strip',
        'nm': 'nm',
        'cpp': 'cpp',
        'ld': 'ld.bfd',
        'gcc': 'gcc',
        'objcopy': 'objcopy',
        'objdump': 'objdump',
        'readelf': 'readelf',
    }

    original_triple = get_triple(arch)
    new_triple = original_triple + "kernel"

    if arch == 'arm':
        # We don't want arm-linux-androideabikernel.
        new_triple = 'arm-linux-androidkernel'

    bin_dir = os.path.join(prebuilt_dir, 'bin')
    src_prefix = '{}-'.format(original_triple)
    link_prefix = '{}-'.format(new_triple)
    for link, src in files.iteritems():
        link_path = os.path.join(bin_dir, link_prefix + link)
        src_path = src_prefix + src

        if dryrun:
            print('ln -s {} {}'.format(src_path, link_path))
        else:
            # Make sure our symlink actually points to something.
            full_path = os.path.join(bin_dir, src_path)
            if not os.path.exists(full_path):
                sys.exit("ERROR: missing file '{}'".format(full_path))

            os.symlink(src_path, link_path)


def update_gcc(host, arch, build_number, use_current_branch,
               dryrun, download_dir, message, cachedir):
    host_tag = host + '-x86'
    prebuilt_dir = get_prebuilt_path(host_tag, arch)
    if dryrun:
        print('cd %s' % prebuilt_dir)
    os.chdir(prebuilt_dir)

    if not use_current_branch:
        invoke_cmd(dryrun,
                   ['repo', 'start',
                    'update-gcc-{}'.format(build_number), '.'])

    package = download_build(host, arch, build_number,
                             download_dir, dryrun, cachedir)

    # Remove the old toolchain so we know the package we're building isn't
    # missing anything.
    delete_old_toolchain(prebuilt_dir, dryrun)
    extract_package(package, prebuilt_dir, dryrun)
    generate_androidkernel_symlinks(arch, prebuilt_dir, dryrun)

    print('Adding files to index...')
    invoke_cmd(dryrun, ['git', 'add', '.'])

    print('Committing update...')
    if message is not None:
        message = message.decode('string_escape')
    else:
        message = 'Update prebuilt GCC to build {}.'.format(build_number)
    invoke_cmd(dryrun, ['git', 'commit', '-m', message])


def main():
    args = ArgParser().parse_args()

    download_dir = os.path.realpath('.download')
    if os.path.isdir(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    try:
        hosts = ('linux', 'darwin')
        arches = ('arm', 'aarch64', 'x86_64')
        for host in hosts:
            for arch in arches:
                update_gcc(host, arch, args.build, args.use_current_branch,
                           args.dryrun, download_dir, args.message,
                           args.cachedir)

    finally:
        shutil.rmtree(download_dir)


if __name__ == '__main__':
    main()
