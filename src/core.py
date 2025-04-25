"""
Core functionality for the GitHub Learner tool.
"""
import os
import re
import sys
import yaml
import json
import llm
import git
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from rich.console import Console
from prompts import REPO_ANALYSIS_PROMPT
import logging
from datetime import datetime
import tiktoken

console = Console()

# Constants
BASE_DIR = Path(os.getcwd()).absolute()

# Configure logging
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# The config file will be in the base directory
CONFIG_FILE = BASE_DIR / "config.yaml"

def load_config():
    """Load configuration from file. Exits if config.yaml is missing or invalid."""
    if not CONFIG_FILE.exists():
        console.print(f"[bold red]Error: Configuration file not found at {CONFIG_FILE}[/bold red]")
        console.print("Please ensure 'config.yaml' exists in the project root.")
        sys.exit(1)

    try:
        with open(CONFIG_FILE, "r") as f:
            config_data = yaml.safe_load(f)
        if not isinstance(config_data, dict):
            raise TypeError("Configuration file content is not a valid dictionary.")
        
        # Add default for max_prompt_chars if missing
        config_data.setdefault('analysis', {})
        config_data['analysis'].setdefault('max_prompt_chars', 15000) # Default character limit

        return config_data
    except (yaml.YAMLError, TypeError) as e:
        console.print(f"[bold red]Error: Invalid configuration file {CONFIG_FILE}: {e}[/bold red]")
        console.print("Please ensure 'config.yaml' is correctly formatted.")
        sys.exit(1)
    except Exception as e: # Catch other potential file reading errors
        console.print(f"[bold red]Error reading configuration file {CONFIG_FILE}: {e}[/bold red]")
        sys.exit(1)


def save_config(config):
    """Save configuration to file."""
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f)


def normalize_github_url(url: str) -> str:
    """Normalize a GitHub URL to the repository's main page."""
    # Handle GitHub URL patterns
    patterns = [
        # Main repo URL: https://github.com/username/repo
        r"^https?://github\.com/([^/]+/[^/]+)(?:/.*)?$",
        # Git URL: https://github.com/username/repo.git
        r"^https?://github\.com/([^/]+/[^/]+)\.git$",
        # SSH URL: git@github.com:username/repo.git
        r"^git@github\.com:([^/]+/[^/]+)(?:\.git)?$",
    ]

    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            repo_path = match.group(1)
            # Remove trailing .git if present
            repo_path = repo_path.removesuffix(".git")
            return f"https://github.com/{repo_path}"

    # If no pattern matches, return the original URL
    console.print(f"[yellow]Warning: Couldn't normalize URL: {url}[/yellow]")
    return url


def get_repo_name_from_url(url: str) -> str:
    """Extract repository name from GitHub URL."""
    normalized_url = normalize_github_url(url)
    parts = normalized_url.split("/")
    if len(parts) >= 5:
        return parts[-1]
    return "unknown-repo"


def clone_repository(url: str, target_dir: Optional[Path] = None) -> Path:
    """Clone a GitHub repository to a target directory.
    
    Creates a repo folder directly under the target directory:
    /learnings/repo_name/...
    """
    normalized_url = normalize_github_url(url)
    repo_name = get_repo_name_from_url(normalized_url)
    
    # Determine target directory if None
    if target_dir is None:
        # Load config here just to get the output path
        try: 
            current_config = load_config()
            output_dir_str = current_config["paths"]["output_dir"]
            if "~" in output_dir_str:
                 output_dir_str = os.path.expanduser(output_dir_str)
            target_dir = BASE_DIR / output_dir_str # Ensure it's relative to BASE_DIR if not absolute
        except Exception as e:
            console.print(f"[bold red]Error loading config to determine target directory: {e}[/bold red]")
            sys.exit(1)
    else:
        # If target_dir was provided (e.g., from analyze), ensure it's Path
        target_dir = Path(target_dir)

    # Create the repository directory directly under target_dir
    repo_dir = target_dir / repo_name
    os.makedirs(repo_dir, exist_ok=True)
    
    console.print(f"[bold green]Cloning repository[/bold green]: {normalized_url}")
    console.print(f"[bold green]Target directory[/bold green]: {repo_dir}")
    
    try:
        # Check if directory already has a .git folder
        if (repo_dir / ".git").exists():
            console.print("[yellow]Repository already exists. Pulling latest changes...[/yellow]")
            repo = git.Repo(repo_dir)
            repo.remotes.origin.pull()
        else:
            git.Repo.clone_from(normalized_url, repo_dir)
        
        console.print("[bold green]Repository cloned successfully![/bold green]")
        return repo_dir
    except git.GitCommandError as e:
        console.print(f"[bold red]Error cloning repository:[/bold red] {e}")
        sys.exit(1)


