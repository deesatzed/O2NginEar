# Contributing to Google Drive Explorer

First off, thank you for considering contributing! Your help is appreciated. These are guidelines to help you get started.

## Getting Started

1.  **Fork and Clone:** Fork the repository and clone it locally.
2.  **Set up Environment:** This project uses Docker Compose for local development. Ensure you have Docker installed.
    ```bash
    docker-compose up --build
    ```
    This will start the frontend (React) on `http://localhost:3000` and the backend (FastAPI) on `http://localhost:8000`.
3.  **Install Linters (Locally, optional if primarily using Docker for linting):**
    *   **Backend (Python):** `pip install black flake8` (preferably in a virtual environment).
    *   **Frontend (JavaScript/React):** `npm install` in the `my-drive-app` directory should set up ESLint if configured in `package.json`.

## Branching Strategy

*   Create feature branches from the `main` (or `develop` if it exists) branch. Example: `feature/my-cool-feature` or `fix/login-bug`.
*   Ensure `main` always reflects a stable, deployable state.

## Making Changes

*   **Code Style:**
    *   **Backend (Python):** Follow PEP 8. Use Black for auto-formatting and Flake8 for linting. Configuration for these tools will be added to the project (e.g., `pyproject.toml`).
    *   **Frontend (React/JS):** Follow the existing code style. ESLint and Prettier (or similar) will be configured to enforce consistency.
*   **Commit Messages:** Aim for clear and descriptive commit messages. Consider using [Conventional Commits](https://www.conventionalcommits.org/) for a structured approach. Example:
    ```
    feat: Add file renaming functionality
    fix: Correct error handling in file download
    docs: Update ARCHITECTURE.md with new component details
    ```
*   **Testing:**
    *   Write tests for new functionality. (Details on testing frameworks and execution to be added once fully set up).
    *   Ensure all existing tests pass before submitting a PR.

## Pull Request (PR) Process

1.  **Create a PR:** Push your feature branch to your fork and open a PR against the `main` (or `develop`) branch of the upstream repository.
2.  **Title and Description:** Use a clear and descriptive title for your PR. In the description, explain the changes you've made and reference any relevant issues.
3.  **Code Review:** At least one other developer should review and approve the PR. Address any feedback or comments.
4.  **Merging:** Once approved and all checks pass, the PR can be merged.

## Code of Conduct

Please note that this project is released with a Contributor Code of Conduct. By participating in this project you agree to abide by its terms. (A formal CODE_OF_CONDUCT.md file would be added for a public project). For now, please be respectful and constructive in all interactions.

---

Happy coding!
