"""Optional Compose deployment contracts; no Docker daemon or real data needed."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_SERVICES = {
    'knowledge-embedding', 'knowledge-model-prepare', 'knowledge-qdrant', 'knowledge-ops',
}
SYNTHETIC_DSN = 'postgresql://synthetic:synthetic@postgres:5432/synthetic'


def test_knowledge_definitions_are_exclusively_opt_in():
    base = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    overlay = yaml.safe_load((ROOT / 'knowledge/compose.yml').read_text())
    assert not KNOWLEDGE_SERVICES.intersection(base['services'])
    assert 'knowledge-internal' not in base['networks']
    assert not {'knowledge-models', 'knowledge-qdrant'}.intersection(base['volumes'])
    assert 'knowledge-internal' not in base['services']['postgres']['networks']
    assert not base.get('include')
    assert set(overlay['services']) == KNOWLEDGE_SERVICES | {'postgres', 'api-server'}
    assert overlay['services']['postgres'] == {'networks': ['knowledge-internal']}
    assert overlay['services']['api-server'] == {'networks': ['knowledge-internal']}
    assert set(overlay['volumes']) == {'knowledge-models', 'knowledge-qdrant'}
    assert overlay['networks'] == {'knowledge-internal': {'internal': True}}
    assert not overlay.get('name')
    assert all(not service.get('container_name') for service in overlay['services'].values())


def test_knowledge_build_and_database_configuration_are_explicit():
    base = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
    services = yaml.safe_load((ROOT / 'knowledge/compose.yml').read_text())['services']
    ops = services['knowledge-ops']
    assert ops['build']['args'] == base['x-release-build-args']
    assert ops['build']['target'] == 'migrator'
    assert ops['environment']['DATABASE_DSN'].startswith('${DATABASE_DSN:?')
    assert set(ops['environment']) == {'DATABASE_DSN', 'APP_CONFIG_MASTER_KEY_FILE', 'APP_ENV'}
    assert ops['environment']['APP_CONFIG_MASTER_KEY_FILE'] == ''
    for name in KNOWLEDGE_SERVICES:
        service = services[name]
        assert not service.get('secrets')
        assert not service.get('extends')
        if name != 'knowledge-ops':
            assert 'DATABASE_DSN' not in service.get('environment', {})
        if 'build' in service:
            assert service['build']['context'] == '.'
            assert (ROOT / service['build']['dockerfile']).is_file()


def test_qdrant_release_is_pinned_without_changing_storage_or_network_boundaries():
    service = yaml.safe_load((ROOT / 'knowledge/compose.yml').read_text())['services']['knowledge-qdrant']
    assert service['image'] == (
        'qdrant/qdrant:v1.19.1@sha256:'
        '12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10'
    )
    assert not service.get('build')
    assert not service.get('ports')
    assert service['profiles'] == ['knowledge']
    assert service['volumes'] == ['knowledge-qdrant:/qdrant/storage']
    assert service['networks'] == ['knowledge-internal']
    assert service['environment']['QDRANT__TELEMETRY_DISABLED'] == 'true'


@pytest.fixture(scope='module')
def compose_cli():
    executable = shutil.which('docker')
    if not executable:
        pytest.skip('Docker Compose CLI unavailable')
    result = subprocess.run([executable, 'compose', 'version'], capture_output=True, timeout=15)
    if result.returncode:
        pytest.skip('Docker Compose CLI unavailable')
    return executable


def render(compose_cli, *, overlay=False, profiles=(), dsn=SYNTHETIC_DSN):
    # Never load the developer's .env or inherit credentials / COMPOSE_FILE.
    env = {key: os.environ[key] for key in ('PATH', 'HOME') if key in os.environ}
    if dsn is not None:
        env['DATABASE_DSN'] = dsn
    command = [compose_cli, 'compose', '--env-file', os.devnull,
               '-p', 'knowledge-compose-contract', '-f', 'docker-compose.yml']
    if overlay:
        command.extend(['-f', 'knowledge/compose.yml'])
    for profile in profiles:
        command.extend(['--profile', profile])
    command.extend(['config', '--format', 'json'])
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)


def parsed(result):
    if result.returncode:
        pytest.fail('Compose configuration validation failed; output intentionally withheld')
    return json.loads(result.stdout)


@pytest.mark.parametrize('profiles', [(), ('*',)])
def test_base_compose_never_requires_knowledge(compose_cli, profiles):
    config = parsed(render(compose_cli, profiles=profiles, dsn=None))
    assert not KNOWLEDGE_SERVICES.intersection(config['services'])
    assert 'knowledge-internal' not in config['networks']
    assert not {'knowledge-models', 'knowledge-qdrant'}.intersection(config['volumes'])


@pytest.mark.parametrize('profiles,expected', [
    ((), set()),
    (('knowledge',), KNOWLEDGE_SERVICES - {'knowledge-model-prepare'}),
    (('knowledge-prepare',), {'knowledge-model-prepare'}),
    (('*',), KNOWLEDGE_SERVICES),
])
def test_overlay_profiles_and_base_services_are_preserved(compose_cli, profiles, expected):
    base = parsed(render(compose_cli, profiles=profiles))
    combined = parsed(render(compose_cli, overlay=True, profiles=profiles))
    assert KNOWLEDGE_SERVICES.intersection(combined['services']) == expected
    for name, service in base['services'].items():
        actual = combined['services'][name]
        if name in {'postgres', 'api-server'}:
            actual = dict(actual, networks=dict(actual['networks']))
            assert 'knowledge-internal' in actual['networks']
            actual['networks'].pop('knowledge-internal')
        assert actual == service
    for kind in ('volumes', 'networks', 'secrets'):
        for name, value in base.get(kind, {}).items():
            assert combined[kind][name] == value
    assert combined['name'] == base['name'] == 'knowledge-compose-contract'
    for name in expected:
        service = combined['services'][name]
        assert not service.get('ports')
        assert not service.get('secrets')
        assert set(service['networks']) == (
            {'provider-egress'} if name == 'knowledge-model-prepare' else {'knowledge-internal'}
        )
        if 'build' in service:
            assert Path(service['build']['context']) == ROOT
    if 'knowledge-ops' in expected:
        assert combined['services']['knowledge-ops']['environment']['DATABASE_DSN'] == SYNTHETIC_DSN
    if 'knowledge-embedding' in expected:
        mount = combined['services']['knowledge-embedding']['volumes'][0]
        assert mount['source'] == 'knowledge-models' and mount['read_only']
        assert combined['volumes']['knowledge-models']['name'] == 'knowledge-compose-contract_knowledge-models'
    if 'knowledge-qdrant' in expected:
        assert combined['volumes']['knowledge-qdrant']['name'] == 'knowledge-compose-contract_knowledge-qdrant'


@pytest.mark.parametrize('dsn', [None, ''])
def test_overlay_rejects_missing_database_configuration(compose_cli, dsn):
    result = render(compose_cli, overlay=True, profiles=('*',), dsn=dsn)
    assert result.returncode != 0
    assert '配置知识库必须设置 DATABASE_DSN' in result.stderr
