#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import io
import json
import mimetypes
import os
import pprint
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from typing import IO, Any, Dict, Iterable, List, Optional, cast

import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
docs_dir = os.path.abspath('docs')
publish_dir = os.path.abspath(os.path.join('..', 'kovidgoyal.github.io', 'kitty'))
with open('kitty/constants.py') as f:
    raw = f.read()
nv = re.search(r'^version: Version\s+=\s+Version\((\d+), (\d+), (\d+)\)', raw, flags=re.MULTILINE)
if nv is not None:
    version = '%s.%s.%s' % (nv.group(1), nv.group(2), nv.group(3))
ap = re.search(r"^appname: str\s+=\s+'([^']+)'", raw, flags=re.MULTILINE)
if ap is not None:
    appname = ap.group(1)

ALL_ACTIONS = 'man html build tag sdist upload website'.split()


def call(*cmd: str, cwd: Optional[str] = None) -> None:
    if len(cmd) == 1:
        q = shlex.split(cmd[0])
    else:
        q = list(cmd)
    ret = subprocess.Popen(q, cwd=cwd).wait()
    if ret != 0:
        raise SystemExit(ret)


def run_build(args: Any) -> None:
    call('python ../bypy linux program')
    call('python ../bypy linux 32 program')
    call('python ../bypy macos program --sign-installers --notarize')
    call('python ../bypy macos shutdown')


def run_tag(args: Any) -> None:
    call('git push')
    call('git tag -s v{0} -m version-{0}'.format(version))
    call('git push origin v{0}'.format(version))


def run_man(args: Any) -> None:
    call('make FAIL_WARN=-W man', cwd=docs_dir)


def run_html(args: Any) -> None:
    call('make FAIL_WARN=-W html', cwd=docs_dir)


def add_analytics() -> None:
    analytics = '''
<!-- Global site tag (gtag.js) - Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id=UA-20736318-2"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'UA-20736318-2');
</script>
'''
    for dirpath, firnames, filenames in os.walk(publish_dir):
        for fname in filenames:
            if fname.endswith('.html'):
                with open(os.path.join(dirpath, fname), 'r+b') as f:
                    html = f.read().decode('utf-8')
                    html = html.replace('<!-- kitty analytics placeholder -->', analytics, 1)
                    f.seek(0), f.truncate()
                    f.write(html.encode('utf-8'))


def run_docs(args: Any) -> None:
    subprocess.check_call(['make', 'docs'])


def run_website(args: Any) -> None:
    if os.path.exists(publish_dir):
        shutil.rmtree(publish_dir)
    shutil.copytree(os.path.join(docs_dir, '_build', 'html'), publish_dir)
    add_analytics()
    with open(os.path.join(publish_dir, 'current-version.txt'), 'w') as f:
        f.write(version)
    shutil.copy2(os.path.join(docs_dir, 'installer.sh'), publish_dir)
    installer = os.path.join(docs_dir, 'installer.py')
    subprocess.check_call([
        'python3', '-c', f"import runpy; runpy.run_path('{installer}', run_name='update_wrapper')",
        os.path.join(publish_dir, 'installer.sh')])
    os.chdir(os.path.dirname(publish_dir))
    subprocess.check_call(['git', 'add', 'kitty'])
    subprocess.check_call(['git', 'commit', '-m', 'kitty website updates'])
    subprocess.check_call(['git', 'push'])


def sign_file(path: str) -> None:
    subprocess.check_call([
        os.environ['PENV'] + '/gpg-as-kovid', '--output', path + '.sig',
        '--detach-sig', path
    ])


def run_sdist(args: Any) -> None:
    with tempfile.TemporaryDirectory() as tdir:
        base = os.path.join(tdir, f'kitty-{version}')
        os.mkdir(base)
        subprocess.check_call('git archive HEAD | tar -x -C ' + base, shell=True)
        dest = os.path.join(base, 'docs', '_build')
        os.mkdir(dest)
        for x in 'html man'.split():
            shutil.copytree(os.path.join(docs_dir, '_build', x), os.path.join(dest, x))
        dest = os.path.abspath(os.path.join('build', f'kitty-{version}.tar'))
        subprocess.check_call(['tar', '-cf', dest, os.path.basename(base)], cwd=tdir)
        with suppress(FileNotFoundError):
            os.remove(dest + '.xz')
        subprocess.check_call(['xz', '-9', dest])
        sign_file(dest + '.xz')


