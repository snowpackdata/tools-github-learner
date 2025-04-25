# tools-github-learner

Building off of the amazingly elegant work of [Simon Willison](https://github.com/simonw), here is a much less elegant, but still quite useful tool to analyze GitHub repositories. The intent is to help you quickly understand a repo, build on it, integrate it, and/or emulate it.
Happy learning from Snowpack Data!

## ...but why??
Why build this when a Cloud model can do something similar very quickly (and as of April 2025, frankly much more powerfully)?
1. At [Snowpack Data](https://snowpack-data.com/) we are building towards an open-source future where increasingly cutting-edge capabilities are accessible locally, securely, offline, and - most importanly - for free. We're not there yet, but the community is on its way...
2. We're all about learning. No better way to learn than to build!
3. Pay an homage to great builders like Simon who generously open-source their work for everyone's benefit.

## Features

*   **Analyze Repositories:** Clones a GitHub repo and generates an analysis (architecture overview, use cases, dependencies, security concerns, etc.).
*   **Configuration:** Uses `config.yaml` for setting paths and default models.
*   **Model Support:** 
    *   Supports local models via MLX (`llm-mlx` plugin).
    *   Supports Google Gemini models via API (`llm-gemini` plugin).
    *   Easily extendable via the `llm` library's plugin system... bring whatever models you want!
*   **Versioning:** Creates versioned analysis files (e.g., `repo-analysis-v1.md`, `repo-analysis-v2.md`) instead of overwriting.
*   **Token Management:** Roughly estimates input tokens and calculates available output tokens based on the selected model's context window (from `config.yaml`), instructing the model to stay within limits. This is a work in progress.
*   **Cleanup:** Provides a command to remove cloned repositories and input files.
*   **Refresh:** Provides a command to completely remove the output directory and all its contents (repos, inputs, analyses).
*   **List:** Lists previously analyzed repositories.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/snowpackdata/tools-github-learner.git
    cd tools-github-learner
    ```

2.  **Create a virtual environment (`uv` recommended):**
    ```bash
    uv venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -e .
    ```
    This installs the tool in editable mode along with dependencies like `click`, `llm`, `llm-mlx`, `llm-gemini`, `tiktoken`, `GitPython`, `PyYAML`, `Rich`, and `files-to-prompt`.

4.  **Configure LLM:**
    *   **Local Models (MLX):** Install desired MLX models using `llm mlx download-model <model-name>`. Example models are listed in `config.yaml`.
    *   **Gemini Models:** 
        *   Obtain a Gemini API key from Google AI Studio.
        *   Set the key for `llm`: 
            ```bash
            llm keys set gemini
            # Paste your API key when prompted
            ```
            Alternatively, set the `LLM_GEMINI_KEY` environment variable (e.g., in your `.zshrc` or `.bashrc`, make sure it's exported: `export LLM_GEMINI_KEY="YOUR_API_KEY"`). **Note:** The plugin expects `LLM_GEMINI_KEY`
    *   Update `config.yaml` to set your desired `default_model` and add/verify `context_window` for models in `available_models`.

## Configuration (`config.yaml`)

*   `paths`: 
    *   `output_dir`: Directory to store cloned repos and analysis files (default: `learnings`). Supports `~` expansion.
*   `models`:
    *   `default_model`: The model to use if `-m` is not specified.
    *   `available_models`: A mapping of model names (matching `llm` identifiers) to their properties, primarily `context_window` (in tokens).

## Usage

```bash
# Basic analysis (uses default model from config)
# Example: Uses 'mlx-community/gemma-3-27b-it-qat-4bit' if that's the default
gl analyze https://github.com/snowpackdata/tools-github-learner

# Specify a different model (e.g., Gemini Flash)
# Requires API key setup (see Installation)
gl analyze -m gemini-2.5-flash-preview-04-17 https://github.com/snowpackdata/tools-github-learner

# Specify a different local model
gl analyze -m mlx-community/SmolLM-135M-Instruct-4bit https://github.com/snowpackdata/tools-github-learner

# Analyze and save to a specific file (disables auto-versioning for this run)
gl analyze https://github.com/snowpackdata/tools-github-learner --output-file my-custom-analysis.md

# List analyzed repositories
gl list

# Clean up all cloned repos and input files in the output directory
gl cleanup

# Refresh (delete) the entire output directory and its contents
gl refresh

# View current configuration (combines config file and CLI overrides)
gl config
```

## How it Works

1.  **Clone:** Clones the target repository into the `output_dir`.
2.  **Gather Files:** Uses `files-to-prompt` to collect content from non-excluded files.
3.  **Token Calculation:** 
    *   Combines file content with the analysis prompt.
    *   Uses `tiktoken` (cl100k_base) to estimate input token count.
    *   Looks up the selected model's `context_window` in `config.yaml`.
    *   Calculates available output tokens (`(context_window - input_tokens) * 0.9`). 90% is conservative buffer.
    *   Injects the calculated output token limit into the final prompt sent to the LLM, if accepted. Gemini models do not support this.
4.  **LLM Interaction:** Sends the combined prompt (including the token limit instruction) to the specified LLM (local via MLX or remote via Gemini API) using the `llm` library.
5.  **Save Output:** Saves the LLM's response to a versioned markdown file (e.g., `learnings/repo-name-analysis-v1.md`).

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
Better yet, contribute directly to Simon's [llm](https://github.com/simonw/llm) and [files-to-prompt](https://github.com/simonw/files-to-prompt) libraries :D

## License

MIT License