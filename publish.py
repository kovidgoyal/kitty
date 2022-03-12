#!/usr/bin/env python3
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
from typing import IO, Any, Dict, Generator, Iterable, Optional, cast

import requests

os.chdir(os.path.dirname(os.path.abspath(__file__)))
docs_dir = os.path.abspath('docs')
publish_dir = os.path.abspath(os.path.join('..', 'kovidgoyal.github.io', 'kitty'))
building_nightly = False
with open('kitty/constants.py') as f:
    raw = f.read()
nv = re.search(r'^version: Version\s+=\s+Version\((\d+), (\d+), (\d+)\)', raw, flags=re.MULTILINE)
if nv is not None:
    version = f'{nv.group(1)}.{nv.group(2)}.{nv.group(3)}'
ap = re.search(r"^appname: str\s+=\s+'([^']+)'", raw, flags=re.MULTILINE)
if ap is not None:
    appname = ap.group(1)

ALL_ACTIONS = 'man html build tag sdist upload website'.split()
NIGHTLY_ACTIONS = 'man html build sdist upload_nightly'.split()


def echo_cmd(cmd: Iterable[str]) -> None:
    isatty = sys.stdout.isatty()
    end = '\n'
    if isatty:
        end = f'\x1b[m{end}'
        print('\x1b[92m', end='')
    print(shlex.join(cmd), end=end, flush=True)


def call(*cmd: str, cwd: Optional[str] = None, echo: bool = False) -> None:
    if len(cmd) == 1:
        q = shlex.split(cmd[0])
    else:
        q = list(cmd)
    if echo:
        echo_cmd(cmd)
    ret = subprocess.Popen(q, cwd=cwd).wait()
    if ret != 0:
        raise SystemExit(ret)


def run_build(args: Any) -> None:

    def run_with_retry(cmd: str) -> None:
        try:
            call(cmd, echo=True)
        except (SystemExit, Exception):
            needs_retry = 'arm64' in cmd or building_nightly
            if not needs_retry:
                raise
            print('Build failed, retrying in a few seconds...', file=sys.stderr)
            if 'macos' in cmd:
                call('python ../bypy macos shutdown')
            time.sleep(25)
            call(cmd, echo=True)

    for x in ('64', '32', 'arm64'):
        cmd = f'python ../bypy linux --arch {x} program'
        run_with_retry(cmd)
        call(f'python ../bypy linux --arch {x} shutdown', echo=True)
    cmd = 'python ../bypy macos program --sign-installers --notarize'
    run_with_retry(cmd)


def run_tag(args: Any) -> None:
    call('git push')
    call('git tag -s v{0} -m version-{0}'.format(version))
    call(f'git push origin v{version}')


def run_man(args: Any) -> None:
    call('make FAIL_WARN=1 man', cwd=docs_dir)


def run_html(args: Any) -> None:
    call('make FAIL_WARN=1 "OPTS=-D analytics_id=UA-20736318-2" dirhtml', cwd=docs_dir)
    add_old_redirects('docs/_build/dirhtml')


def generate_redirect_html(link_name: str, bname: str) -> None:
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


def add_old_redirects(loc: str) -> None:
    for dirpath, dirnames, filenames in os.walk(loc):
        if dirpath != loc:
            for fname in filenames:
                if fname == 'index.html':
                    bname = os.path.basename(dirpath)
                    base = os.path.dirname(dirpath)
                    link_name = os.path.join(base, f'{bname}.html') if base else f'{bname}.html'
                    generate_redirect_html(link_name, bname)

    old_unicode_input_path = os.path.join(loc, 'kittens', 'unicode-input')
    os.makedirs(old_unicode_input_path, exist_ok=True)
    generate_redirect_html(os.path.join(old_unicode_input_path, 'index.html'), '../unicode_input')
    generate_redirect_html(f'{old_unicode_input_path}.html', 'unicode_input')


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
    dest = f'{path}.sig'
    with suppress(FileNotFoundError):
        os.remove(dest)
    subprocess.check_call([
        os.environ['PENV'] + '/gpg-as-kovid', '--output', f'{path}.sig',
        '--detach-sig', path
    ])


def run_sdist(args: Any) -> None:
    with tempfile.TemporaryDirectory() as tdir:
        base = os.path.join(tdir, f'kitty-{version}')
        os.mkdir(base)
        subprocess.check_call(f'git archive HEAD | tar -x -C {base}', shell=True)
        dest = os.path.join(base, 'docs', '_build')
        os.mkdir(dest)
        for x in 'html man'.split():
            shutil.copytree(os.path.join(docs_dir, '_build', x), os.path.join(dest, x))
        dest = os.path.abspath(os.path.join('build', f'kitty-{version}.tar'))
        subprocess.check_call(['tar', '-cf', dest, os.path.basename(base)], cwd=tdir)
        with suppress(FileNotFoundError):
            os.remove(f'{dest}.xz')
        subprocess.check_call(['xz', '-9', dest])
        sign_file(f'{dest}.xz')


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

        frac = float(self.tell()) / self._total
        mb_pos = self.tell() / float(1024**2)
        mb_tot = self._total / float(1024**2)
        kb_pos = self.tell() / 1024.0
        kb_rate = kb_pos / (time.monotonic() - self.start_time)
        bit_rate = kb_rate * 1024
        eta = int((self._total - self.tell()) / bit_rate) + 1
        eta_m, eta_s = eta / 60, eta % 60
        if sys.stdout.isatty():
            write(
                f'\r\033[K\033[?7h {frac:%} {mb_pos:.1f}/{mb_tot:.1f}MB {kb_rate:.1f} KB/sec {eta_m} minutes, {eta_s} seconds left\033[?7l')
        if self.tell() >= self._total:
            t = int(time.monotonic() - self.start_time) + 1
            print(f'\nUpload took {t//60} minutes and {t%60} seconds at {kb_rate:.1f} KB/sec')
        sys.stdout.flush()


