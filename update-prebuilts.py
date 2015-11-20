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
            '--use-current-branch', action='store_true',
            help='Do not repo start a new branch for the update.')


def host_to_build_host(host):
    """Gets the build host name for an NDK host tag.

    The Windows builds are done from Linux.
    """
    return {
        'darwin': 'mac',
        'linux': 'linux',
        'windows': 'linux',
    }[host]


def build_name(host, arch):
    """Gets the release build name for an NDK host tag.

    The builds are named by a short identifier like "linux" or "win64".

    >>> build_name('darwin', 'arm')
    'arm'

    >>> build_name('darwin', 'aarch64')
    'arm64'

    >>> build_name('linux', 'x86')
    'linux_x86'
    """
    build_arch = arch
    if arch == 'aarch64':
        build_arch = 'arm64'

    if host == 'darwin':
        return build_arch

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


def download_build(host, arch, build_number, download_dir):
    url_base = 'https://android-build-uber.corp.google.com'
    path = 'builds/{branch}-{build_host}-{build_name}/{build_num}'.format(
        branch=BRANCH,
        build_host=host_to_build_host(host),
        build_name=build_name(host, arch),
        build_num=build_number)

    pkg_name = package_name(host, arch)
    url = '{}/{}/{}'.format(url_base, path, pkg_name)

    TIMEOUT = '60'  # In seconds.
    out_file_path = os.path.join(download_dir, pkg_name)
    with open(out_file_path, 'w') as out_file:
        print('Downloading {} to {}'.format(url, out_file_path))
        subprocess.check_call(
            ['sso_client', '--location', '--request_timeout', TIMEOUT, url],
            stdout=out_file)
    return out_file_path


def extract_package(package, install_dir):
    # The --strip-components is needed because the git project is in
    # prebuilts/gcc/$HOST/$ARCH/$TRIPLE, rather than a directory above that
    # like it really should have been.
    cmd = ['tar', 'xf', package, '-C', install_dir, '--strip-components=1']
    print('Extracting {}...'.format(package))
    subprocess.check_call(cmd)


def delete_old_toolchain(path):
    print('Removing old files in {}...'.format(path))
    subprocess.check_call(
        ['git', '-C', path, 'rm', '-rf', '--ignore-unmatch', '.'])

    # Git doesn't believe in directories, so `git rm -rf` might leave behind
    # empty directories.
    subprocess.check_call(['git', '-C', path, 'clean', '-df'])


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
    prebuilt_arch = {
        'arm': 'arm',
        'aarch64': 'aarch64',
        'mips64': 'mips',
        'x86_64': 'x86',
    }[arch]

    triple_arch = arch
    if arch == 'mips64':
        triple_arch = 'mips64el'

    triple = '{}-linux-android'.format(triple_arch)
    if arch == 'arm':
        triple += 'eabi'
    triple += '-4.9'

    return os.path.join('prebuilts/gcc', host, prebuilt_arch, triple)


# This is a separate function from get_prebuilt_subdir just to simplify the
# doctests (no need to know absolute path).
def get_prebuilt_path(host, arch):
    return android_path(get_prebuilt_subdir(host, arch))


def update_gcc(host, arch, build_number, use_current_branch, download_dir):
    host_tag = host + '-x86'
    prebuilt_dir = get_prebuilt_path(host_tag, arch)
    os.chdir(prebuilt_dir)

    if not use_current_branch:
        subprocess.check_call(
            ['repo', 'start', 'update-gcc-{}'.format(build_number), '.'])

    package = download_build(host, arch, build_number, download_dir)

    # Remove the old toolchain so we know the package we're building isn't
    # missing anything.
    delete_old_toolchain(prebuilt_dir)
    extract_package(package, prebuilt_dir)

    print('Adding files to index...')
    subprocess.check_call(['git', 'add', '.'])

    print('Committing update...')
    message = 'Update prebuilt GCC to build {}.'.format(build_number)
    subprocess.check_call(['git', 'commit', '-m', message])


def main():
    args = ArgParser().parse_args()

    download_dir = os.path.realpath('.download')
    if os.path.isdir(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    try:
        hosts = ('darwin', 'linux')
        arches = ('arm', 'aarch64', 'mips64', 'x86_64')
        for host in hosts:
            for arch in arches:
                update_gcc(host, arch, args.build, args.use_current_branch,
                           download_dir)
    finally:
        shutil.rmtree(download_dir)


if __name__ == '__main__':
    main()
