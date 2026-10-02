import click
import os
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from gitrec.storage.db import Storage
from gitrec.extractors.git_extractor import GitExtractor
from gitrec.extractors.github_extractor import GitHubExtractor
from gitrec.engine.grouper import WorkGrouper
from gitrec.engine.scorer import ConfidenceScorer
from gitrec.review.exporter import ReviewExporter
from gitrec.review.web_ui import create_app
from gitrec.jira.client import JiraClient
from gitrec.jira.migrator import JiraMigrator

console = Console()


def _load_env_if_present():
    env_file = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip(" \"'")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_env_if_present()


@click.group()
def cli():
    """GitRec: Git History Organization & Jira Backfill Tool"""
    _load_env_if_present()


@cli.command()
@click.option("--repo-path", default=".", help="Path to local Git repository")
@click.option("--github-repo", help="GitHub repo in format 'owner/repo' or full URL (default: SOURCE_GITHUB_REPO env var)")
@click.option("--github-token", help="GitHub Personal Access Token (default: SOURCE_GITHUB_PAT or GITHUB_TOKEN env var)")
@click.option("--db-path", default="gitrec_store.db", help="SQLite database path")
@click.option("--max-items", default=None, type=int, help="Max PRs and Issues to extract from GitHub API (e.g. 50)")
def extract(repo_path, github_repo, github_token, db_path, max_items):
    """Extract commits from local Git and PRs/issues from GitHub."""
    storage = Storage(db_path)
    console.print(Panel(f"[bold cyan]Extracting Git History from {repo_path}[/bold cyan]"))

    # 1. Git extraction
    git_ext = GitExtractor(repo_path)
    try:
        commits = git_ext.extract_commits()
        storage.save_commits(commits)
        console.print(f"[green]✓ Extracted {len(commits)} commits from Git.[/green]")
    except Exception as e:
        console.print(f"[red]Error extracting git commits: {e}[/red]")
        sys.exit(1)

    # 2. GitHub extraction (fallback to .env variables if not supplied)
    gh_repo = github_repo or os.environ.get("SOURCE_GITHUB_REPO")
    gh_token = github_token or os.environ.get("SOURCE_GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")

    if gh_repo:
        # Normalize https://github.com/owner/repo to owner/repo
        if "github.com/" in gh_repo:
            gh_repo = gh_repo.split("github.com/")[-1].strip("/")
        owner, repo = gh_repo.split("/", 1)
        gh_ext = GitHubExtractor(owner, repo, gh_token)
        console.print(f"[bold cyan]Extracting GitHub PRs & Issues for {gh_repo}...[/bold cyan]")
        try:
            prs = gh_ext.extract_pull_requests(max_items=max_items)
            issues = gh_ext.extract_issues(max_items=max_items)
            storage.save_pull_requests(prs)
            storage.save_issues(issues)
            console.print(f"[green]✓ Extracted {len(prs)} PRs and {len(issues)} Issues from GitHub.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: GitHub extraction encountered error: {e}[/yellow]")



@cli.command()
@click.option("--db-path", default="gitrec_store.db", help="SQLite database path")
@click.option("--proximity-hours", default=24, help="Time window for commit proximity clustering (hours)")
def process(db_path, proximity_hours):
    """Detect relationships, group commits into logical work items, and score confidence."""
    storage = Storage(db_path)
    commits = storage.get_commits()
    prs = storage.get_pull_requests()
    issues = storage.get_issues()

    if not commits:
        console.print("[yellow]No commits found in database. Run 'gitrec extract' first.[/yellow]")
        return

    console.print(f"[bold cyan]Grouping {len(commits)} commits, {len(prs)} PRs, {len(issues)} Issues...[/bold cyan]")
    grouper = WorkGrouper(commits, prs, issues, proximity_hours=proximity_hours)
    raw_work_items = grouper.group_work()

    scorer = ConfidenceScorer(commits, prs, issues)
    scored_items = scorer.process_and_score_items(raw_work_items)
    storage.save_work_items(scored_items)

    # Summary table
    table = Table(title="Historical Work Items Generated")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Type", style="magenta")
    table.add_column("Kanban", style="yellow")
    table.add_column("Confidence", style="green")
    table.add_column("Commits", justify="right")
    table.add_column("PRs", justify="right")
    table.add_column("Issues", justify="right")

    for item in scored_items[:15]:
        conf_style = "green" if item.confidence >= 0.90 else ("yellow" if item.confidence >= 0.70 else "red")
        table.add_row(
            item.id,
            item.title[:40] + ("..." if len(item.title) > 40 else ""),
            item.work_type.value,
            item.kanban_status.value,
            f"[{conf_style}]{item.confidence:.2f}[/{conf_style}]",
            str(len(item.commit_shas)),
            str(len(item.pr_numbers)),
            str(len(item.issue_numbers))
        )


    console.print(table)
    if len(scored_items) > 15:
        console.print(f"[dim]... and {len(scored_items) - 15} more items.[/dim]")

    console.print(f"[bold green]✓ Created {len(scored_items)} logical work items from {len(commits)} commits.[/bold green]")


