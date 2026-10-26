"""Exercise release helpers against real disposable Git repositories, not GitHub."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VERSION = 'v9.15.0-ls423'


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.work = self.root / 'work'
        self.work.mkdir()
        self.env = {**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        self.command(['git', 'init', '--bare', '-b', 'main', str(self.remote)], cwd=self.root)
        self.command(['git', 'init', '-b', 'main'], cwd=self.work)
        self.git('config', 'user.name', 'Release Test')
        self.git('config', 'user.email', 'release@example.invalid')
        self.git('config', 'tag.gpgSign', 'false')
        self.git('remote', 'add', 'origin', str(self.remote))
        shutil.copytree(PROJECT / 'scripts', self.work / 'scripts')
        self.commit('initial')

    def command(self, args, *, cwd=None, success=True, env=None):
        result = subprocess.run(args, cwd=cwd or self.work, env=env or self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout)
        return result

    def git(self, *args):
        return self.command(['git', *args]).stdout.strip()

    def commit(self, text, *, push=True):
        with (self.work / 'history.txt').open('a') as output:
            output.write(text + '\n')
        self.git('add', '.')
        self.git('commit', '-m', text)
        if push:
            self.git('push', '-u', 'origin', 'main')
        return self.git('rev-parse', 'HEAD')

    def helper(self, name, *args, success=True):
        return self.command([str(self.work / 'scripts' / name), *args], success=success)

    def remote_tag(self):
        return self.command(['git', '--git-dir', str(self.remote), 'rev-parse', f'refs/tags/{VERSION}']).stdout.strip()

    def test_create_and_retag_pushed_main(self):
        first_commit = self.git('rev-parse', 'HEAD')
        self.helper('tag.sh', VERSION)
        first_tag = self.remote_tag()
        self.assertEqual(self.git('rev-parse', f'{VERSION}^{{commit}}'), first_commit)
        second_commit = self.commit('fix patch')
        self.helper('retag.sh', VERSION)
        self.assertNotEqual(self.remote_tag(), first_tag)
        self.assertEqual(self.git('rev-parse', f'{VERSION}^{{commit}}'), second_commit)
        self.helper('verify-release.sh', VERSION, second_commit, self.remote_tag())

    def test_same_commit_retag_is_a_new_event(self):
        self.helper('tag.sh', VERSION)
        first = self.remote_tag()
        self.helper('retag.sh', VERSION)
        second = self.remote_tag()
        self.helper('retag.sh', VERSION)
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, self.remote_tag())

    def test_dry_run_does_not_create_or_move_tags(self):
        self.helper('tag.sh', VERSION, '--dry-run')
        self.assertEqual(self.git('tag', '--list'), '')
        self.helper('tag.sh', VERSION)
        old = self.remote_tag()
        self.commit('fix')
        self.helper('retag.sh', VERSION, '--dry-run')
        self.assertEqual(self.remote_tag(), old)
        self.assertEqual(self.git('rev-parse', VERSION), old)

    def test_dirty_wrong_branch_and_unpushed_head_are_rejected(self):
        (self.work / 'untracked').write_text('unfinished')
        self.assertNotEqual(self.helper('tag.sh', VERSION, success=False).returncode, 0)
        (self.work / 'untracked').unlink()
        self.git('checkout', '-b', 'feature')
        self.assertNotEqual(self.helper('tag.sh', VERSION, success=False).returncode, 0)
        self.git('checkout', 'main')
        self.commit('not pushed', push=False)
        self.assertNotEqual(self.helper('tag.sh', VERSION, success=False).returncode, 0)
        self.assertEqual(self.git('tag', '--list'), '')

    def test_bad_versions_and_accidental_overwrite_are_rejected(self):
        for version in ('latest', 'main', 'v9.15.0/unsafe', 'v9.15.0;false', '--force'):
            self.assertNotEqual(self.helper('tag.sh', version, success=False).returncode, 0)
        self.assertNotEqual(self.helper('retag.sh', VERSION, success=False).returncode, 0)
        self.helper('tag.sh', VERSION)
        old = self.remote_tag()
        self.assertNotEqual(self.helper('tag.sh', VERSION, success=False).returncode, 0)
        self.assertEqual(self.remote_tag(), old)

    def test_stale_run_and_non_main_tag_are_rejected(self):
        commit = self.git('rev-parse', 'HEAD')
        self.helper('tag.sh', VERSION)
        old = self.remote_tag()
        self.helper('retag.sh', VERSION)
        result = self.helper('verify-release.sh', VERSION, commit, old, success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stale', result.stdout)
        self.git('checkout', '-b', 'feature')
        feature = self.commit('feature only', push=False)
        self.git('tag', '-f', '-a', VERSION, '-m', 'invalid branch tag')
        self.git('push', '--force', 'origin', f'refs/tags/{VERSION}')
        result = self.helper('verify-release.sh', VERSION, feature, self.remote_tag(), success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not on main', result.stdout)

    def test_rejected_push_restores_local_tag(self):
        self.helper('tag.sh', VERSION)
        old = self.remote_tag()
        self.commit('fix')
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.assertNotEqual(self.helper('retag.sh', VERSION, success=False).returncode, 0)
        self.assertEqual(self.git('rev-parse', VERSION), old)
        self.assertEqual(self.remote_tag(), old)
        other = 'v9.16.0-ls424'
        self.assertNotEqual(self.helper('tag.sh', other, success=False).returncode, 0)
        self.assertEqual(self.git('tag', '--list', other), '')

    def test_publish_uses_both_registries_and_refuses_stale_run(self):
        self.helper('tag.sh', VERSION)
        commit, tag = self.git('rev-parse', 'HEAD'), self.remote_tag()
        commands = self.root / 'commands'
        tools = self.root / 'bin'
        tools.mkdir()
        engine = tools / 'docker'
        engine.write_text('''#!/bin/sh
printf "%s\\n" "$*" >> "$COMMAND_LOG"
case "$*" in
  *org.opencontainers.image.version*) printf '%s\\n' "$IMAGE_VERSION" ;;
  *org.opencontainers.image.revision*) printf '%s\\n' "$IMAGE_REVISION" ;;
esac
''')
        engine.chmod(0o755)
        env = {**self.env, 'PATH': str(tools) + os.pathsep + self.env['PATH'],
               'CONTAINER_ENGINE': 'docker', 'COMMAND_LOG': str(commands),
               'IMAGE_VERSION': VERSION, 'IMAGE_REVISION': commit}
        self.command([str(self.work / 'scripts/publish.sh'), VERSION, 'tested-image', commit, tag], env=env)
        recorded = commands.read_text()
        self.assertIn(f'push ghcr.io/vm75/calibre-server:{VERSION}', recorded)
        self.assertIn(f'push docker.io/vm75/calibre-server:{VERSION}', recorded)
        commands.write_text('')
        result = self.command([str(self.work / 'scripts/publish.sh'), VERSION, 'wrong-image', commit, tag],
                              env={**env, 'IMAGE_REVISION': '0' * 40}, success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('push ', commands.read_text())
        self.helper('retag.sh', VERSION)
        commands.write_text('')
        result = self.command([str(self.work / 'scripts/publish.sh'), VERSION, 'tested-image', commit, tag],
                              env=env, success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('push ', commands.read_text())


class PatchFailureTest(unittest.TestCase):
    def test_upstream_mismatch_exits_before_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'calibre/srv/auth.py'
            target.parent.mkdir(parents=True)
            target.write_text('# incompatible upstream source\n')
            result = subprocess.run(['python3', str(PROJECT / 'patches/patch_auth.py'), directory],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Expected exactly one matching patch location', result.stdout)
            self.assertEqual(target.read_text(), '# incompatible upstream source\n')


if __name__ == '__main__':
    unittest.main()
