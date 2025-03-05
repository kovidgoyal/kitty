#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import base64
import contextlib
import datetime
import glob
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
from http.client import HTTPResponse, HTTPSConnection
from typing import Any, Callable, Dict, Generator, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlencode, urlparse

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

ALL_ACTIONS = 'local_build man html build tag sdist upload website'.split()
NIGHTLY_ACTIONS = 'local_build man html build sdist upload_nightly'.split()


def echo_cmd(cmd: Iterable[str]) -> None:
    isatty = sys.stdout.isatty()
    end = '\n'
    if isatty:
        end = f'\x1b[m{end}'
        print('\x1b[32m', end='')  # ]]]]]
    print(shlex.join(cmd), end=end, flush=True)


def call(*cmd: str, cwd: Optional[str] = None, echo: bool = False, timeout: float | None = None) -> None:
    if len(cmd) == 1:
        q = shlex.split(cmd[0])
    else:
        q = list(cmd)
    if echo:
        echo_cmd(cmd)
    p = subprocess.Popen(q, cwd=cwd)
    try:
        ret = p.wait(timeout)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            p.wait(1)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        raise
    if ret != 0:
        raise SystemExit(ret)


def run_local_build(args: Any) -> None:
    call('make debug')


def run_build(args: Any) -> None:
    import runpy

    m = runpy.run_path('./setup.py', run_name='__publish__')
    vcs_rev: str = m['get_vcs_rev']()

    def run_with_retry(cmd: str, timeout: float | None = 20 * 60 ) -> None:
        try:
            call(cmd, echo=True, timeout=timeout)
        except (SystemExit, Exception):
            needs_retry = building_nightly and 'linux' not in cmd
            if not needs_retry:
                raise
            print('Build failed, retrying in a minute seconds...', file=sys.stderr)
            if 'macos' in cmd:
                call('python ../bypy macos shutdown')
            time.sleep(60)
            call(cmd, echo=True, timeout=timeout)

    for x in ('64', 'arm64'):
        prefix = f'python ../bypy linux --arch {x} '
        run_with_retry(prefix + f'program --non-interactive --extra-program-data "{vcs_rev}"')
    run_with_retry(f'python ../bypy macos program --sign-installers --notarize --non-interactive --extra-program-data "{vcs_rev}"')
    call('python ../bypy macos shutdown', echo=True)
    call('make debug')
    call('./setup.py build-static-binaries')


def run_tag(args: Any) -> None:
    call('git push')
    call('git tag -s v{0} -m version-{0}'.format(version))
    call(f'git push origin v{version}')


def run_man(args: Any) -> None:
    call('make FAIL_WARN=1 man', cwd=docs_dir)


def run_html(args: Any) -> None:
    # Force a fresh build otherwise the search index is not correct
    with suppress(FileNotFoundError):
        shutil.rmtree(os.path.join(docs_dir, '_build', 'dirhtml'))
    call('make FAIL_WARN=1 "OPTS=-D analytics_id=G-XTJK3R7GF2" dirhtml', cwd=docs_dir)
    add_old_redirects('docs/_build/dirhtml')

    with suppress(FileNotFoundError):
        shutil.rmtree(os.path.join(docs_dir, '_build', 'html'))
    call('make FAIL_WARN=1 "OPTS=-D analytics_id=G-XTJK3R7GF2" html', cwd=docs_dir)


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
    os.chdir(os.path.dirname(publish_dir))
    subprocess.check_call(['optipng', '-o7'] + glob.glob('kitty/_images/social_previews/*.png'))
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
        super().__init__(path, 'rb')
        self.seek(0, os.SEEK_END)
        self._total = self.tell()
        self.seek(0)
        self.start_time = time.monotonic()
        print('Starting upload of:', os.path.basename(path), 'size:', self._total)

    def __len__(self) -> int:
        return self._total

    def read(self, size: Optional[int] = -1) -> bytes:
        data = io.FileIO.read(self, size)
        if data:
            self.report_progress(len(data))
        return data

    def report_progress(self, size: int) -> None:
        def write(*args: str) -> None:
            print(*args, end='')

        frac = int(self.tell() * 100 / self._total)
        mb_pos = self.tell() / float(1024**2)
        mb_tot = self._total / float(1024**2)
        kb_pos = self.tell() / 1024.0
        kb_rate = kb_pos / (time.monotonic() - self.start_time)
        bit_rate = kb_rate * 1024
        eta = int((self._total - self.tell()) / bit_rate) + 1
        eta_m, eta_s = divmod(eta, 60)
        if sys.stdout.isatty():
            write(
                f'\r\033[K\033[?7h {frac}% {mb_pos:.1f}/{mb_tot:.1f}MB {kb_rate:.1f} KB/sec {eta_m} minutes, {eta_s} seconds left\033[?7l')
        if self.tell() >= self._total:
            t = int(time.monotonic() - self.start_time) + 1
            print(f'\nUpload took {t//60} minutes and {t%60} seconds at {kb_rate:.1f} KB/sec')
        sys.stdout.flush()