@cli.command()
@click.option("--db-path", default="gitrec_store.db", help="SQLite database path")
@click.option("--json-out", default="work_items_review.json", help="JSON export path")
@click.option("--csv-out", default="work_items_review.csv", help="CSV export path")
def export(db_path, json_out, csv_out):
    """Export work items dataset to JSON and CSV for human review."""
    storage = Storage(db_path)
    items = storage.get_work_items()
    if not items:
        console.print("[yellow]No work items found. Run 'gitrec process' first.[/yellow]")
        return

    ReviewExporter.export_to_json(items, json_out)
    ReviewExporter.export_to_csv(items, csv_out)
    console.print(f"[green]✓ Exported {len(items)} work items to [bold]{json_out}[/bold] and [bold]{csv_out}[/bold][/green]")


@cli.command()
@click.option("--db-path", default="gitrec_store.db", help="SQLite database path")
@click.option("--port", default=5000, help="Port to run web review studio on")
def review(db_path, port):
    """Launch the interactive web review dashboard."""
    app = create_app(db_path)
    console.print(Panel(f"[bold green]Starting GitRec Review Studio on http://127.0.0.1:{port}[/bold green]"))
    app.run(port=port, debug=False)


@cli.command()
@click.option("--jira-url", default=lambda: os.environ.get("TARGET_BASE_URL"), help="Jira base URL (default: TARGET_BASE_URL env var)")
@click.option("--project-key", default=lambda: os.environ.get("TARGET_PROJECT_KEY", "VSSO"), help="Jira Project Key (default: TARGET_PROJECT_KEY or 'VSSO')")
@click.option("--email", default=lambda: os.environ.get("TARGET_EMAIL"), help="Jira user email (default: TARGET_EMAIL env var)")
@click.option("--api-token", default=lambda: os.environ.get("TARGET_TOKEN"), help="Jira API Token (default: TARGET_TOKEN env var)")
@click.option("--db-path", default="gitrec_store.db", help="SQLite database path")
@click.option("--dry-run", is_flag=True, help="Simulate migration without creating Jira tickets")
def migrate(jira_url, project_key, email, api_token, db_path, dry_run):
    """Migrate approved historical work items to Jira."""
    storage = Storage(db_path)
    items = storage.get_work_items()
    if not items:
        console.print("[yellow]No work items found in database. Run process/review first.[/yellow]")
        return

    if not jira_url:
        console.print("[red]Error: --jira-url or TARGET_BASE_URL env variable is required.[/red]")
        sys.exit(1)

    client = None
    if not dry_run:
        if not email or not api_token:
            console.print("[red]Error: --email and --api-token (or TARGET_EMAIL and TARGET_TOKEN env vars) are required.[/red]")
            sys.exit(1)
        client = JiraClient(jira_url, email=email, api_token=api_token)
        try:
            client.test_connection()
            console.print("[green]✓ Connected to Jira successfully.[/green]")
        except Exception as e:
            console.print(f"[red]Error connecting to Jira: {e}[/red]")
            sys.exit(1)

    migrator = JiraMigrator(client, storage, project_key=project_key, dry_run=dry_run)
    console.print(f"[bold cyan]Migrating {len(items)} work items (Dry Run: {dry_run})...[/bold cyan]")
    results = migrator.migrate(items)

    success_count = len([r for r in results if r.get("status") in ["created", "updated", "dry-run-create", "dry-run-update"]])
    console.print(f"[bold green]✓ Processed {len(results)} items: {success_count} successful/simulated.[/bold green]")


