# Google Drive Explorer - System Architecture

## 1. Overview

This project is a web application that provides a user interface to interact with a user's Google Drive. It allows listing files and folders, creating folders, uploading files, downloading files, renaming, and deleting items.

The application consists of a React frontend and a FastAPI (Python) backend.

## 2. Components

### 2.1. Frontend (`my-drive-app/`)

*   **Technology:** React.js, Tailwind CSS.
*   **Responsibilities:**
    *   Rendering the user interface.
    *   Handling user interactions (clicks, forms, uploads).
    *   Making API calls to the backend to perform Google Drive operations.
    *   Managing client-side state (authentication status, file lists, UI state).
*   **Key Directories/Files:**
    *   `public/`: Static assets and `index.html`.
    *   `src/`: Main application source code.
        *   `App.js`: Root component, main layout, and routing logic.
        *   `apiService.js`: Service layer for all backend API communications.
        *   `components/` (Conceptual): Reusable UI components (though current structure is mostly within `App.js`).
        *   `index.css`: Global styles and Tailwind CSS imports.
*   **Build:** `npm run build` creates static assets in `my-drive-app/build/`.

### 2.2. Backend (`backend/`)

*   **Technology:** FastAPI (Python 3).
*   **Responsibilities:**
    *   Providing a RESTful API for the frontend.
    *   Handling user authentication with Google (OAuth 2.0 flow).
    *   Interacting with the Google Drive API using the `google-api-python-client`.
    *   Implementing business logic for file and folder operations.
*   **Key Modules/Files:**
    *   `main.py`: Defines all API endpoints, integrates Google Drive service logic, and handles request/response validation using Pydantic models.
    *   `config.py`: Manages application configuration, primarily Google OAuth credentials (loaded from environment variables).
    *   `logging_config.py`: Configures structured JSON logging for the application.
    *   `MockDriveService` (within `main.py` currently): A mock implementation of the Google Drive service used for development and when real credentials are not available. This allows the API to function conceptually without live calls.
*   **API Documentation:** Auto-generated OpenAPI (Swagger UI) documentation available at `/docs` and ReDoc at `/redoc` when the backend is running.

### 2.3. Docker Setup (Local Development)

*   **`Dockerfile` (in `backend/` and `my-drive-app/`):** Defines how to build images for the backend and frontend services.
*   **`docker-compose.yml` (project root):** Orchestrates the local development environment. It builds and runs containers for the frontend and backend, enabling hot-reloading for code changes and easy startup with `docker-compose up --build`.
*   Environment variables for the backend (like Google API keys) can be set in `docker-compose.yml` or preferably via a `.env` file at the project root.

## 3. Data Flow & Key Processes

### 3.1. User Authentication (OAuth 2.0)

1.  **Frontend:** User clicks "Login with Google".
2.  **Frontend:** Redirects to the backend's `/api/auth/login/google` endpoint.
3.  **Backend:** Generates a Google OAuth authorization URL and redirects the user's browser to Google's consent screen.
4.  **Google:** User authenticates and grants permission. Google redirects back to the backend's `GOOGLE_REDIRECT_URI` (`/api/auth/callback/google`) with an authorization code.
5.  **Backend:** Receives the code, exchanges it with Google for an access token and refresh token (simulated in the current mock setup). Stores these tokens (conceptually, in `user_sessions` for this demo; would be a secure session/DB store in production).
6.  **Backend:** Responds to the frontend (e.g., with a success message or by setting a session cookie). The frontend updates its state to reflect authentication.

### 3.2. Typical API Request (e.g., Listing Files)

1.  **Frontend:** User navigates to a folder. `App.js` calls `listFiles(folderId)` from `apiService.js`.
2.  **`apiService.js`:** Makes a GET request to the backend's `/api/drive/files?folder_id=<folderId>` endpoint.
3.  **Backend (`main.py`):**
    *   The corresponding path operation receives the request.
    *   `get_drive_service()` is called to obtain an authenticated Google Drive service client (either real or mock). This involves checking for stored credentials.
    *   The service client calls the Google Drive API (`service.files().list(...).execute()`).
    *   The response from Google Drive API is processed.
4.  **Backend:** Sends a JSON response containing the list of files and folders back to the frontend.
5.  **Frontend:** `apiService.js` returns the data. `App.js` updates its state, re-rendering the UI to display the files.

## 4. Google Drive Integration

*   **Credentials:** The backend requires `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (obtained from GCP Console) and a `GOOGLE_REDIRECT_URI`. These are loaded from environment variables via `config.py`.
*   **Scopes:** The application requests scopes like `https://www.googleapis.com/auth/drive.file` (full read/write access to files created or opened by the app) and potentially `https://www.googleapis.com/auth/drive.metadata.readonly` or broader scopes if needed. Current setup uses `drive.file`.

## 5. Error Handling

*   **Backend:** FastAPI uses `HTTPException` to return appropriate HTTP error responses with JSON details. Pydantic handles request validation errors automatically. Unhandled exceptions are caught by a generic error handler (implicitly) or can be customized. Errors are logged using structured JSON logging.
*   **Frontend:** `apiService.js` attempts to parse error responses from the backend. `App.js` displays error messages to the user.

## 6. Logging

*   **Backend:** Uses structured JSON logging configured in `logging_config.py`. Logs include timestamps, levels, messages, module/function info, and contextual data. Request logging middleware logs all incoming requests and their responses.

---
This document provides a high-level overview. For more detailed information, refer to the code and inline comments.
