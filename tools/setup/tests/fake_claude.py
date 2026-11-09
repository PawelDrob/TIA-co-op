"""Stands in for the claude command: logs each call and keeps the files the real one was seen to keep, in CLAUDE_CONFIG_DIR."""
import json
import os
import sys
from pathlib import Path


def main(args):
    config = Path(os.environ['CLAUDE_CONFIG_DIR'])
    with open(config / 'claude-calls.log', 'a', encoding='utf-8') as log:
        log.write(json.dumps(args) + '\n')
    failing = os.environ.get('FAKE_CLAUDE_FAIL', '')
    if failing and ' '.join(args).startswith(failing):
        # The shape of a real failure: the cause in the middle, another attempt's words last.
        noise = ''.join(f'error: noise {n}\n' for n in range(int(os.environ.get('FAKE_CLAUDE_NOISE', 0))))
        print(f'{failing}: trying over HTTPS\nerror: unable to create file: Filename too long\n{noise}\ntrying over SSH\nand the repository exists.', file=sys.stderr)
        return 1
    plugins = config / 'fake-plugins.json'
    installed = json.loads(plugins.read_text()) if plugins.exists() else []
    if args[:2] == ['mcp', 'add']:
        state_file = config / '.claude.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        rest = args[args.index('--') + 1:]
        holder = state if args[args.index('--scope') + 1] == 'user' else state.setdefault('projects', {}).setdefault(Path.cwd().as_posix(), {})
        holder.setdefault('mcpServers', {})[args[args.index('--') - 1]] = {'type': 'stdio', 'command': rest[0], 'args': rest[1:]}
        state_file.write_text(json.dumps(state))
    elif args[:3] == ['plugin', 'list', '--json']:
        print(json.dumps(installed))
    elif args[:2] == ['plugin', 'install']:
        scope = args[args.index('--scope') + 1] if '--scope' in args else 'user'
        plugins.write_text(json.dumps(installed + [{'id': args[2], 'scope': scope, 'enabled': True}]))
    return 0


sys.exit(main(sys.argv[1:]))
