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
)
import sys
import shutil # Ensure shutil is imported
import yaml
import glob # Add glob import
import re # Add re import
from datetime import datetime # Add datetime import

console = Console()


@click.group()
@click.option(
    "--output-dir", 
    "-o", 
    type=click.STRING,
    help="Directory for storing cloned repositories (relative to project root or absolute)"
)
@click.option(
    "--language-model", 
    "-m", 
    help="Language model to use for analysis"
)
@click.option(
    "--max-files",
    type=int,
    help="Maximum number of files to include in analysis (0 = unlimited)"
)
@click.pass_context
def cli(ctx, output_dir, language_model, max_files):
    """GitHub Learner - Repository Analysis Tool.
    
    This tool helps you analyze GitHub repositories using local LLMs.
    """
    ctx.ensure_object(dict)
    ctx.obj['output_dir_override'] = output_dir
    ctx.obj['language_model_override'] = language_model
    ctx.obj['max_files_override'] = max_files


@cli.command()
@click.option(
    "--save", 
    is_flag=True, 
    help="Save current settings as defaults"
)
@click.pass_context
def config(ctx, save):
    """View or update configuration settings."""
    # Load base config
    current_config = load_config()

    # Apply command-line overrides passed via context (if any)
    if ctx.obj.get('output_dir_override'):
        current_config["paths"]["output_dir"] = ctx.obj['output_dir_override']
    if ctx.obj.get('language_model_override'):
        current_config["models"]["default_model"] = ctx.obj['language_model_override']
    if ctx.obj.get('max_files_override') is not None:
        # Ensure 'analysis' key exists
        current_config.setdefault('analysis', {})
        current_config["analysis"]["max_files"] = ctx.obj['max_files_override']
        
    # Use this potentially overridden view for display/save
    config_to_process = current_config

    if save:
        # IMPORTANT: We save the potentially modified config back
        save_config(config_to_process)
        console.print("[bold green]Configuration saved![/bold green]")

    console.print(Panel.fit(
        "\n".join(f"{k}: {v}" for k, v in config_to_process.items()),
        title="Current Configuration"
    ))


