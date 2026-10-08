"""Independent native-v1 identity fixture over real, immutable Git commits."""
import hashlib
import re
import subprocess


def native_input(repository, commit, paths):
    def git(*args):
        return subprocess.run(['git', '-C', str(repository), *args], capture_output=True,
                              check=True).stdout.decode('utf-8')
    base = git('rev-parse', commit + '^').strip()
    text = git('-c', 'core.quotepath=false', 'diff', '--no-ext-diff', '--no-textconv',
               '--find-renames', '--src-prefix=a/', '--dst-prefix=b/', '--no-color',
               '-U3', '--end-of-options', base, commit, '--')
    items, old, new, lines = [], None, None, []
    def flush():
        if old is not None and new in paths:
            patch = '\n'.join(lines).rstrip('\r\n')
            items.append({'path': new,
                'item_id': hashlib.sha256(('review\0commit\0' + old + '\0' + new).encode()).hexdigest(),
                'fingerprint': hashlib.sha256(('commit\0' + old + '\0' + new + '\0' + patch).encode()).hexdigest()})
    for line in text.split('\n'):
        line = line.removesuffix('\r')
        match = re.fullmatch(r'diff --git a/(.+?) b/(.+)', line)
        if match:
            flush()
            old, new = match.groups()
            lines = []
        if old is not None and not line.startswith('index '):
            lines.append(line)
    flush()
    digest = hashlib.sha256()
    for item in sorted(items, key=lambda x: x['item_id']):
        for key in ('item_id', 'fingerprint'):
            value = item[key].encode()
            digest.update(len(value).to_bytes(8, 'big')); digest.update(value)
    return {'mode': 'commit', 'requested_head': commit, 'resolved_base': base,
            'resolved_head': commit, 'exact_range': base + '..' + commit,
            'source_artifact_sha256': digest.hexdigest()}, items
