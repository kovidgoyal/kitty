#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import datetime
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
from contextlib import contextmanager, suppress
from typing import IO, Any, Dict, Generator, Iterable, List, Optional, cast

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
NIGHTLY_ACTIONS = 'man html build upload_nightly'.split()


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
    call('make FAIL_WARN=-W "OPTS=-D analytics_id=UA-20736318-2" dirhtml', cwd=docs_dir)
    add_old_redirects('docs/_build/dirhtml')


def add_old_redirects(loc: str) -> None:
    for dirpath, dirnames, filenames in os.walk(loc):
        if dirpath != loc:
            for fname in filenames:
                if fname == 'index.html':
                    bname = os.path.basename(dirpath)
                    base = os.path.dirname(dirpath)
                    link_name = os.path.join(base, f'{bname}.html') if base else f'{bname}.html'
                    with open(link_name, 'w') as f:
                        f.write(f'''
<html>
<head>
<title>Redirecting...</title>
<link rel="canonical" href="{bname}/" />
<noscript>
<meta http-equiv="refresh" content="0;url={bname}/" />
</noscript>
<script type="text/javascript">
window.location.replace('./{bname}/' + window.location.hash);
</script>
</head>
<body>
<p>Redirecting, please wait...</p>
</body>
</html>
''')


def run_docs(args: Any) -> None:
    subprocess.check_call(['make', 'docs'])


def run_website(args: Any) -> None:
    if os.path.exists(publish_dir):
        shutil.rmtree(publish_dir)
    shutil.copytree(os.path.join(docs_dir, '_build', 'dirhtml'), publish_dir, symlinks=True)
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
    dest = path + '.sig'
    with suppress(FileNotFoundError):
        os.remove(dest)
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
        self.current_tag_name = self.version if self.version == 'nightly' else ('v' + self.version)
        self.is_nightly = self.current_tag_name == 'nightly'
        self.requests = s = requests.Session()
        s.auth = (self.username, self.password)
        s.headers.update({'Accept': 'application/vnd.github.v3+json'})
        self.url_base = self.API + f'repos/{self.username}/{self.reponame}/releases/'

    def patch(self, url: str, fail_msg: str, **data: Any) -> None:
        rdata = json.dumps(data)
        try:
            r = self.requests.patch(url, data=rdata)
        except Exception:
            time.sleep(15)
            r = self.requests.patch(url, data=rdata)
        if r.status_code != 200:
            self.fail(r, fail_msg)

    def update_nightly_description(self, release_id: int) -> None:
        url = self.url_base + str(release_id)
        now = str(datetime.datetime.utcnow()).split('.')[0] + ' UTC'
        with open('.git/refs/heads/master') as f:
            commit = f.read().strip()
        self.patch(url, 'Failed to update nightly release description',
                   body=f'Nightly release, generated on: {now} from commit: {commit}')

    def __call__(self) -> None:
        releases = self.releases()
        # self.clean_older_releases(releases)
        release = self.create_release(releases)
        upload_url = release['upload_url'].partition('{')[0]
        asset_url = self.url_base + 'assets/{}'
        existing_assets = self.existing_assets(release['id'])
        if self.is_nightly:
            for fname in existing_assets:
                self.info(f'Deleting {fname} from GitHub')
                r = self.requests.delete(asset_url.format(existing_assets[fname]))
                if r.status_code != 204:
                    self.fail(r, 'Failed to delete %s from GitHub' % fname)
            self.update_nightly_description(release['id'])
        for path, desc in self.files.items():
            self.info('')
            fname = os.path.basename(path)
            if self.is_nightly:
                fname = fname.replace(version, 'nightly')
            if fname in existing_assets:
                self.info(f'Deleting {fname} from GitHub with id: {existing_assets[fname]}')
                r = self.requests.delete(asset_url.format(existing_assets[fname]))
                if r.status_code != 204:
                    self.fail(r, f'Failed to delete {fname} from GitHub')
            r = self.do_upload(upload_url, path, desc, fname)
            if r.status_code != 201:
                self.fail(r, f'Failed to upload file: {fname}')
            self.patch(asset_url.format(r.json()['id']), f'Failed to set label for {fname}', name=fname, label=desc)

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
        if self.is_nightly:
            raise SystemExit('No existing nightly release found on GitHub')
        url = self.API + 'repos/%s/%s/releases' % (self.username, self.reponame)
        r = self.requests.post(
            url,
            data=json.dumps({
                'tag_name': self.current_tag_name,
                'target_commitish': 'master',
                'name': 'version %s' % self.version,
                'body': f'Release version {self.version}.'
                ' For changelog, see https://sw.kovidgoyal.net/kitty/changelog/'
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


def files_for_upload() -> Dict[str, str]:
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
    return files


def run_upload(args: Any) -> None:
    gd = get_github_data()
    files = files_for_upload()
    gh = GitHub(files, appname, version, gd['username'], gd['password'])
    gh()


def run_upload_nightly(args: Any) -> None:
    subprocess.check_call(['git', 'tag', '-f', 'nightly'])
    subprocess.check_call(['git', 'push', 'origin', 'nightly', '-f'])
    gd = get_github_data()
    files = files_for_upload()
    gh = GitHub(files, appname, 'nightly', gd['username'], gd['password'])
    gh()


def current_branch() -> str:
    return subprocess.check_output(['git', 'symbolic-ref', '--short', 'HEAD']).decode('utf-8').strip()


def require_git_master(branch: str = 'master') -> None:
    if current_branch() != branch:
        raise SystemExit('You must be in the {} git branch'.format(branch))


def safe_read(path: str) -> str:
    with suppress(FileNotFoundError):
        with open(path) as f:
            return f.read()
    return ''


@contextmanager
def change_to_git_master() -> Generator[None, None, None]:
    stash_ref_before = safe_read('.git/refs/stash')
    subprocess.check_call(['git', 'stash'])
    try:
        branch_before = current_branch()
        if branch_before != 'master':
            subprocess.check_call(['git', 'switch', 'master'])
        try:
            yield
        finally:
            if branch_before != 'master':
                subprocess.check_call(['git', 'switch', branch_before])
    finally:
        if stash_ref_before != safe_read('.git/refs/stash'):
            subprocess.check_call(['git', 'stash', 'pop'])


def require_penv() -> None:
    if 'PENV' not in os.environ:
        raise SystemExit('The PENV env var is not present, required for uploading releases')


def exec_actions(actions: Iterable[str], args: Any) -> None:
    for action in actions:
        print('Running', action)
        cwd = os.getcwd()
        globals()['run_' + action](args)
        os.chdir(cwd)


def main() -> None:
    parser = argparse.ArgumentParser(description='Publish kitty')
    parser.add_argument(
        '--only',
        default=False,
        action='store_true',
        help='Only run the specified action, by default the specified action and all sub-sequent actions are run')
    parser.add_argument(
        '--nightly',
        default=False,
        action='store_true',
        help='Upload a nightly release, ignores all other arguments')
    parser.add_argument(
        'action',
        default='all',
        nargs='?',
        choices=list(ALL_ACTIONS) + ['all', 'upload_nightly'],
        help='The action to start with')
    args = parser.parse_args()
    require_penv()
    if args.nightly:
        with change_to_git_master():
            exec_actions(NIGHTLY_ACTIONS, args)
        return
    require_git_master()
    if args.action == 'all':
        actions = list(ALL_ACTIONS)
    elif args.action == 'upload_nightly':
        actions = ['upload_nightly']
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
        actions.insert(0, 'html')
    exec_actions(actions, args)


if __name__ == '__main__':
    main()
