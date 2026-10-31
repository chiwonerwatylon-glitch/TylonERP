"""Command line tools: `flask seed-admin`."""
import click
from flask.cli import with_appcontext


@click.command("seed-admin")
@with_appcontext
def seed_admin_command():
    """Create the system administrator, or sync its password, from ADMIN_EMAIL and ADMIN_PASSWORD."""
    from flask import current_app

    from . import seed_admin

    seed_admin(current_app)
    click.echo("Administrator checked.")


def init_cli(app):
    app.cli.add_command(seed_admin_command)