class ReadFileWithProgressReporting(io.FileIO):  # {{{
    def __init__(self, path: str):
        io.FileIO.__init__(self, path, 'rb')
        self.seek(0, os.SEEK_END)
        self._total = self.tell()
        self.seek(0)
        self.start_time = time.monotonic()

    def __len__(self) -> int:
        return self._total

    def read(self, size: int = -1) -> bytes:
        data = io.FileIO.read(self, size)
        if data:
            self.report_progress(len(data))
        return data

    def report_progress(self, size: int) -> None:
        def write(*args: str) -> None:
            print(*args, end='')

        write('\x1b[s\x1b[K')
        frac = float(self.tell()) / self._total
        mb_pos = self.tell() / float(1024**2)
        mb_tot = self._total / float(1024**2)
        kb_pos = self.tell() / 1024.0
        kb_rate = kb_pos / (time.monotonic() - self.start_time)
        bit_rate = kb_rate * 1024
        eta = int((self._total - self.tell()) / bit_rate) + 1
        eta_m, eta_s = eta / 60, eta % 60
        write(
            '  %.1f%%   %.1f/%.1fMB %.1f KB/sec    %d minutes, %d seconds left'
            % (frac * 100, mb_pos, mb_tot, kb_rate, eta_m, eta_s))
        write('\x1b[u')
        if self.tell() >= self._total:
            t = int(time.time() - self.start_time) + 1
            print('\nUpload took %d minutes and %d seconds at %.1f KB/sec' %
                  (t / 60, t % 60, kb_rate))
        sys.stdout.flush()


# }}}


class Base(object):  # {{{

    def info(self, *args: Any, **kwargs: Any) -> None:
        print(*args, **kwargs)
        sys.stdout.flush()

    def warn(self, *args: Any, **kwargs: Any) -> None:
        print('\n' + '_' * 20, 'WARNING', '_' * 20)
        print(*args, **kwargs)
        print('_' * 50)
        sys.stdout.flush()


# }}}


class GitHub(Base):  # {{{

    API = 'https://api.github.com/'

    def __init__(
        self,
        files: Dict[str, str],
        reponame: str,
        version: str,
        username: str,
        password: str,
        replace: bool = False
    ):
        self.files, self.reponame, self.version, self.username, self.password, self.replace = (
            files, reponame, version, username, password, replace)
        self.current_tag_name = 'v' + self.version
        self.requests = s = requests.Session()
        s.auth = (self.username, self.password)
        s.headers.update({'Accept': 'application/vnd.github.v3+json'})

    def __call__(self) -> None:
        releases = self.releases()
        # self.clean_older_releases(releases)
        release = self.create_release(releases)
        upload_url = release['upload_url'].partition('{')[0]
        existing_assets = self.existing_assets(release['id'])
        for path, desc in self.files.items():
            self.info('')
            url = self.API + 'repos/%s/%s/releases/assets/{}' % (self.username,
                                                                 self.reponame)
            fname = os.path.basename(path)
            if fname in existing_assets:
                self.info('Deleting %s from GitHub with id: %s' %
                          (fname, existing_assets[fname]))
                r = self.requests.delete(url.format(existing_assets[fname]))
                if r.status_code != 204:
                    self.fail(r, 'Failed to delete %s from GitHub' % fname)
            r = self.do_upload(upload_url, path, desc, fname)
            if r.status_code != 201:
                self.fail(r, 'Failed to upload file: %s' % fname)
            try:
                r = self.requests.patch(
                    url.format(r.json()['id']),
                    data=json.dumps({
                        'name': fname,
                        'label': desc
                    }))
            except Exception:
                time.sleep(15)
                r = self.requests.patch(
                    url.format(r.json()['id']),
                    data=json.dumps({
                        'name': fname,
                        'label': desc
                    }))
            if r.status_code != 200:
                self.fail(r, 'Failed to set label for %s' % fname)

    def clean_older_releases(self, releases: Iterable[Dict[str, Any]]) -> None:
        for release in releases:
            if release.get(
                    'assets',
                    None) and release['tag_name'] != self.current_tag_name:
                self.info('\nDeleting old released installers from: %s' %
                          release['tag_name'])
                for asset in release['assets']:
                    r = self.requests.delete(
                        self.API + 'repos/%s/%s/releases/assets/%s' % (
                            self.username, self.reponame, asset['id']))
                    if r.status_code != 204:
                        self.fail(
                            r,
                            'Failed to delete obsolete asset: %s for release: %s'
                            % (asset['name'], release['tag_name']))

    def do_upload(self, url: str, path: str, desc: str, fname: str) -> requests.Response:
        mime_type = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
        self.info('Uploading to GitHub: %s (%s)' % (fname, mime_type))
        with ReadFileWithProgressReporting(path) as f:
            return self.requests.post(
                url,
                headers={
                    'Content-Type': mime_type,
                    'Content-Length': str(f._total)
                },
                params={'name': fname},
                data=cast(IO[bytes], f))

    def fail(self, r: requests.Response, msg: str) -> None:
        print(msg, ' Status Code: %s' % r.status_code, file=sys.stderr)
        print("JSON from response:", file=sys.stderr)
        pprint.pprint(dict(r.json()), stream=sys.stderr)
        raise SystemExit(1)

    def already_exists(self, r: requests.Response) -> bool:
        error_code = r.json().get('errors', [{}])[0].get('code', None)
        return bool(error_code == 'already_exists')

    def existing_assets(self, release_id: str) -> Dict[str, str]:
        url = self.API + 'repos/%s/%s/releases/%s/assets' % (
            self.username, self.reponame, release_id)
        r = self.requests.get(url)
        if r.status_code != 200:
            self.fail(r, 'Failed to get assets for release')
        return {asset['name']: asset['id'] for asset in r.json()}

    def releases(self) -> List[Dict[str, Any]]:
        url = self.API + 'repos/%s/%s/releases' % (self.username, self.reponame
                                                   )
        r = self.requests.get(url)
        if r.status_code != 200:
            self.fail(r, 'Failed to list releases')
        return list(r.json())

    def create_release(self, releases: Iterable[Dict[str, str]]) -> Dict[str, Any]:
        ' Create a release on GitHub or if it already exists, return the existing release '
        for release in releases:
            # Check for existing release
            if release['tag_name'] == self.current_tag_name:
                return release
        url = self.API + 'repos/%s/%s/releases' % (self.username, self.reponame)
        r = self.requests.post(
            url,
            data=json.dumps({
                'tag_name': self.current_tag_name,
                'target_commitish': 'master',
                'name': 'version %s' % self.version,
                'body': f'Release version {self.version}.'
                ' For changelog, see https://sw.kovidgoyal.net/kitty/changelog.html'
                ' GPG key used for signing tarballs is: https://calibre-ebook.com/signatures/kovid.gpg',
                'draft': False,
                'prerelease': False
            }))
        if r.status_code != 201:
            self.fail(r, 'Failed to create release for version: %s' %
                      self.version)
        return dict(r.json())
