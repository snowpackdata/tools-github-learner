"""
GitHub Learner - A CLI tool for analyzing GitHub repositories
"""
import os
import click
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from core import (
    clone_repository, 
    analyze_repository, 
    load_config, 
    save_config,
    get_repo_name_from_url,
    LEARNINGS_DIR
)

console = Console()


@click.group()
@click.option(
    "--output-dir", 
    "-o", 
    type=click.Path(file_okay=False),
    help="Directory for storing cloned repositories"
)
@click.option(
    "--language-model", 
    "-m", 
    help="Language model to use for analysis"
)
@click.option(
    "--max-files",
    "-f",
    type=int,
    help="Maximum number of files to include in analysis (0 = unlimited)"
)
@click.pass_context
def cli(ctx, output_dir, language_model, max_files):
    """GitHub Learner - Repository Analysis Tool.
    
    This tool helps you analyze GitHub repositories using local LLMs.
    """
    config = load_config()
    
    if output_dir:
        config["paths"]["output_dir"] = output_dir
    if language_model:
        config["models"]["default_model"] = language_model
    if max_files is not None:
        config["analysis"]["max_files"] = max_files
    
    # Expand user directory if needed
    if "~" in config["paths"]["output_dir"]:
        config["paths"]["output_dir"] = os.path.expanduser(config["paths"]["output_dir"])
    
    ctx.obj = config


@cli.command()
@click.option(
    "--save", 
    is_flag=True, 
    help="Save current settings as defaults"
)
@click.pass_context
def config(ctx, save):
    """View or update configuration settings."""
    if save:
        save_config(ctx.obj)
        console.print("[bold green]Configuration saved![/bold green]")
    
    console.print(Panel.fit(
        "\n".join(f"{k}: {v}" for k, v in ctx.obj.items()),
        title="Current Configuration"
    ))


@cli.command()
@click.argument("repository_url")
@click.option(
    "--output-file", 
    "-f", 
    type=click.Path(dir_okay=False),
    help="File to save analysis output"
)
@click.option(
    "--max-files",
    type=int,
    help="Maximum number of files to include in analysis (0 = unlimited)"
)
@click.pass_context
def analyze(ctx, repository_url, output_file, max_files):
    """Analyze a GitHub repository."""
    config = ctx.obj
    target_dir = Path(config["paths"]["output_dir"])
    os.makedirs(target_dir, exist_ok=True)
    
    # Get repo name for file organization
    repo_name = get_repo_name_from_url(repository_url)
    
    # Clone the repository (creates single-level folder structure)
    repo_dir = clone_repository(repository_url, target_dir)
    
    # Use command-line max_files if provided, otherwise use from config
    if max_files is not None:
        max_file_count = max_files
    else:
        max_file_count = config["analysis"]["max_files"]
    
    analysis_output = analyze_repository(
        repo_dir,
        config["models"]["default_model"],
        max_file_count
    )
    
    if output_file:
        # Use provided output file path
        with open(output_file, "w") as f:
            f.write(analysis_output)
        console.print(f"[bold green]Analysis saved to[/bold green]: {output_file}")
    else:
        # Create default output file directly under /learnings/
        default_output_file = target_dir / f"{repo_name}-analysis.md"
        with open(default_output_file, "w") as f:
            f.write(analysis_output)
        console.print(f"[bold green]Analysis saved to[/bold green]: {default_output_file}")
        console.print(Markdown(analysis_output))


@cli.command()
@click.argument("repository_name", required=False, default=None)
@click.pass_context
def cleanup(ctx, repository_name):
    """Remove cloned repositories. If no name is given, removes all."""
    import shutil

    config = ctx.obj
    output_dir = Path(config["paths"]["output_dir"])

    if not output_dir.exists():
        console.print(f"[yellow]Output directory not found:[/yellow] {output_dir}")
        return

    if repository_name:
        # Remove specific repository
        repo_dir = output_dir / repository_name
        if repo_dir.is_dir():
            try:
                shutil.rmtree(repo_dir)
                console.print(f"[bold green]Removed repository[/bold green]: {repo_dir}")
            except Exception as e:
                console.print(f"[bold red]Error removing repository {repo_dir}:[/bold red] {e}")
        else:
            console.print(f"[yellow]Repository not found at:[/yellow] {repo_dir}")
    else:
        # Remove all repositories
        console.print(f"[bold yellow]Removing all repositories in {output_dir}...[/bold yellow]")
        removed_count = 0
        error_count = 0
        for item in output_dir.iterdir():
            if item.is_dir() and (item / ".git").exists(): # Check if it looks like a git repo
                try:
                    shutil.rmtree(item)
                    console.print(f"- Removed: {item.name}")
                    removed_count += 1
                except Exception as e:
                    console.print(f"[bold red]  Error removing {item.name}:[/bold red] {e}")
                    error_count += 1
            elif item.is_dir():
                 # Optional: Add handling for other directories if needed
                 pass 
        
        if removed_count > 0:
             console.print(f"[bold green]Removed {removed_count} repositories.[/bold green]")
        else:
            console.print("[yellow]No cloned repositories found to remove.[/yellow]")
        if error_count > 0:
            console.print(f"[bold red]Encountered {error_count} errors during cleanup.[/bold red]")


@cli.command()
def list():
    """List all analyzed repositories."""
    if not LEARNINGS_DIR.exists():
        console.print("[yellow]No repositories have been analyzed yet.[/yellow]")
        return
    
    # Look for repository folders with .git directories
    repos = [d for d in LEARNINGS_DIR.iterdir() if d.is_dir() and (d / ".git").exists()]
    
    # Find analysis files directly under LEARNINGS_DIR
    analysis_files = [f for f in LEARNINGS_DIR.iterdir() 
                     if f.is_file() and f.name.endswith('-analysis.md')]
    
    if not repos:
        console.print("[yellow]No repositories have been analyzed yet.[/yellow]")
        return
    
    console.print("[bold green]Analyzed Repositories:[/bold green]")
    for repo_dir in repos:
        # Check if an analysis file exists for this repo
        analysis_file = next((f for f in analysis_files 
                            if f.stem.startswith(repo_dir.name)), None)
        status = "[green]✓[/green]" if analysis_file else "[yellow]⚠[/yellow]"
        console.print(f"- {repo_dir.name} {status}")


def main():
    """Entry point for the command-line interface."""
    cli(obj=None)


if __name__ == "__main__":
    main()