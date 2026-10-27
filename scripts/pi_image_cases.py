#!/usr/bin/env python3
"""Build per-Case Pi images and materialize isolated Harbor Job inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / 'scripts/pi-preinstalled-node.Dockerfile'
NVM_SHA256 = '9290aec6cc2efc89273e16a77214eb37303caaff8c943102de5116fdef47ba86'
NODE_SHA256 = '1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce'
PI_CLASSES = {'PiComponentAgent', 'PiComponentInstaller', 'PiNoModelProbe'}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def image_info(name: str) -> dict:
    result = subprocess.run(['docker', 'image', 'inspect', name], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f'Image not found: {name}')
    return json.loads(result.stdout)[0]


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {'schema_version': 1, 'cases': {}}
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or not isinstance(data.get('cases'), dict):
        raise ValueError('Unsupported image manifest')
    return data


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def task_base(case: Path) -> str:
    config = tomllib.loads((case / 'task.toml').read_text())
    base = config.get('environment', {}).get('docker_image')
    if not isinstance(base, str) or not base:
        raise ValueError(f'{case}: task.toml must specify environment.docker_image')
    return base


def build(case: Path, context: Path, manifest_path: Path) -> dict:
    case = case.resolve()
    base = task_base(case)
    base_info = image_info(base)
    if base_info.get('Architecture') != 'amd64':
        raise ValueError('The current Dockerfile only supports amd64')
    nvm_hash, node_hash = sha(context / 'nvm.sh'), sha(context / 'node.tar.xz')
    if (nvm_hash, node_hash) != (NVM_SHA256, NODE_SHA256):
        raise ValueError('nvm.sh or node.tar.xz does not match the pinned SHA-256')
    dockerfile_hash = sha(DOCKERFILE)
    inputs = {'recipe_version': 1, 'base_image_id': base_info['Id'], 'dockerfile_sha256': dockerfile_hash,
              'nvm_sha256': nvm_hash, 'node_sha256': node_hash}
    build_key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    slug = re.sub(r'[^a-z0-9_.-]', '-', case.name.lower()).strip('-.')
    if not slug:
        raise ValueError('Invalid Case name')
    image = f'harbor-local/{slug}-pi:{build_key[:20]}'
    existing = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, text=True)
    if existing.returncode == 0:
        info = json.loads(existing.stdout)[0]
        labels = info.get('Config', {}).get('Labels') or {}
        if labels.get('coding-cases.pi-build-key') != build_key:
            raise ValueError(f'Image tag already exists with different build metadata: {image}')
        previous = load_manifest(manifest_path)['cases'].get(case.name)
        if previous and previous.get('image') == image and previous.get('image_id') != info['Id']:
            raise ValueError(f'Image ID no longer matches manifest: {image}')
        built_id = info['Id']
    else:
        with tempfile.TemporaryDirectory() as tmp:
            iidfile = Path(tmp) / 'iid'
            subprocess.run(['docker', 'build', '--network', 'none', '-f', str(DOCKERFILE),
                            '--build-arg', f'BASE_IMAGE={base}', '--iidfile', str(iidfile),
                            '--label', f'coding-cases.pi-build-key={build_key}',
                            '-t', image, str(context.resolve())], check=True)
            built_id = iidfile.read_text().strip()
    actual = image_info(image)['Id']
    if actual != built_id:
        raise ValueError(f'Image tag changed during build: {image}')
    if image_info(base)['Id'] != base_info['Id']:
        raise ValueError(f'Base image changed during build: {base}')
    record = {'case': case.name, 'base_image': base, 'image': image,
              'image_id': actual, 'build_key': build_key, 'node_version': '22.23.4',
              'nvm_version': '0.40.2', **inputs}
    manifest = load_manifest(manifest_path)
    manifest['cases'][case.name] = record
    write_json_atomic(manifest_path, manifest)
    return record


def pin_image(case: Path, image: str) -> None:
    path = case / 'task.toml'
    text = path.read_text()
    pattern = r'(?ms)(^\[environment\][ \t]*\n)(.*?)(?=^\[|\Z)'
    def replace(match):
        block, count = re.subn(r'(?m)^\s*docker_image\s*=.*$',
                               f'docker_image = {json.dumps(image)}', match.group(2), count=1)
        if count != 1:
            raise ValueError(f'{path}: missing docker_image')
        return match.group(1) + block
    updated, count = re.subn(pattern, replace, text, count=1)
    if count != 1 or tomllib.loads(updated)['environment']['docker_image'] != image:
        raise ValueError(f'{path}: unable to set image')
    path.write_text(updated)


def prepare(template: Path, manifest_path: Path, output: Path) -> Path:
    manifest = load_manifest(manifest_path)
    job = json.loads(template.read_text())
    if job.get('datasets'):
        raise ValueError('Dataset expansion is unsupported; list each local Case in tasks')
    tasks = job.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('Job must contain explicit local tasks')
    resolved = []
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or not task.get('path') or task.get('git_url') or task.get('name'):
            raise ValueError('Only explicit local Case paths are supported')
        case = Path(task['path']).resolve()
        if case.name in seen:
            raise ValueError(f'Duplicate Case name: {case.name}')
        seen.add(case.name)
        record = manifest['cases'].get(case.name)
        if not record or record.get('case') != case.name:
            raise ValueError(f'No image manifest record for {case.name}')
        if task_base(case) != record['base_image']:
            raise ValueError(f'Base image binding changed for {case.name}')
        if image_info(record['base_image'])['Id'] != record['base_image_id']:
            raise ValueError(f'Base image ID changed for {case.name}')
        if image_info(record['image'])['Id'] != record['image_id']:
            raise ValueError(f'Pi image ID changed for {case.name}')
        resolved.append((task, case, record))
    for agent in job.get('agents', []):
        agent_class = agent.get('import_path', '').split(':')[-1]
        if agent.get('name') == 'pi' and agent_class not in PI_CLASSES:
            raise ValueError('Built-in Pi does not support preinstalled_node; select the Pi component adapter')
        if agent_class in PI_CLASSES:
            agent.setdefault('kwargs', {})['preinstalled_node'] = True
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        records = {}
        for task, case, record in resolved:
            target = output / 'cases' / case.name
            shutil.copytree(case, target)
            pin_image(target, record['image'])
            task['path'] = str(target)
            records[case.name] = {**record, 'source_path': str(case),
                                  'source_task_sha256': sha(case / 'task.toml')}
        write_json_atomic(output / 'image-manifest.json', {'schema_version': 1, 'cases': records})
        job_path = output / 'job.json'
        write_json_atomic(job_path, job)
        return job_path
    except BaseException:
        shutil.rmtree(output)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('build')
    p.add_argument('--case', type=Path, required=True)
    p.add_argument('--context', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--template', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'build':
        print(json.dumps(build(args.case, args.context, args.manifest), indent=2))
    else:
        print(prepare(args.template, args.manifest, args.output))


if __name__ == '__main__':
    main()