# }}}


def get_github_data() -> Dict[str, str]:
    with open(os.environ['PENV'] + '/github-token') as f:
        un, pw = f.read().strip().split(':')
    return {'username': un, 'password': pw}


def run_upload(args: Any) -> None:
    files = {}
    signatures = {}
    for f, desc in {
        'macos/dist/kitty-{}.dmg': 'macOS dmg',
        'linux/64/sw/dist/kitty-{}-x86_64.txz': 'Linux amd64 binary bundle',
        'linux/32/sw/dist/kitty-{}-i686.txz': 'Linux x86 binary bundle',
    }.items():
        path = os.path.join('bypy', 'b', f.format(version))
        if not os.path.exists(path):
            raise SystemExit(f'The installer {path} does not exist')
        files[path] = desc
        signatures[path] = f'GPG signature for {desc}'
    files[f'build/kitty-{version}.tar.xz'] = 'Source code'
    files[f'build/kitty-{version}.tar.xz.sig'] = 'Source code GPG signature'
    for path, desc in signatures.items():
        sign_file(path)
        files[path + '.sig'] = desc
    for f in files:
        if not os.path.exists(f):
            raise SystemExit(f'The release artifact {f} does not exist')
    gd = get_github_data()
    gh = GitHub(files, appname, version, gd['username'], gd['password'])
    gh()


def require_git_master(branch: str = 'master') -> None:
    b = subprocess.check_output(['git', 'symbolic-ref', '--short', 'HEAD']).decode('utf-8').strip()
    if b != branch:
        raise SystemExit('You must be in the {} git branch'.format(branch))


def require_penv() -> None:
    if 'PENV' not in os.environ:
        raise SystemExit('The PENV env var is not present, required for uploading releases')


def main() -> None:
    require_git_master()
    require_penv()
    parser = argparse.ArgumentParser(description='Publish kitty')
    parser.add_argument(
        '--only',
        default=False,
        action='store_true',
        help='Only run the specified action, by default the specified action and all sub-sequent actions are run')
    parser.add_argument(
        'action',
        default='all',
        nargs='?',
        choices=list(ALL_ACTIONS) + ['all'],
        help='The action to start with')
    args = parser.parse_args()
    if args.action == 'all':
        actions = list(ALL_ACTIONS)
    else:
        idx = ALL_ACTIONS.index(args.action)
        actions = ALL_ACTIONS[idx:]
    if args.only:
        del actions[1:]
    else:
        try:
            ans = input('Publish version \033[91m{}\033[m (y/n): '.format(version))
        except KeyboardInterrupt:
            ans = 'n'
        if ans.lower() != 'y':
            return
    if actions == ['website']:
        actions.insert(0, 'docs')
    for action in actions:
        print('Running', action)
        cwd = os.getcwd()
        globals()['run_' + action](args)
        os.chdir(cwd)


if __name__ == '__main__':
    main()