# }}}


class GitHub:  # {{{

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
        self.auth = 'Basic ' + base64.standard_b64encode(f'{self.username}:{self.password}'.encode()).decode()
        self.url_base = f'{self.API}/repos/{self.username}/{self.reponame}/releases'

    def info(self, *args: Any) -> None:
        print(*args, flush=True)

    def error(self, *args: Any) -> None:
        print(*args, flush=True, file=sys.stderr)

    def make_request(
        self, url: str, data: Optional[Dict[str, Any]] = None, method:str = 'GET',
        upload_data: Optional[ReadFileWithProgressReporting] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> HTTPSConnection:
        headers={
            'Authorization': self.auth,
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'kitty',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        if params:
            url += '?' + urlencode(params)
        rdata: Optional[Union[bytes, io.FileIO]] = None
        if data is not None:
            rdata = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'
            headers['Content-Length'] = str(len(rdata))
        elif upload_data is not None:
            rdata = upload_data
            mime_type = mimetypes.guess_type(os.path.basename(str(upload_data.name)))[0] or 'application/octet-stream'
            headers['Content-Type'] = mime_type
            headers['Content-Length'] = str(upload_data._total)
        purl = urlparse(url)
        conn = HTTPSConnection(purl.netloc, timeout=60)
        conn.request(method, url, body=rdata, headers=headers)
        return conn

    def make_request_with_retries(
        self, url: str, data: Optional[Dict[str, str]] = None, method:str = 'GET',
        num_tries: int = 2, sleep_between_tries: float = 15,
        success_codes: Tuple[int, ...] = (200,),
        failure_msg: str = 'Request failed',
        return_data: bool = False,
        upload_path: str = '',
        params: Optional[Dict[str, str]] = None,
        failure_callback: Callable[[HTTPResponse], None] = lambda r: None,
    ) -> Any:
        for i in range(num_tries):
            is_last_try = i == num_tries - 1
            try:
                if upload_path:
                    conn = self.make_request(url, method='POST', upload_data=ReadFileWithProgressReporting(upload_path), params=params)
                else:
                    conn = self.make_request(url, data, method, params=params)
                with contextlib.closing(conn):
                    r = conn.getresponse()
                    if r.status in success_codes:
                        return json.loads(r.read()) if return_data else None
                    if is_last_try:
                        self.fail(r, failure_msg)
                    else:
                        self.print_failed_response_details(r, failure_msg)
                        failure_callback(r)
            except Exception as e:
                self.error(failure_msg, 'with error:', e)
            self.error(f'Retrying after {sleep_between_tries} seconds')
            if is_last_try:
                break
            time.sleep(sleep_between_tries)
        raise SystemExit('All retries failed, giving up')

    def patch(self, url: str, fail_msg: str, **data: str) -> None:
        self.make_request_with_retries(url, data, method='PATCH', failure_msg=fail_msg)

    def update_nightly_description(self, release_id: int) -> None:
        url = f'{self.url_base}/{release_id}'
        now = str(datetime.datetime.now(datetime.timezone.utc)).split('.')[0] + ' UTC'
        commit = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options', 'master^{commit}']).decode('utf-8').strip()
        self.patch(
            url, 'Failed to update nightly release description',
            body=f'Nightly release, generated on: {now} from commit: {commit}.'
            ' For how to install nightly builds, see: https://sw.kovidgoyal.net/kitty/binary/#customizing-the-installation'
        )

    def __call__(self) -> None:
        # See https://docs.github.com/en/rest/releases/assets#upload-a-release-asset
        release = self.create_release()
        upload_url = release['upload_url'].partition('{')[0]
        all_assest_for_release = self.existing_assets_for_release(release)
        assets_by_fname = {a['name']:a for a in all_assest_for_release}

        def delete_asset(asset: Dict[str, Any], allow_not_found: bool = True) -> None:
            success_codes = [204]
            if allow_not_found:
                success_codes.append(404)
            self.make_request_with_retries(
                asset['url'], method='DELETE', num_tries=5, sleep_between_tries=2, success_codes=tuple(success_codes),
                failure_msg='Failed to delete asset from GitHub')

        def upload_with_retries(path: str, desc: str, num_tries: int = 8, sleep_time: float = 60.0) -> None:
            fname = os.path.basename(path)
            if self.is_nightly:
                fname = fname.replace(version, 'nightly')
            if fname in assets_by_fname:
                self.info(f'Deleting {fname} from GitHub with id: {assets_by_fname[fname]["id"]}')
                delete_asset(assets_by_fname.pop(fname))
            params = {'name': fname, 'label': desc}

            self.make_request_with_retries(
                upload_url, upload_path=path, params=params, num_tries=num_tries, sleep_between_tries=sleep_time,
                failure_msg=f'Failed to upload file: {fname}', success_codes=(201,),
            )

        if self.is_nightly:
            for fname in tuple(assets_by_fname):
                self.info(f'Deleting {fname} from GitHub with id: {assets_by_fname[fname]["id"]}')
                delete_asset(assets_by_fname.pop(fname))
        for path, desc in self.files.items():
            self.info('')
            upload_with_retries(path, desc)
        if self.is_nightly:
            self.update_nightly_description(release['id'])

    def print_failed_response_details(self, r: HTTPResponse, msg: str) -> None:
        self.error(msg, f'\nStatus Code: {r.status} {r.reason}')
        try:
            jr = json.loads(r.read())
        except Exception:
            pass
        else:
            self.error('JSON from response:')
            pprint.pprint(jr, stream=sys.stderr)

    def fail(self, r: HTTPResponse, msg: str) -> None:
        self.print_failed_response_details(r, msg)
        raise SystemExit(1)

    def existing_assets_for_release(self, release: Dict[str, Any]) -> List[Dict[str, Any]]:
        if 'assets' in release:
            d: List[Dict[str, Any]] = release['assets']
        else:
            d = self.make_request_with_retries(
                release['assets_url'], params={'per_page': '64'}, failure_msg='Failed to get assets for release', return_data=True)
        return d

    def create_release(self) -> Dict[str, Any]:
        ' Create a release on GitHub or if it already exists, return the existing release '
        # Check for existing release
        url = f'{self.url_base}/tags/{self.current_tag_name}'
        with contextlib.closing(self.make_request(url)) as conn:
            r = conn.getresponse()
            if r.status == 200:
                return {str(k): v for k, v in json.loads(r.read()).items()}
        if self.is_nightly:
            self.fail(r, 'No existing nightly release found on GitHub')
        data = {
            'tag_name': self.current_tag_name,
            'target_commitish': 'master',
            'name': f'version {self.version}',
            'body': f'Release version {self.version}.'
            ' For changelog, see https://sw.kovidgoyal.net/kitty/changelog/#detailed-list-of-changes'
            ' GPG key used for signing tarballs is: https://calibre-ebook.com/signatures/kovid.gpg',
            'draft': False,
            'prerelease': False
        }
        with contextlib.closing(self.make_request(self.url_base, method='POST', data=data)) as conn:
            r = conn.getresponse()
            if r.status != 201:
                self.fail(r, f'Failed to create release for version: {self.version}')
            return {str(k): v for k, v in json.loads(r.read()).items()}
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
        'linux/arm64/dist/kitty-{}-arm64.txz': 'Linux arm64 binary bundle',
    }.items():
        path = os.path.join('bypy', 'b', f.format(version))
        if not os.path.exists(path):
            raise SystemExit(f'The installer {path} does not exist')
        files[path] = desc
        signatures[path] = f'GPG signature for {desc}'
    b = len(files)
    for path in glob.glob('build/static/kitten-*'):
        if path.endswith('.sig'):
            continue
        path = os.path.abspath(path)
        exe_name = os.path.basename(path)
        files[path] = f'Static {exe_name} executable'
        signatures[path] = f'GPG signature for static {exe_name} executable'
    if len(files) == b:
        raise SystemExit('No static binaries found')

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


def remove_pycache_only_folders() -> None:
    folders_to_remove = []
    for dirpath, folders, files in os.walk('.'):
        if not files and folders == ['__pycache__']:
            folders_to_remove.append(dirpath)
    for x in folders_to_remove:
        shutil.rmtree(x)


@contextmanager
def change_to_git_master() -> Generator[None, None, None]:
    stash_ref_before = safe_read('.git/refs/stash')
    subprocess.check_call(['git', 'stash', '-u'])
    try:
        branch_before = current_branch()
        if branch_before != 'master':
            subprocess.check_call(['git', 'switch', 'master'])
            remove_pycache_only_folders()
            subprocess.check_call(['make', 'clean', 'debug'])
        try:
            yield
        finally:
            if branch_before != 'master':
                subprocess.check_call(['git', 'switch', branch_before])
                subprocess.check_call(['make', 'clean', 'debug'])
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
            subprocess.run(['make', 'clean', 'debug'])
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
