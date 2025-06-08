# CI/CD Pipeline Overview

## 1. Introduction

This document outlines the conceptual Continuous Integration/Continuous Deployment (CI/CD) pipeline for the Google Drive Explorer project. The goal is to automate code quality checks, testing, and deployments.

## 2. Platform Choice

**GitHub Actions** is recommended due to its tight integration with GitHub repositories. Other platforms like GitLab CI, Jenkins, or Google Cloud Build could also be used.

## 3. Triggers

The pipeline workflows will be triggered on:
*   Pushes to the `main` branch.
*   Pushes to `develop` branch (if used).
*   Pull requests targeting the `main` (or `develop`) branch.

## 4. Workflows

### 4.1. Linting, Testing, and Build Workflow (`ci.yml`)

This workflow runs on every push to main/develop and on every PR.

```yaml
# .github/workflows/ci.yml (Example GitHub Actions Workflow)
name: CI Checks

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10']
        node-version: ['18.x']

    steps:
    - name: Checkout code
      uses: actions/checkout@v3

    # Backend Python Setup and Checks
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v3
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install backend dependencies
      working-directory: ./backend
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        # Ensure linters are installed if not already in requirements.txt for CI
        # pip install black flake8 pytest

    - name: Lint with Flake8 (Backend)
      working-directory: ./backend
      run: flake8 . --count --show-source --statistics

    - name: Check formatting with Black (Backend)
      working-directory: ./backend
      run: black . --check --diff

    - name: Run backend tests with PyTest (Conceptual)
      working-directory: ./backend
      run: pytest # (Requires test files and pytest setup)

    # Frontend Node.js Setup and Checks
    - name: Set up Node.js ${{ matrix.node-version }}
      uses: actions/setup-node@v3
      with:
        node-version: ${{ matrix.node-version }}
        cache: 'npm'
        cache-dependency-path: my-drive-app/package-lock.json

    - name: Install frontend dependencies
      working-directory: ./my-drive-app
      run: npm ci # Use npm ci for cleaner installs in CI

    - name: Lint with ESLint (Frontend)
      working-directory: ./my-drive-app
      run: npm run lint

    - name: Check formatting with Prettier (Frontend)
      working-directory: ./my-drive-app
      run: npm run check-format

    - name: Run frontend tests with Jest (Conceptual)
      working-directory: ./my-drive-app
      run: npm test -- --watchAll=false # (Acknowledging current script issues)

    - name: Build frontend application
      working-directory: ./my-drive-app
      run: npm run build # (Acknowledging current script issues)
```

### 4.2. Deployment Workflow (`deploy.yml` - Conceptual)

This workflow would be triggered on merges/pushes to the `main` branch (typically after successful CI checks).

*   **Steps:**
    1.  All steps from the "Linting, Testing, and Build Workflow".
    2.  **Build Docker Images:**
        *   Build the backend Docker image: `docker build -t gcr.io/YOUR_PROJECT_ID/drive-backend:$GITHUB_SHA ./backend`
        *   Build the frontend Docker image: `docker build -t gcr.io/YOUR_PROJECT_ID/drive-frontend:$GITHUB_SHA ./my-drive-app`
    3.  **Authenticate to Container Registry:** (e.g., Google Container Registry, Docker Hub).
    4.  **Push Docker Images:**
        *   `docker push gcr.io/YOUR_PROJECT_ID/drive-backend:$GITHUB_SHA`
        *   `docker push gcr.io/YOUR_PROJECT_ID/drive-frontend:$GITHUB_SHA`
    5.  **Deploy to Target Environment:**
        *   **Backend (e.g., Google Cloud Run):**
            `gcloud run deploy drive-backend-service --image gcr.io/YOUR_PROJECT_ID/drive-backend:$GITHUB_SHA --region YOUR_REGION --platform managed --allow-unauthenticated` (adjust flags as needed).
        *   **Frontend (e.g., Firebase Hosting or Google Cloud Storage):**
            `firebase deploy --only hosting` (if using Firebase).
            Or `gsutil rsync -R my-drive-app/build gs://YOUR_FRONTEND_BUCKET` (if using GCS).

## 5. Environment Variables & Secrets

*   **Secrets Management:** Sensitive information (Google API keys, container registry credentials, deployment keys) must be stored as encrypted secrets in the CI/CD platform's settings (e.g., GitHub repository secrets).
*   **Accessing Secrets:** Secrets are accessed in workflow files using expressions like `${{ secrets.YOUR_SECRET_NAME }}`.

## 6. Future Improvements

*   Automated versioning based on git tags or commit history.
*   Notifications for build/deployment status (e.g., Slack, email).
*   Staging/QA environments with approval steps before production deployment.
*   Security scanning for Docker images and dependencies.
*   Performance testing.