# }}}


class Base:  # {{{

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

    API = 'https://api.github.com'

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
        self.current_tag_name = self.version if self.version == 'nightly' else f'v{self.version}'
        self.is_nightly = self.current_tag_name == 'nightly'
        self.requests = s = requests.Session()
        s.auth = (self.username, self.password)
        s.headers.update({'Accept': 'application/vnd.github.v3+json'})
        self.url_base = f'{self.API}/repos/{self.username}/{self.reponame}/releases'

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
        url = f'{self.url_base}/{release_id}'
        now = str(datetime.datetime.utcnow()).split('.')[0] + ' UTC'
        try:
            with open('.git/refs/heads/master') as f:
                commit = f.read().strip()
        except FileNotFoundError:
            time.sleep(1)
            with open('.git/refs/heads/master') as f:
                commit = f.read().strip()
        self.patch(
            url, 'Failed to update nightly release description',
            body=f'Nightly release, generated on: {now} from commit: {commit}.'
            ' For how to install nightly builds, see: https://sw.kovidgoyal.net/kitty/binary/#customizing-the-installation'
        )

    def __call__(self) -> None:
        # self.clean_older_releases(releases)
        release = self.create_release()
        upload_url = release['upload_url'].partition('{')[0]
        asset_url = f'{self.url_base}/assets/{{}}'
        existing_assets = self.existing_assets(release['id'])
        if self.is_nightly:
            for fname in existing_assets:
                self.info(f'Deleting {fname} from GitHub')
                r = self.requests.delete(asset_url.format(existing_assets[fname]))
                if r.status_code not in (204, 404):
                    self.fail(r, f'Failed to delete {fname} from GitHub')
            self.update_nightly_description(release['id'])
        for path, desc in self.files.items():
            self.info('')
            fname = os.path.basename(path)
            if self.is_nightly:
                fname = fname.replace(version, 'nightly')
            if fname in existing_assets:
                self.info(f'Deleting {fname} from GitHub with id: {existing_assets[fname]}')
                r = self.requests.delete(asset_url.format(existing_assets[fname]))
                if r.status_code not in (204, 404):
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
                self.info(f'\nDeleting old released installers from: {release["tag_name"]}')
                for asset in release['assets']:
                    r = self.requests.delete(
                        f'{self.url_base}/assets/{asset["id"]}')
                    if r.status_code != 204:
                        self.fail(r, f'Failed to delete obsolete asset: {asset["name"]} for release: {release["tag_name"]}')

    def do_upload(self, url: str, path: str, desc: str, fname: str) -> requests.Response:
        mime_type = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
        self.info(f'Uploading to GitHub: {fname} ({mime_type})')
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
        print(msg, f' Status Code: {r.status_code}', file=sys.stderr)
        print('JSON from response:', file=sys.stderr)
        pprint.pprint(dict(r.json()), stream=sys.stderr)
        raise SystemExit(1)

    def already_exists(self, r: requests.Response) -> bool:
        error_code = r.json().get('errors', [{}])[0].get('code', None)
        return bool(error_code == 'already_exists')

    def existing_assets(self, release_id: str) -> Dict[str, str]:
        url = f'{self.url_base}/{release_id}/assets'
        r = self.requests.get(url)
        if r.status_code != 200:
            self.fail(r, 'Failed to get assets for release')
        return {asset['name']: asset['id'] for asset in r.json()}

    def create_release(self) -> Dict[str, Any]:
        ' Create a release on GitHub or if it already exists, return the existing release '
        # Check for existing release
        url = f'{self.url_base}/tags/{self.current_tag_name}'
        r = self.requests.get(url)
        if r.status_code == 200:
            return dict(r.json())
        if self.is_nightly:
            raise SystemExit('No existing nightly release found on GitHub')
        r = self.requests.post(
            self.url_base,
            data=json.dumps({
                'tag_name': self.current_tag_name,
                'target_commitish': 'master',
                'name': f'version {self.version}',
                'body': f'Release version {self.version}.'
                ' For changelog, see https://sw.kovidgoyal.net/kitty/changelog/'
                ' GPG key used for signing tarballs is: https://calibre-ebook.com/signatures/kovid.gpg',
                'draft': False,
                'prerelease': False
            }))
        if r.status_code != 201:
            self.fail(r, f'Failed to create release for version: {self.version}')
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
        'linux/64/dist/kitty-{}-x86_64.txz': 'Linux amd64 binary bundle',
        'linux/32/dist/kitty-{}-i686.txz': 'Linux x86 binary bundle',
        'linux/arm64/dist/kitty-{}-arm64.txz': 'Linux arm64 binary bundle',
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
        files[f'{path}.sig'] = desc
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
        raise SystemExit(f'You must be in the {branch} git branch')


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
        globals()[f'run_{action}'](args)
        os.chdir(cwd)


def main() -> None:
    global building_nightly
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
            building_nightly = True
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
            ans = input(f'Publish version \033[91m{version}\033[m (y/n): ')
        except KeyboardInterrupt:
            ans = 'n'
        if ans.lower() != 'y':
            return
    if actions == ['website']:
        actions.insert(0, 'html')
    exec_actions(actions, args)


if __name__ == '__main__':
    main()