def analyze_repository(repo_dir: Path, language_model: str):
    """Analyze a repository using files-to-prompt and local LLM.
    
    Args:
        repo_dir: Path to the repository directory
        language_model: Name of the language model to use
    """
    current_config = load_config() # Load fresh config for analysis settings
    # Determine LEARNINGS_DIR within the function if needed for saving input file
    learnings_dir_str = current_config["paths"]["output_dir"]
    if "~" in learnings_dir_str:
        learnings_dir_str = os.path.expanduser(learnings_dir_str)
    # Assuming output_dir is relative to BASE_DIR unless absolute path provided
    learnings_path = Path(learnings_dir_str)
    if not learnings_path.is_absolute():
        learnings_path = BASE_DIR / learnings_path
    os.makedirs(learnings_path, exist_ok=True) # Ensure dir exists

    console.print(f"[bold green]Analyzing repository[/bold green]: {repo_dir}")
    console.print(f"[bold green]Using language model[/bold green]: {language_model}")
    
    # Remove any "mlx:" prefix if present
    if language_model.startswith("mlx:"):
        language_model = language_model.replace("mlx:", "", 1)
    
    # Create a temporary file to store the output from files-to-prompt
    with tempfile.NamedTemporaryFile(delete=False, mode='w+') as temp_file:
        # Build the command to run files-to-prompt, passing repo_dir and ignore flags
        cmd = [
            sys.executable, 
            "-m", 
            "files_to_prompt", 
            "--markdown", 
            str(repo_dir) # Pass the repo directory itself
        ]
        
        # Add ignore flags corresponding to previous logic
        ignore_flags = [
            # Directories
            "--ignore", ".git",
            "--ignore", ".venv",
            "--ignore", "venv",
            "--ignore", "node_modules",
            "--ignore", "dist",
            "--ignore", "build",
            "--ignore", "target",
            "--ignore", "docs",
            "--ignore", "doc", 
            "--ignore", "tests",
            # Common non-code files (using patterns)
            "--ignore", "LICENSE*", 
            "--ignore", "COPYING*", 
            "--ignore", "NOTICE*", 
            "--ignore", "CONTRIBUTING*", 
            "--ignore", "CODE_OF_CONDUCT*",
            "--ignore", "SECURITY.md",
            "--ignore", "CHANGELOG*",
            "--ignore", "HISTORY*",
            "--ignore", "RELEASES*",
            # Add other common patterns if needed (e.g., logs, specific config files)
            "--ignore", "*.log",
        ]
        cmd.extend(ignore_flags)
        
        # Run the command and capture output
        try:
            # Log the command being run for debugging if needed
            # console.print(f"[dim]Running command: {' '.join(cmd)}[/dim]") 
            subprocess.run(cmd, stdout=temp_file, check=True, cwd=BASE_DIR) # Ensure correct CWD
            temp_file.flush()
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error running files-to-prompt:[/bold red] {e}")
            # Attempt to read stderr if available
            if e.stderr:
                 try:
                     stderr_output = e.stderr.decode('utf-8')
                     console.print(f"[red]files-to-prompt stderr:[/red]\n{stderr_output}")
                 except Exception:
                     console.print("[red](Could not decode stderr)[/red]")
            return f"Error analyzing repository: files-to-prompt failed. {e}"
        except FileNotFoundError:
            console.print(f"[bold red]Error: 'files-to-prompt' command not found. Is it installed and in PATH?[/bold red]")
            return "Error analyzing repository: files-to-prompt not found."

        # Read the output
        temp_file.seek(0)
        prompt = temp_file.read()

        # --- Refined File Detail Extraction ---
        prompt_lines = prompt.split('\n')
        file_details = [] # Store full paths now
        for i, line in enumerate(prompt_lines):
            # Check if the line looks like a path (not indented, not ```, not ---)
            # AND the next line starts with ``` (code block marker)
            if line and not line.startswith((' ', '\t', '`', '---')):
                if i + 1 < len(prompt_lines) and prompt_lines[i+1].startswith('```'):
                    # Construct potential full path and verify it exists within repo_dir
                    try:
                        # Assume line is relative to repo_dir
                        potential_full_path = (repo_dir / line).resolve()
                        # Ensure it's actually within the repo directory
                        if potential_full_path.is_file() and repo_dir.resolve() in potential_full_path.parents:
                            file_details.append(str(potential_full_path))
                    except Exception: 
                        # Ignore lines that cause errors during path construction/resolution
                        pass 
        # --- End Refined File Detail Extraction ---

    # --- Prepare Input Text Content ---
    input_text_content = f"# Input Files for {repo_dir.name} Analysis\n\n"
    input_text_content += "## Files Analyzed\n\n"
    # Iterate through the validated full paths
    for full_filename_str in file_details:
        full_filename_path = Path(full_filename_str)
        # Use relative path for cleaner output
        try:
            relative_filename = full_filename_path.relative_to(repo_dir.resolve())
            input_text_content += f"- `{relative_filename}`\n"
        except ValueError:
             # Fallback if relative_to fails (should be rare now)
             input_text_content += f"- `{full_filename_str}` (Error getting relative path)\n"
    input_text_content += f"\n## Combined File Content\n\n{prompt}\n"

    # Save input text to separate file
    input_text_filename = learnings_path / f"{repo_dir.name}-input-text.md"
    try:
        with open(input_text_filename, "w", encoding="utf-8") as f:
            f.write(input_text_content)
        console.print(f"[dim]Saved input text details to {input_text_filename}[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save input text file: {e}[/yellow]")
    # --- End Input Text Handling ---

    # --- Calculate Token Count and Available Output Tokens ---
    # Create the full analysis prompt FIRST
    analysis_prompt_template = REPO_ANALYSIS_PROMPT
    full_analysis_prompt = prompt + "\n\n" + analysis_prompt_template # Use template for initial calc

    input_tokens = 0
    available_output_tokens = 0
    context_window = 0 # Initialize
    
    try:
        # Use tiktoken to count tokens (cl100k_base is default for gpt-4/3.5)
        encoding = tiktoken.get_encoding("cl100k_base")
        input_tokens = len(encoding.encode(full_analysis_prompt))
        console.print(f"[dim]Input tokens estimate (cl100k_base): {input_tokens}[/dim]")
        
        # Get context window for the selected model
        try:
            model_config = current_config["models"]["available_models"][language_model]
            context_window = model_config["context_window"]
            console.print(f"[dim]Model context window: {context_window}[/dim]")

            # Calculate available output tokens with 10% buffer
            available_output_tokens = int((context_window - input_tokens) * 0.9)
            if available_output_tokens < 0:
                available_output_tokens = 0 # Prevent negative tokens
            console.print(f"[dim]Available output tokens (target): {available_output_tokens}[/dim]")

        except KeyError:
            console.print(f"[yellow]Warning: Could not find model '{language_model}' or 'context_window' in config.yaml. Cannot calculate available output tokens.[/yellow]")
            available_output_tokens = -1 # Indicate failure to calculate
        except Exception as e:
             console.print(f"[yellow]Warning: Error accessing context window from config: {e}[/yellow]")
             available_output_tokens = -1 # Indicate failure to calculate

    except tiktoken.RegistryError:
         console.print("[yellow]Warning: Tiktoken encoding 'cl100k_base' not found. Cannot estimate tokens.[/yellow]")
         available_output_tokens = -1 # Indicate failure to calculate
    except Exception as e:
        console.print(f"[yellow]Warning: Error counting tokens with tiktoken: {e}[/yellow]")
        available_output_tokens = -1 # Indicate failure to calculate
    # --- End Token Calculation ---

    # --- Modify Prompt with Token Limit ---
    final_repo_analysis_prompt = analysis_prompt_template
    if available_output_tokens != -1: # Only add if calculation succeeded
        final_repo_analysis_prompt = analysis_prompt_template.replace(
            "<available_output_tokens>", 
            str(available_output_tokens)
        )
    else:
        # If calculation failed, remove the placeholder line or replace with generic message
        final_repo_analysis_prompt = "\n".join(
            line for line in analysis_prompt_template.split('\n') 
            if "<available_output_tokens>" not in line
        )
        final_repo_analysis_prompt += "\nWarning: Output token limit could not be determined."

    # Construct the final prompt parts
    user_prompt_content = prompt # The combined file content
    system_prompt_content = final_repo_analysis_prompt # The analysis instructions

    # Send the prompt to the local LLM using direct model loading
    timestamp = datetime.now().strftime("%H:%M:%S")
    console.print(f"[{timestamp}] [bold green]Generating AI analysis...[/bold green]")
    
    try:
        # Let llm library handle model loading and plugin dispatch
        import llm 
        model = llm.get_model(language_model)

        # Generate the response using the MODIFIED prompt
        # Conditionally pass max_tokens based on model provider prefix
        if language_model.startswith("gemini-"):
            # Gemini plugin doesn't accept max_tokens here
            response = model.prompt(
                prompt=user_prompt_content,
                system=system_prompt_content
            )
        else:
            # Assume other models (like local mlx) might accept max_tokens
            response = model.prompt(
                prompt=user_prompt_content,
                system=system_prompt_content,
                max_tokens=available_output_tokens 
            )
        
        response_text = response.text() # Keep getting the text

        # Format the successful analysis output with the new header
        analysis_header = f"# {repo_dir.name} github repo reviewed by {language_model}\n\n"
        final_analysis_output = analysis_header + response_text
    except Exception as e:
        error_message = str(e)
        console.print(f"[bold red]Error generating AI analysis:[/bold red] {e}")
        
        # Format the error output with the new header style
        error_header = f"# {repo_dir.name} github repo reviewed by {language_model}\n\n"
        final_analysis_output = error_header + f"Error generating analysis: {e}\n\n"
        final_analysis_output += f"Make sure the model '{language_model}' is available.\n"
        final_analysis_output += f"You can install MLX models with: `llm mlx download-model {language_model}`\n"

        # Add context length warning if that's the issue
        if "sequence length is longer than the specified maximum" in error_message:
            console.print("[bold yellow]Warning: Repository content exceeds model context length.[/yellow]")
            console.print("[bold yellow]Consider using a model with a larger context window for better results.[/yellow]")
            final_analysis_output += f"\n\nWarning: Repository content likely exceeds model context length.\n"
            final_analysis_output += f"Consider using a model with a larger context window.\n"

    return final_analysis_output # Return only the final formatted analysis or error