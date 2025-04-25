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


def analyze_repository(repo_dir: Path, language_model: str, max_files: int = None):
    """Analyze a repository using files-to-prompt and local LLM.
    
    Args:
        repo_dir: Path to the repository directory
        language_model: Name of the language model to use
        max_files: Maximum number of files to include in analysis (None = use config value)
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

    # Use config value if max_files is not provided
    if max_files is None:
        max_files = current_config.get("analysis", {}).get("max_files", 3) # Default to 3 if missing

    # --- DEBUG LOG --- 
    print(f"DEBUG: Effective max_files = {max_files}")
    # --- END DEBUG LOG ---

    max_prompt_chars = current_config.get("analysis", {}).get("max_prompt_chars", 15000) # Default if missing

    console.print(f"[bold green]Analyzing repository[/bold green]: {repo_dir}")
    console.print(f"[bold green]Using language model[/bold green]: {language_model}")
    console.print(f"[bold green]Max files to process[/bold green]: {'Unlimited' if max_files <= 0 else max_files}")
    console.print(f"[bold green]Max prompt characters[/bold green]: {max_prompt_chars}")
    
    # Remove any "mlx:" prefix if present
    if language_model.startswith("mlx:"):
        language_model = language_model.replace("mlx:", "", 1)
    
    # Get list of files in the repository
    file_list = []
    
    # Walk through the repository directory
    excluded_dirs = {'.git', '.venv', 'venv', 'node_modules', 'dist', 'build', 'target', 'docs', 'doc', 'tests'}
    # Add common non-code files to exclude (case-insensitive)
    excluded_files = {
        'license', 'license.txt', 'license.md',
        'copying', 'copying.txt', 'copying.md',
        'notice', 'notice.txt', 'notice.md',
        'contributing', 'contributing.md', 'contributing.txt',
        'code_of_conduct', 'code_of_conduct.md', 'code_of_conduct.txt',
        'security.md',
        'changelog', 'changelog.md', 'changelog.txt',
        'history', 'history.md', 'history.txt',
        'releases', 'releases.md',
    }
    for root, dirs, files in os.walk(repo_dir):
        # Skip hidden directories and explicitly excluded directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in excluded_dirs]
        
        for file in files:
            # Skip hidden files and explicitly excluded filenames
            if file.startswith('.') or file.lower() in excluded_files:
                continue
                
            file_path = os.path.join(root, file)
            try:
                # Try to read the file as text to ensure it's not binary
                with open(file_path, 'r', encoding='utf-8') as f:
                    f.read(1024)  # Just read a bit to check if it's text
                file_list.append(file_path)
            except UnicodeDecodeError:
                # Skip binary files
                continue
    
    # Limit the number of files if max_files is set
    if max_files > 0 and len(file_list) > max_files:
        console.print(f"[bold yellow]Limiting analysis to {max_files} files (out of {len(file_list)}) to fit context window[/bold yellow]")
        file_list = file_list[:max_files]
    
    # Create a temporary file to store the output
    with tempfile.NamedTemporaryFile(delete=False, mode='w+') as temp_file:
        # Build the command to run files-to-prompt with markdown option
        cmd = [sys.executable, "-m", "files_to_prompt", "--markdown"]
            
        # Add file paths to command
        cmd.extend(file_list)
        
        # Run the command and capture output
        try:
            subprocess.run(cmd, stdout=temp_file, check=True)
            temp_file.flush()
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error running files-to-prompt:[/bold red] {e}")
            return f"Error analyzing repository: {e}"

        # Read the output
        temp_file.seek(0)
        prompt = temp_file.read()

        # --- DEBUG LOG --- 
        print(f"DEBUG: Length of files-to-prompt output (prompt var): {len(prompt)}")
        # --- END DEBUG LOG ---
        
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

        # --- REMOVED LOG A ---

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

    # Construct the final prompt sent to the model
    final_prompt_for_llm = prompt + "\n\n" + final_repo_analysis_prompt
    # --- End Prompt Modification ---

    # Send the prompt to the local LLM using direct model loading
    timestamp = datetime.now().strftime("%H:%M:%S")
    console.print(f"[{timestamp}] [bold green]Generating AI analysis...[/bold green]")
    
    try:
        # Instead of using llm.get_model, directly use MlxModel
        try:
            from llm_mlx import MlxModel
            model = MlxModel(language_model)
        except ImportError:
            # Fallback to llm's get_model if llm_mlx isn't available
            import llm
            model = llm.get_model(language_model)
        
        # --- DEBUG LOG (using final prompt length) ---
        print(f"DEBUG: Length of FINAL prompt sent to LLM (chars): {len(final_prompt_for_llm)}")
        # --- END DEBUG LOG ---

        # --- Fail Fast Check (Use Character Limit for now) ---
        # Note: We could potentially use the *input_tokens* count vs a token limit 
        # derived from max_prompt_chars, but char limit is simpler for now.
        if len(final_prompt_for_llm) > max_prompt_chars:
            error_message = (
                f"Combined prompt content ({len(final_prompt_for_llm)} characters) exceeds the configured character limit "
                f"({max_prompt_chars} characters). Analysis aborted."
            )
            console.print(f"[bold red]Error: {error_message}[/bold red]")
            console.print("Consider increasing 'max_prompt_chars' in config.yaml, reducing '--max-files',")
            console.print("or using a model with a larger context window.")
            error_header = f"# {repo_dir.name} github repo reviewed by {language_model}\n\n"
            return error_header + f"Error: {error_message}\n" # Return the error with the new header
        # --- End Fail Fast Check ---

        # Generate the response using the MODIFIED prompt
        # Try passing max_tokens directly to the prompt method
        response = model.prompt(
            final_prompt_for_llm, 
            max_tokens=available_output_tokens # Pass calculated limit
        )
        
        # --- DEBUG LOG ---
        response_text = response.text()
        print(f"DEBUG: Raw response_text length: {len(response_text)}")
        print(f"DEBUG: Raw response_text START: {response_text[:200]}...")
        print(f"DEBUG: Raw response_text END: ...{response_text[-200:]}")
        # --- END DEBUG LOG ---

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