# GitHub Learner

A CLI tool for analyzing GitHub repositories using local LLMs.

## Features

- Clone and analyze GitHub repositories
- Process code using Simon Willison's [files-to-prompt](https://github.com/simonw/files-to-prompt)
- Generate repository insights using local MLX models

## Requirements

- Python 3.12+
- Git
- MLX-compatible system (Apple Silicon Mac for MLX acceleration)

## Installation

```bash
# Clone repository
git clone https://github.com/snowpackdata/tools-github-learner.git
cd tools-github-learner

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install with pip
pip install -e .

# Ensure an MLX model is available
# In the future, the package will allow for Cloud models
# Check installed models (you should have at least one MLX model)
llm mlx models

# If no models are installed, download the default SmolLM model:
llm mlx download-model mlx-community/gemma-3-12b-it-8bit

# Or register an existing model from your Hugging Face cache:
llm mlx import-models

# For better performance, try a larger model (if your system can handle it):
llm mlx download-model mlx-community/gemma-3-27b-it-8bit
```

## Project Structure

tools-github-learner/
├── pyproject.toml         # Project metadata and dependencies
├── .gitignore             # Ignores learnings directory and Python artifacts
├── config.yaml            # Configuration file
├── README.md              # Project documentation
├── src/                   # Python package source
│   ├── __init__.py        # Package initialization
│   ├── cli.py             # Command-line interface
│   ├── core.py            # Core functionality
│   └── prompts.py         # LLM prompt templates
└── learnings/             # Output directory (gitignored)
    ├── repository/        # Cloned repositories 
    └── repository-analysis.md  # Analysis output files

## Usage

```bash
# Basic analysis
gl analyze https://github.com/simonw/files-to-prompt

# Save output to file
gl analyze https://github.com/simonw/files-to-prompt -f analysis.md

# Limit analysis to just a few files (helpful for large repositories)
gl analyze https://github.com/simonw/datasette --max-files 5

# List previously analyzed repositories
gl list

# View or update configuration
gl config

# Get help
gl --help
```

## Configuration

GitHub Learner requires a YAML config file named `config.yaml` located in the project root directory (where you run the `gl` command). If this file is missing or invalid, the tool will exit with an error.

A default `config.yaml` is included in the repository:

```yaml
paths:
  base_dir: '/absolute/path/to/tools-github-learner' # Auto-detected, usually no need to change
  output_dir: learnings # Directory relative to base_dir for cloned repos and analyses
models:
  default_model: mlx-community/SmolLM-135M-Instruct-4bit # Default model ID for analysis
  alternatives: # List of other available models (for reference)
    - mlx-community/Llama-3.2-3B-Instruct-4bit
    - mlx-community/gemma-3-1b-it-qat-8bit
analysis:
  max_files: 3 # Default max files (3 = conservative for small models, 0 = unlimited)
  max_prompt_chars: 15000 # Default max characters for the combined prompt
```

You can use any MLX model registered with the LLM CLI. For a better experience with larger repositories, consider using a larger model.

**Important Notes on Defaults & Limits:**

*   The default `max_files` is set to **3** to ensure basic functionality even with small models like SmolLM, which have limited context windows.
*   A `max_prompt_chars` limit (default: 15000) is enforced. If the total characters of the collected file contents plus the analysis instructions exceed this limit, the analysis will be aborted with an error message *before* calling the LLM. This prevents generating nonsensical output due to context overflow.
*   For analyzing more files or larger repositories:
    1.  Increase the file limit: `gl analyze <url> --max-files <number>`
    2.  Increase the character limit: Edit `max_prompt_chars` in `config.yaml`.
    3.  Use a model with a larger context window: `gl analyze <url> -m <larger_model_name>`
    4.  Consider using Cloud models via `llm` if local model capacity is insufficient.

## How it Works

1.  **Cloning:** Clones the target repository into the `output_dir` specified in `config.yaml`.
2.  **File Collection:** Uses `files-to-prompt` to gather the content of text files (up to `max_files`), excluding hidden files/dirs, test dirs, docs, build artifacts, and virtual environments.
3.  **Prompt Assembly:** Combines the collected file content with analysis instructions.
4.  **Limit Check:** Verifies if the combined prompt exceeds `max_prompt_chars`. If so, aborts with an error.
5.  **LLM Analysis:** Sends the prompt to the specified `default_model` (or the one provided via `-m`) using the `llm` library (specifically `llm-mlx`).
6.  **Output:** Saves the analysis (or error message) to a markdown file in the `output_dir`.

**Note**: Smaller models like SmolLM have limited context length (2048 tokens) which may result in truncated analysis for larger repositories. For better results with larger codebases:

1. Use a model with a larger context window like Gemma-3.
2. Limit the number of files analyzed with the `--max-files` option
3. For production use, consider using a large local model or Cloud model