@cli.command()
@click.argument("repository_url")
@click.option(
    "--output-file", 
    type=click.Path(dir_okay=False),
    help="File to save analysis output"
)
@click.option(
    "--max-files", # Allow overriding max_files specifically for this command
    type=int,
    help="Maximum number of files to include in analysis (0 = unlimited)"
)
@click.pass_context
def analyze(ctx, repository_url, output_file, max_files):
    """Analyze a GitHub repository."""
    # Load base config
    current_config = load_config()

    # Apply global command-line overrides from group context
    if ctx.obj.get('output_dir_override'):
        current_config["paths"]["output_dir"] = ctx.obj['output_dir_override']
    if ctx.obj.get('language_model_override'):
        current_config["models"]["default_model"] = ctx.obj['language_model_override']
    # Apply analyze-specific command-line override for max_files
    # Note: The group override for max_files is ignored if this specific one is given
    if max_files is not None:
        current_config.setdefault('analysis', {})
        current_config["analysis"]["max_files"] = max_files
    elif ctx.obj.get('max_files_override') is not None:
        current_config.setdefault('analysis', {})
        current_config["analysis"]["max_files"] = ctx.obj['max_files_override']

    # --- Use the effective config --- 
    effective_output_dir = current_config["paths"]["output_dir"]
    effective_model = current_config["models"]["default_model"]
    effective_max_files = current_config.get("analysis", {}).get("max_files", 3) # Default to 3

    # Convert output_dir string to Path here *after* parsing
    if isinstance(effective_output_dir, str):
        if "~" in effective_output_dir:
             effective_output_dir = os.path.expanduser(effective_output_dir)
        target_dir = Path(effective_output_dir)
    elif isinstance(effective_output_dir, Path): # Handle case where it might already be a Path from config
        target_dir = effective_output_dir
    else:
        console.print(f"[bold red]Invalid output_dir type: {type(effective_output_dir)}[/bold red]")
        sys.exit(1)

    os.makedirs(target_dir, exist_ok=True)
    
    # Get repo name for file organization
    repo_name = get_repo_name_from_url(repository_url)
    
    # Clone the repository (creates single-level folder structure)
    repo_dir = clone_repository(repository_url, target_dir)
    
    analysis_output = analyze_repository(
        repo_dir,
        effective_model, # Use effective model
        effective_max_files # Use effective max files
    )
    
    if output_file:
        # Use provided output file path
        output_path = Path(output_file)
        # Ensure parent directory exists if output_file includes path components
        os.makedirs(output_path.parent, exist_ok=True) 
        with open(output_path, "w") as f:
            f.write(analysis_output)
        console.print(f"[bold green]Analysis saved to[/bold green]: {output_path}")
    else:
        # --- Start Versioning Logic ---
        # Find existing analysis files for this repo
        version_pattern = re.compile(rf"^{re.escape(repo_name)}-analysis-v(\d+)\.md$")
        existing_versions = []
        # Use glob within the target directory
        glob_pattern = str(target_dir / f"{repo_name}-analysis-v*.md") 
        for filepath_str in glob.glob(glob_pattern):
            filename = Path(filepath_str).name # Get just the filename
            match = version_pattern.match(filename)
            if match:
                try:
                    existing_versions.append(int(match.group(1)))
                except ValueError:
                    pass # Ignore if the number part isn't a valid int

        # Determine next version
        if existing_versions:
            next_version = max(existing_versions) + 1
        else:
            next_version = 1

        # Create the new versioned filename
        versioned_output_file = target_dir / f"{repo_name}-analysis-v{next_version}.md"
        # --- End Versioning Logic ---

        # Save using the versioned filename
        with open(versioned_output_file, "w") as f:
            f.write(analysis_output)
        # Add timestamp before printing saved path
        timestamp = datetime.now().strftime("%H:%M:%S")
        console.print(f"[{timestamp}] [bold green]Analysis saved to[/bold green]: {versioned_output_file}")
        # Optionally print the markdown to console as before
        console.print(Markdown(analysis_output))


