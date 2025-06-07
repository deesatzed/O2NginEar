# backend/main.py
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import os
import json
import io

from . import config

app = FastAPI()

# In-memory store for demonstration. In production, use a proper session store or database.
user_sessions = {} # This should persist from the auth step

# --- Authentication Endpoints (from previous step, abridged for focus) ---
@app.get("/api/auth/login/google")
async def login_google(request: Request):
    # ... (existing code from previous step)
    flow = Flow.from_client_config(
        client_config={ "web": { "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [config.GOOGLE_REDIRECT_URI], "javascript_origins": ["http://localhost:3000"] }},
        scopes=config.SCOPES, redirect_uri=config.GOOGLE_REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    user_sessions['oauth_state'] = state
    return RedirectResponse(authorization_url)

@app.get("/api/auth/callback/google")
async def auth_callback_google(request: Request, code: str, state:str):
    # ... (existing code from previous step, with simulated token fetch)
    stored_state = user_sessions.get('oauth_state')
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="Invalid CSRF state token.")
    user_sessions.pop('oauth_state', None)
    try:
        flow = Flow.from_client_config(client_config={ "web": { "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [config.GOOGLE_REDIRECT_URI], }}, scopes=config.SCOPES, redirect_uri=config.GOOGLE_REDIRECT_URI)
        # Simulate token fetch
        print(f"Simulating token fetch for code: {code}")
        credentials_dict = {'token': 'dummy_access_token', 'refresh_token': 'dummy_refresh_token', 'token_uri': 'https://oauth2.googleapis.com/token', 'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET, 'scopes': config.SCOPES }
        credentials = Credentials.from_authorized_user_info(credentials_dict)
        user_sessions['credentials'] = credentials_to_dict(credentials)
        return JSONResponse(content={"message": "Authentication successful (simulated).", "credentials": credentials_to_dict(credentials)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

def credentials_to_dict(credentials):
    return {'token': credentials.token, 'refresh_token': credentials.refresh_token, 'token_uri': credentials.token_uri, 'client_id': credentials.client_id, 'client_secret': credentials.client_secret, 'scopes': credentials.scopes, 'id_token': getattr(credentials, 'id_token', None)}

# --- Helper to get Google Drive Service ---
def get_drive_service(request: Request):
    creds_dict = user_sessions.get('credentials') # Get from our mock session
    if not creds_dict:
        raise HTTPException(status_code=401, detail="User not authenticated. Please login first via /api/auth/login/google")

    # Reconstruct credentials object
    # In a real app, you might need to handle token refresh here
    credentials = Credentials.from_authorized_user_info(creds_dict)

    # Check if token is (conceptually) expired and refresh if possible
    # This is a simplified check. `google-auth` library handles this more robustly if credentials are valid.
    if credentials.expired and credentials.refresh_token:
        try:
            print("Simulating token refresh...")
            # In a real scenario, this would make a call to Google's token endpoint.
            # credentials.refresh(GoogleAuthRequest())
            # For this subtask, we'll just update a dummy token value if it was 'dummy_access_token'
            if credentials.token == 'dummy_access_token':
                credentials.token = 'refreshed_dummy_access_token'
                user_sessions['credentials'] = credentials_to_dict(credentials) # Update stored credentials
            print("Token refresh simulated.")
        except Exception as e:
            print(f"Error refreshing token (simulated): {e}")
            # If refresh fails, user might need to re-authenticate
            user_sessions.pop('credentials', None) # Clear invalid credentials
            raise HTTPException(status_code=401, detail=f"Failed to refresh token, please re-authenticate: {str(e)}")

    if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
        print("WARNING: Using placeholder Google Client ID. Drive API calls will be simulated.")
        # Return a mock service if using placeholder credentials to avoid HttpError during build()
        class MockDriveService:
            def files(self): return self
            def list(self, **kwargs): return self
            def execute(self):
                print(f"Simulated Drive API Call: files().list() with params: {kwargs}")
                return {'files': [{'id': 'sim_id_1', 'name': 'Simulated File.txt', 'mimeType': 'text/plain'}, {'id': 'sim_id_2', 'name': 'Simulated Folder', 'mimeType': 'application/vnd.google-apps.folder'}]}
            def create(self, **kwargs):
                print(f"Simulated Drive API Call: files().create() with params: {kwargs}")
                # For create, Google API returns the created resource directly, not an object needing another .execute()
                # Let's simulate that it returns a dictionary representing the created file/folder
                created_resource = {"id": "sim_created_id", "name": kwargs.get("body", {}).get("name", "sim_created_item")}
                print(f"Simulated Drive API Call: files().create() result: {created_resource}")
                return created_resource  # Return the dict directly
            def get(self, fileId, fields="*"):
                print(f"Simulated Drive API Call: files().get(fileId='{fileId}', fields='{fields}')")
                return self # chain execute
            def get_media(self, fileId):
                    print(f"Simulated Drive API Call: files().get_media(fileId='{fileId}')")
                    # This typically returns a MediaIoBaseDownload object or similar, not directly executable in this way for mock
                    # For simplicity, we'll make it chainable to an execute that returns mock data
                    class MockMediaDownloader:
                        def __init__(self, file_id_mock):
                            self.file_id_mock = file_id_mock
                        def execute(self): # Mocking the execute for get_media result
                            print(f"Simulated Media Download Execute for fileId: {self.file_id_mock}")
                            # Simulate returning some bytes or a structure indicating success
                            return io.BytesIO(b"simulated file content")
                    return MockMediaDownloader(fileId) # Return an object that can be "executed"
            def delete(self, fileId):
                print(f"Simulated Drive API Call: files().delete(fileId='{fileId}')")
                return self # chain execute
            def update(self, fileId, body):
                print(f"Simulated Drive API Call: files().update(fileId='{fileId}', body='{body}')")
                return self # chain execute

        return MockDriveService()

    try:
        service = build('drive', 'v3', credentials=credentials)
        return service
    except HttpError as error:
        print(f'An error occurred building Drive service: {error}')
        # Clear potentially bad credentials
        # user_sessions.pop('credentials', None) # Commented out for subtask to avoid issues if build fails once.
        raise HTTPException(status_code=500, detail=f"Failed to build Google Drive service: {error.resp.status} - {error._get_reason()}")
    except Exception as e:
        # Catch other potential errors during service build, e.g., misconfiguration
        print(f'A general error occurred building Drive service: {e}')
        raise HTTPException(status_code=500, detail=f"General error building Google Drive service: {str(e)}")


# --- Google Drive API Endpoints ---

@app.get("/api/drive/files")
async def list_files(request: Request, folder_id: str = 'root', page_size: int = 10):
    service = get_drive_service(request)
    try:
        q = f"'{folder_id}' in parents and trashed=false"
        # For MockDriveService, list().execute() is already defined to return a dict
        results = service.files().list(
            q=q,
            pageSize=page_size,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, iconLink, webViewLink, webContentLink)"
        ).execute() # This execute is part of the mock structure for list()

        items = results.get('files', [])
        return {"items": items, "nextPageToken": results.get('nextPageToken')}
    except HttpError as error:
        print(f'An error occurred: {error}')
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        print(f'An list_files error occurred: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/drive/folders")
async def create_folder(request: Request, folder_name: str = Form(...)):
    service = get_drive_service(request)
    try:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        # For MockDriveService, create() is defined to return the created resource dict directly
        # For real service, create().execute() is needed.
        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            folder = service.files().create(body=file_metadata, fields='id, name') # Mock returns dict
        else:
            folder = service.files().create(body=file_metadata, fields='id, name').execute() # Real call

        return {"id": folder.get('id'), "name": folder.get('name'), "message": "Folder created successfully"}
    except HttpError as error:
        raise HTTPException(status_code=error.resp.status, detail=str(error))

@app.post("/api/drive/files/upload")
async def upload_file(request: Request, file: UploadFile = File(...), folder_id: str = Form(None)): # folder_id is optional
    service = get_drive_service(request)
    fh = None  # Initialize fh to None
    try:
        file_metadata = {'name': file.filename}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        contents = await file.read()
        fh = io.BytesIO(contents)

        media = MediaFileUpload(
            file.filename, # Pass filename for mimetype detection by library
            mimetype=file.content_type,
            resumable=True
        )
        # Important: Set the content for MediaFileUpload AFTER initialization if using BytesIO directly with it
        # However, Google's library is a bit tricky here. It's often better to pass the BytesIO object as the filename if it supports it,
        # or save to a temp file. For MediaFileUpload, it expects a filename string, and then reads from that path.
        # To use BytesIO directly with media_body in files().create(), we don't pass it to MediaFileUpload constructor.

        # Let's adjust how MediaFileUpload is used or bypass it for BytesIO if possible.
        # The googleapiclient.http.MediaIoBaseUpload is more suitable for io.BytesIO.
        # For simplicity with MediaFileUpload, it works best if it can read from the path `file.filename`.
        # Since we have `contents`, we can use MediaIoBaseUpload.

        media_body_for_create = io.BytesIO(contents) # Use a fresh BytesIO for the upload body

        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            print(f"Simulating file upload for: {file.filename} to folder: {folder_id} with media type: {file.content_type}")
            # MockDriveService.files().create() returns a dict directly
            created_file = service.files().create(body=file_metadata, media_body=media_body_for_create, fields='id, name, webViewLink')
        else:
            # Use MediaIoBaseUpload for direct upload from BytesIO
            media_upload = MediaIoBaseUpload(media_body_for_create, mimetype=file.content_type, resumable=True)
            created_file = service.files().create(
                body=file_metadata,
                media_body=media_upload, # Use MediaIoBaseUpload instance here
                fields='id, name, webViewLink'
            ).execute()

        return {"id": created_file.get('id'), "name": created_file.get('name'), "link": created_file.get('webViewLink'), "message": "File uploaded successfully"}
    except HttpError as error:
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        print(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred during upload: {str(e)}")
    finally:
        if fh:
            fh.close()
        if 'media_body_for_create' in locals() and media_body_for_create:
            media_body_for_create.close()
        await file.close()


@app.get("/api/drive/files/{file_id}/download")
async def download_file(file_id: str, request: Request):
    service = get_drive_service(request)
    try:
        # Mock service.files().get().execute() returns a predefined dict
        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            # Simulate get().execute() behavior for mock
            mock_file_metadata_response = service.files().get(fileId=file_id, fields="name, mimeType, webViewLink").execute()
            file_metadata = mock_file_metadata_response # In mock, execute() on get() returns the dict
        else:
            file_metadata = service.files().get(fileId=file_id, fields="name, mimeType, webViewLink, webContentLink").execute()

        file_name = file_metadata.get("name", "downloaded_file")
        mime_type = file_metadata.get('mimeType', '')

        if mime_type.startswith('application/vnd.google-apps'):
            if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
                print(f"Simulating download (export) for Google Workspace file: {file_id}")
                return JSONResponse(content={
                    "message": "Simulated download for Google Workspace file. Use webViewLink or implement export.",
                    "name": file_name, "webViewLink": file_metadata.get('webViewLink')
                })
            # Actual export logic is complex and depends on chosen format (e.g., PDF, DOCX)
            # For now, return a message indicating export is needed.
            return JSONResponse(content={"message": f"File '{file_name}' is a Google Workspace document. Export is required. WebViewLink: {file_metadata.get('webViewLink')}"})

        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            print(f"Simulating get_media for file: {file_id}")
             # Simulate what get_media().execute() would give for mock
            simulated_content = service.files().get_media(fileId=file_id).execute() # This is an io.BytesIO from mock
            simulated_content.seek(0)
            return StreamingResponse(simulated_content, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=sim_{file_name}"})

        api_request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, api_request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status: print(f"Download {int(status.progress() * 100)}%.")
        fh.seek(0)
        media_type_for_response = mime_type if mime_type else "application/octet-stream"
        return StreamingResponse(fh, media_type=media_type_for_response, headers={"Content-Disposition": f"attachment; filename=\"{file_name}\""})

    except HttpError as error:
        if error.resp.status == 404: raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        if error.resp.status == 403 and 'cannot be downloaded' in str(error).lower():
             raise HTTPException(status_code=403, detail=f"File {file_id} ({file_metadata.get('name', '')}) is likely a Google Workspace document and needs to be exported.")
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        print(f"Download error for {file_id}: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred during download: {str(e)}")

@app.delete("/api/drive/files/{file_id}")
async def delete_file(file_id: str, request: Request):
    service = get_drive_service(request)
    try:
        # For MockDriveService, delete().execute() is needed
        service.files().delete(fileId=file_id).execute()
        return {"message": f"File/Folder with ID: {file_id} deleted successfully."}
    except HttpError as error:
        if error.resp.status == 404:
            raise HTTPException(status_code=404, detail=f"File/Folder not found: {file_id}")
        raise HTTPException(status_code=error.resp.status, detail=str(error))

@app.patch("/api/drive/files/{file_id}/rename")
async def rename_file(file_id: str, new_name: str = Form(...), request: Request):
    service = get_drive_service(request)
    try:
        file_metadata = {'name': new_name}
        # For MockDriveService, update().execute() is needed
        updated_file = service.files().update(fileId=file_id, body=file_metadata, fields='id, name').execute()
        return {"id": updated_file.get('id'), "name": updated_file.get('name'), "message": "File/Folder renamed successfully"}
    except HttpError as error:
        if error.resp.status == 404:
            raise HTTPException(status_code=404, detail=f"File/Folder not found: {file_id}")
        raise HTTPException(status_code=error.resp.status, detail=str(error))

# Root and status endpoints (can be minimal now)
@app.get("/")
async def root(): return {"message": "FastAPI Backend for Google Drive"}
@app.get("/api/status")
async def get_status(): return {"status": "Backend is running with Drive integration"}

# Ensure __init__.py exists for `from . import config`
# This check might be redundant if __init__.py is guaranteed to exist by previous steps.
if not os.path.exists(os.path.join(os.path.dirname(__file__), "__init__.py")):
    with open(os.path.join(os.path.dirname(__file__), "__init__.py"), "w") as f:
        f.write("# Automatically created by main.py\n")