@cli.command(name="run")
@click.option("--repo-path", default="scratch/owncast", help="Path to local Git repository")
@click.option("--github-repo", help="GitHub repo in format 'owner/repo' or URL (default: SOURCE_GITHUB_REPO env var)")
@click.option("--github-token", help="GitHub Personal Access Token (default: SOURCE_GITHUB_PAT env var)")
@click.option("--jira-url", default=lambda: os.environ.get("TARGET_BASE_URL"), help="Jira base URL (default: TARGET_BASE_URL env var)")
@click.option("--project-key", default=lambda: os.environ.get("TARGET_PROJECT_KEY", "VSSO"), help="Jira Project Key")
@click.option("--email", default=lambda: os.environ.get("TARGET_EMAIL"), help="Jira user email (default: TARGET_EMAIL env var)")
@click.option("--api-token", default=lambda: os.environ.get("TARGET_TOKEN"), help="Jira API Token (default: TARGET_TOKEN env var)")
@click.option("--db-path", default="gitrec_store.db", help="SQLite database path")
@click.option("--json-out", default="owncast_work_items.json", help="JSON export path")
@click.option("--csv-out", default="owncast_work_items.csv", help="CSV export path")
@click.option("--max-items", default=None, type=int, help="Optional max PRs/Issues (default is unlimited / all)")
@click.option("--auto-approve-min-confidence", default=0.70, type=float, help="Auto-approve items with confidence >= threshold for migration (default: 0.70)")
@click.option("--limit-migrate", default=None, type=int, help="Max approved items to migrate to Jira in this run")
@click.option("--reset-db", is_flag=True, help="Clear existing SQLite DB and re-extract completely from scratch")
@click.option("--dry-run", is_flag=True, help="Simulate migration without creating Jira tickets")
def run_all(repo_path, github_repo, github_token, jira_url, project_key, email, api_token, db_path, json_out, csv_out, max_items, auto_approve_min_confidence, limit_migrate, reset_db, dry_run):
    """Run the entire end-to-end pipeline in one command without limits."""
    from gitrec.models.base import WorkItemStatus

    console.print(Panel("[bold green]Starting Complete GitRec Backfill Pipeline (Full History, Fresh Start)[/bold green]"))

    if reset_db and os.path.exists(db_path):
        os.remove(db_path)
        console.print(f"[yellow]Database {db_path} wiped for fresh start.[/yellow]")

    storage = Storage(db_path)

    # 1. Git extraction
    console.print(f"[bold cyan]1. Extracting Complete Git Commit History from {repo_path}...[/bold cyan]")
    git_ext = GitExtractor(repo_path)
    commits = git_ext.extract_commits()
    storage.save_commits(commits)
    console.print(f"[green]✓ Extracted & indexed all {len(commits)} commits.[/green]")

    # 2. GitHub extraction
    gh_repo = github_repo or os.environ.get("SOURCE_GITHUB_REPO")
    gh_token = github_token or os.environ.get("SOURCE_GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    prs, issues = [], []
    if gh_repo:
        if "github.com/" in gh_repo:
            gh_repo = gh_repo.split("github.com/")[-1].strip("/")
        owner, repo = gh_repo.split("/", 1)
        limit_txt = f"(Limit: {max_items})" if max_items else "(ALL PRs & Issues)"
        console.print(f"[bold cyan]2. Extracting GitHub PRs, Issues & Discussions for {gh_repo} {limit_txt}...[/bold cyan]")
        try:
            gh_ext = GitHubExtractor(owner, repo, gh_token)
            prs = gh_ext.extract_pull_requests(max_items=max_items)
            issues = gh_ext.extract_issues(max_items=max_items)
            storage.save_pull_requests(prs)
            storage.save_issues(issues)
            console.print(f"[green]✓ Extracted {len(prs)} PRs and {len(issues)} Issues with full discussion histories.[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: GitHub extraction notice: {e}[/yellow]")
            prs = storage.get_pull_requests()
            issues = storage.get_issues()

    # 3. Process & Group
    console.print("[bold cyan]3. Clustering and classifying work items across entire history...[/bold cyan]")
    grouper = WorkGrouper(commits, prs, issues, proximity_hours=24)
    raw_work_items = grouper.group_work()

    scorer = ConfidenceScorer(commits, prs, issues)
    scored_items = scorer.process_and_score_items(raw_work_items)
    storage.save_work_items(scored_items)
    console.print(f"[bold green]✓ Clustered into {len(scored_items)} logical work items.[/bold green]")

    # 4. Export
    console.print(f"[bold cyan]4. Exporting to {json_out} and {csv_out}...[/bold cyan]")
    ReviewExporter.export_to_json(scored_items, json_out)
    ReviewExporter.export_to_csv(scored_items, csv_out)
    console.print(f"[green]✓ Exported full review datasets to {json_out} & {csv_out}.[/green]")

    # 5. Migrate
    console.print(f"[bold cyan]5. Jira Migration to {jira_url} (Project: {project_key}, Dry Run: {dry_run})...[/bold cyan]")
    client = None
    if not dry_run and jira_url and email and api_token:
        client = JiraClient(jira_url, email=email, api_token=api_token)
        try:
            user_info = client.test_connection()
            console.print(f"[green]✓ Connected to Jira Cloud ({user_info.get('displayName')}).[/green]")
        except Exception as e:
            console.print(f"[red]Error connecting to Jira: {e}[/red]")
            return

    # Auto-approve items meeting confidence threshold for migration
    approved_items = []
    for item in scored_items:
        if item.confidence >= auto_approve_min_confidence:
            item.status = WorkItemStatus.APPROVED
            approved_items.append(item)

    if limit_migrate:
        approved_items = approved_items[:limit_migrate]

    storage.save_work_items(approved_items)
    console.print(f"[cyan]Selected {len(approved_items)} high-confidence approved items (>= {auto_approve_min_confidence*100:.0f}%) for Jira synchronization.[/cyan]")

    migrator = JiraMigrator(client, storage, project_key=project_key, dry_run=dry_run)
    results = migrator.migrate(approved_items)
    success_count = len([r for r in results if r.get("status") in ["created", "updated", "dry-run-create", "dry-run-update"]])
    console.print(f"[bold green]✓ Migration finished: {success_count} tickets successfully created/synchronized in Jira.[/bold green]")
    for r in results[:10]:
        if r.get("status") in ["created", "updated"]:
            console.print(f"  → Ticket: [bold cyan]{r.get('jira_key')}[/bold cyan] | Status: {r.get('status')} | Work Item: {r.get('id')}")


if __name__ == "__main__":
    cli()




