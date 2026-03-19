"""Command-line interface for garde-manger (conversation memory system)."""

import os
os.environ.setdefault('RUST_LOG', 'error,sqlite3Parser=off')

import click

from ..config import load_config
from ..glossary import load_glossary


@click.group()
@click.version_option(package_name="garde-manger")
@click.pass_context
def main(ctx):
    """Conversation Memory System - persistent, searchable memory across Claude sessions."""
    ctx.ensure_object(dict)
    ctx.obj['config'] = load_config()
    ctx.obj['glossary'] = load_glossary()


# Register command modules — each module adds commands to `main` via @main.command()
from . import scan, browse, ingest, extract_cmds, fts, entities  # noqa: E402, F401


if __name__ == '__main__':
    main()