@cli.command()
@click.pass_context
def cleanup(ctx):
    """Remove ALL cloned repositories and *-input-text.md files from the output directory."""
    # Load config manually inside the function
    config = load_config()
    # Allow global override for output dir if provided
    output_dir_str = config["paths"]["output_dir"] # Get base path string from config
    if ctx.obj.get('output_dir_override'): 
        output_dir_str = ctx.obj['output_dir_override'] # Override with string from CLI arg

    # Convert to Path *after* parsing and overrides
    if "~" in output_dir_str:
        output_dir_str = os.path.expanduser(output_dir_str)
    output_dir = Path(output_dir_str)

    if not output_dir.exists():
        console.print(f"[yellow]Output directory not found:[/yellow] {output_dir}")
        return

    # Remove Debug prints
    # console.print(f"DEBUG: Attempting to list items in: {output_dir}")
    # console.print(f"DEBUG: Type of output_dir: {type(output_dir)}")

    # --- Always Delete All Logic --- 
    console.print(f"[bold yellow]Removing ALL repository directories and *-input-text.md files in {output_dir}...[/bold yellow]")
    repo_removed_count = 0
    repo_error_count = 0 # Keep track of errors
    input_removed_count = 0
    input_error_count = 0

    # Pass 1: Remove repository directories
    console.print("--- Removing repository directories ---")
    
    # Build list manually
    # console.print("DEBUG: Trying manual iteration and building list manually...")
    items_to_process = [] # Initialize
    try:
        for item in output_dir.iterdir():
             # console.print(f"  - Found item: {item} (Type: {type(item)})", highlight=False)
             items_to_process.append(item) # Build list manually
        # List is built
        # console.print("DEBUG: Manual iteration and list building succeeded.")
    except TypeError as te:
         console.print(f"[bold red]TypeError during iteration/listing: {te}[/bold red]")
         # Print traceback for detailed context
         import traceback
         traceback.print_exc()
         return # Exit on TypeError
    except FileNotFoundError:
        console.print(f"[bold red]Error: Output directory {output_dir} vanished during operation.[/bold red]")
        return
    except Exception as e:
        console.print(f"[bold red]Other error listing items in {output_dir}: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        return # Exit on other errors
        
    # Proceed only if items_to_process was populated
    for item in items_to_process:
        if item.is_dir() and (item / ".git").exists():
            try:
                shutil.rmtree(item)
                console.print(f"- Removed directory: {item.name}")
                repo_removed_count += 1
            except Exception as e:
                console.print(f"[bold red]  Error removing {item.name}:[/bold red] {e}")
                repo_error_count += 1 # Increment repo error count

    # Pass 2: Remove input text files
    console.print("--- Removing input text files ---")
    # Re-list items in case directory contents changed or dir was removed/recreated
    # Build the list manually for the second pass too
    items_to_process_files = []
    try:
        # Build list manually instead of using list()
        for item in output_dir.iterdir():
            items_to_process_files.append(item)
        # console.print(f"DEBUG: Found {len(items_to_process_files)} items for file removal pass.")
    except FileNotFoundError:
        # If the directory is gone after removing repos, that's fine for this step.
        console.print(f"[yellow]Output directory {output_dir} no longer exists after removing repositories. Skipping input file removal.[/yellow]")
        # items_to_process_files remains empty
    except Exception as e:
        console.print(f"[bold red]Error re-listing items in {output_dir}: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        # Decide if we should stop or continue? Let's stop.
        # items_to_process_files remains empty 
        input_error_count +=1 # Count this as an error
        
    for item in items_to_process_files: # Use the manually built list
         if item.is_file() and item.name.endswith('-input-text.md'):
             try:
                 os.remove(item)
                 console.print(f"- Removed input file: {item.name}")
                 input_removed_count += 1
             except Exception as e:
                 console.print(f"[bold red]  Error removing {item.name}:[/bold red] {e}")
                 input_error_count += 1

    # Summary
    if repo_removed_count > 0:
         console.print(f"[bold green]Removed {repo_removed_count} repository directories.[/bold green]")
    else:
        console.print("[yellow]No cloned repository directories found to remove.[/yellow]")
        
    if input_removed_count > 0:
         console.print(f"[bold green]Removed {input_removed_count} input text files.[/bold green]")
    else:
        # Only print this if we didn't skip due to directory vanishing
        if output_dir.exists(): 
            console.print("[yellow]No input text files found to remove.[/yellow]")

    total_errors = repo_error_count + input_error_count
    if total_errors > 0:
        console.print(f"[bold red]Encountered {total_errors} errors during cleanup.[/bold red]")


@cli.command()
def list():
    """List all analyzed repositories."""
    # Load config to determine the learnings directory
    try:
        current_config = load_config()
        learnings_dir_str = current_config["paths"]["output_dir"]
        if "~" in learnings_dir_str:
            learnings_dir_str = os.path.expanduser(learnings_dir_str)
        # Assuming relative path if not absolute
        learnings_dir = Path(learnings_dir_str)
        if not learnings_dir.is_absolute():
            from core import BASE_DIR # Need BASE_DIR for relative paths
            learnings_dir = BASE_DIR / learnings_dir
    except Exception as e:
        console.print(f"[bold red]Error loading config for list command: {e}[/bold red]")
        sys.exit(1)

    if not learnings_dir.exists():
        console.print(f"[yellow]Learnings directory not found: {learnings_dir}[/yellow]")
        console.print("[yellow]No repositories have been analyzed yet.[/yellow]")
        return

    # Look for repository folders with .git directories
    repos = [d for d in learnings_dir.iterdir() if d.is_dir() and (d / ".git").exists()]
    
    # Find analysis files directly under LEARNINGS_DIR
    analysis_files = [f for f in learnings_dir.iterdir() 
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