"""First-time / daily Upstox OAuth login.

Prints an auth URL, asks user to paste back the ?code= value after login,
exchanges it for an access_token, and writes the token into .env.

Token expires ~3:30 AM IST next day. Re-run each morning before 8 AM
(or trigger on first failure of live_check.py).

Usage:
    python scripts/upstox_login.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel

from src.broker.upstox_auth import build_auth_url, exchange_code
from src.common import config

console = Console()
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _update_env_file(key: str, value: str) -> None:
    """Upsert KEY=VALUE in .env (creates file if missing)."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    found = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def main() -> int:
    if not config.UPSTOX_API_KEY or not config.UPSTOX_API_SECRET:
        console.print("[red]UPSTOX_API_KEY and UPSTOX_API_SECRET must be set in .env[/red]")
        console.print("[dim]Get these from https://upstox.com/developer/apps[/dim]")
        return 1
    redirect_uri = config.UPSTOX_REDIRECT_URI or "http://localhost:8080/callback"

    auth_url = build_auth_url(config.UPSTOX_API_KEY, redirect_uri)

    console.print(
        Panel(
            f"""[bold cyan]Step 1[/bold cyan] — Open this URL in your browser:

[green]{auth_url}[/green]

[bold cyan]Step 2[/bold cyan] — Log in with your Upstox credentials + TOTP.

[bold cyan]Step 3[/bold cyan] — After login you'll be redirected to a URL like:
  {redirect_uri}?code=<LONG_CODE>&state=stockpredict

The page may show an error (because {redirect_uri} isn't a real server). \
That's fine — copy the [bold]code[/bold] value from the URL's query string.""",
            title="Upstox OAuth Flow",
            border_style="cyan",
        )
    )

    code = input("\nPaste the 'code' value here: ").strip()
    if not code:
        console.print("[red]No code provided. Aborting.[/red]")
        return 1

    try:
        result = exchange_code(
            config.UPSTOX_API_KEY,
            config.UPSTOX_API_SECRET,
            redirect_uri,
            code,
        )
    except Exception as e:
        console.print(f"[red]Token exchange failed: {e}[/red]")
        return 1

    token = result.get("access_token")
    if not token:
        console.print(f"[red]No access_token in response:[/red] {result}")
        return 1

    _update_env_file("UPSTOX_ACCESS_TOKEN", token)
    console.print("\n[green]✓ Access token saved to .env[/green]")
    console.print(
        f"[dim]Expires ~3:30 AM IST next day. "
        f"Re-run this script each morning (or when ping fails).[/dim]"
    )
    console.print(
        "\n[cyan]Next step:[/cyan] [bold]python scripts/fetch_upstox_instruments.py[/bold] "
        "(one-time — maps our stocks to Upstox instrument keys)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
