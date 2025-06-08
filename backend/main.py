# backend/main.py
from fastapi import FastAPI, Request as FastAPIRequest, HTTPException, UploadFile, File, Form, Query, Path
# Renamed Request to FastAPIRequest to avoid conflict with GoogleAuthRequest
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import os
import json
import io
import logging # Import logging
from .logging_config import setup_logging # Import setup_logging

# Call setup_logging() to configure logging for the application
setup_logging()

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# --- Pydantic Models (from previous step, ensure they are here) ---
class MessageResponse(BaseModel):
    message: str = Field(..., example="Operation successful")
class StatusResponse(BaseModel):
    status: str = Field(..., example="Backend is running")
class AuthURLResponse(BaseModel):
    authorization_url: str = Field(..., example="https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=...")
    state: str = Field(..., example="random_state_string", description="CSRF protection state token.")
class CredentialsModel(BaseModel):
    token: str | None = Field(None, example="dummy_access_token") # descriptions omitted for brevity here, but should be present from prev step
    refresh_token: str | None = Field(None, example="dummy_refresh_token")
    token_uri: str | None = Field(None, example="https://oauth2.googleapis.com/token")
    client_id: str | None = Field(None, example="YOUR_GOOGLE_CLIENT_ID_HERE")
    client_secret: str | None = Field(None, example="YOUR_GOOGLE_CLIENT_SECRET_HERE")
    scopes: list[str] | None = Field(None, example=["https://www.googleapis.com/auth/drive.file"])
    id_token: str | None = Field(None, example="dummy_id_token")
class AuthCallbackResponse(BaseModel):
    message: str = Field(..., example="Authentication successful (simulated).")
    credentials: CredentialsModel | None = Field(None)
class UserProfileResponse(BaseModel):
    message: str = Field(..., example="User is authenticated (simulated).")
    data: CredentialsModel | None = Field(None)
class DriveFile(BaseModel):
    id: str = Field(..., description="Google Drive File ID")
    name: str = Field(..., description="Name of the file or folder")
    mimeType: str = Field(..., description="MIME type of the file")
    size: str | None = Field(None, description="Size of the file in bytes")
    modifiedTime: str | None = Field(None, description="Last modified time")
    iconLink: str | None = Field(None, description="Link to file's icon")
    webViewLink: str | None = Field(None, description="Link to view in browser")
    webContentLink: str | None = Field(None, description="Link to download content")
class FileListResponse(BaseModel):
    items: list[DriveFile] = Field(..., description="List of files and folders.")
    nextPageToken: str | None = Field(None, description="Token for next page.")
class CreatedFolderResponse(BaseModel):
    id: str = Field(..., description="ID of the new folder.")
    name: str = Field(..., description="Name of the new folder.")
    message: str = Field(default="Folder created successfully")
class UploadedFileResponse(BaseModel):
    id: str = Field(..., description="ID of the uploaded file.")
    name: str = Field(..., description="Name of the uploaded file.")
    link: str | None = Field(None, description="Link to view file.")
    message: str = Field(default="File uploaded successfully")
class DownloadSimulatedResponse(BaseModel):
    message: str = Field(..., description="Info about simulated download.")
    name: str | None = Field(None)
    file_id: str | None = Field(None)
    webViewLink: str | None = Field(None)

from . import config

app = FastAPI(
    title="Google Drive Explorer API",
    description="An API to interact with Google Drive, including authentication and file operations...",
    version="1.0.0",
    contact={"name": "API Support", "url": "http://example.com/support", "email": "support@example.com"},
    license_info={"name": "MIT License", "url": "https://opensource.org/licenses/MIT"},
)

logger.info("Application starting up...", extra={"props": {"app_title": app.title, "app_version": app.version}})

user_sessions = {}

# --- Middleware for Logging Requests ---
@app.middleware("http")
async def log_requests_middleware(request: FastAPIRequest, call_next):
    client_host = request.client.host if request.client else "unknown"
    # Reducing header verbosity for logs; log specific headers if needed.
    # For example, only 'user-agent' and 'content-type'.
    relevant_headers = {
        "user-agent": request.headers.get("user-agent"),
        "content-type": request.headers.get("content-type"),
        "accept": request.headers.get("accept"),
    }
    extra_props = {
        "method": request.method,
        "url": str(request.url),
        "client_host": client_host,
        "headers": relevant_headers
    }
    logger.info("Incoming request", extra={"props": extra_props})

    response = await call_next(request)

    extra_props_resp = {
        "method": request.method,
        "url": str(request.url),
        "status_code": response.status_code
    }
    logger.info("Request finished", extra={"props": extra_props_resp})
    return response

# --- Authentication Endpoints ---
@app.get("/api/auth/login/google", summary="Initiate Google OAuth 2.0 Login", tags=["Authentication"])
async def login_google(request: FastAPIRequest): # Changed 'Request' to 'FastAPIRequest'
    logger.info("Initiating Google OAuth 2.0 login flow.")
    flow = Flow.from_client_config(
        client_config={ "web": { "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [config.GOOGLE_REDIRECT_URI], "javascript_origins": ["http://localhost:3000"] }},
        scopes=config.SCOPES, redirect_uri=config.GOOGLE_REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    user_sessions['oauth_state'] = state
    logger.info("Generated authorization URL and state for CSRF.", extra={"props": {"auth_url_domain": authorization_url.split('/')[2], "state_len": len(state)}})
    return RedirectResponse(authorization_url)

@app.get("/api/auth/callback/google", response_model=AuthCallbackResponse, summary="Google OAuth 2.0 Callback", tags=["Authentication"])
async def auth_callback_google(
    request: FastAPIRequest,
    code: str = Query(..., description="Authorization code from Google."),
    state: str = Query(..., description="CSRF state token from Google.")
):
    logger.info("Received callback from Google OAuth.", extra={"props": {"has_code": bool(code), "received_state_len": len(state)}})
    stored_state = user_sessions.get('oauth_state')
    if not stored_state or stored_state != state:
        logger.warning("Invalid CSRF state token.", extra={"props": {"expected_state": stored_state, "received_state": state}})
        raise HTTPException(status_code=400, detail="Invalid CSRF state token.")
    user_sessions.pop('oauth_state', None)
    logger.info("CSRF state token verified successfully.")
    try:
        flow = Flow.from_client_config(client_config={ "web": { "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [config.GOOGLE_REDIRECT_URI], }}, scopes=config.SCOPES, redirect_uri=config.GOOGLE_REDIRECT_URI)
        logger.info("Simulating token fetch with authorization code.", extra={"props": {"code_len": len(code)}})
        # Actual token fetch is commented out for simulation
        # flow.fetch_token(code=code)
        # credentials = flow.credentials
        credentials_dict_data = {'token': 'dummy_access_token', 'refresh_token': 'dummy_refresh_token', 'token_uri': 'https://oauth2.googleapis.com/token', 'client_id': config.GOOGLE_CLIENT_ID, 'client_secret': config.GOOGLE_CLIENT_SECRET, 'scopes': config.SCOPES }
        credentials = Credentials.from_authorized_user_info(credentials_dict_data)
        user_sessions['credentials'] = credentials_to_dict(credentials)
        logger.info("Successfully (simulated) fetched and stored credentials.", extra={"props": {"scopes_granted": credentials.scopes}})
        return AuthCallbackResponse(message="Authentication successful (simulated).", credentials=CredentialsModel(**credentials_dict_data))
    except Exception as e:
        logger.error(f"Error during (simulated) token exchange: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

def credentials_to_dict(credentials: Credentials) -> dict:
    return {'token': credentials.token, 'refresh_token': credentials.refresh_token, 'token_uri': credentials.token_uri, 'client_id': credentials.client_id, 'client_secret': credentials.client_secret, 'scopes': credentials.scopes, 'id_token': getattr(credentials, 'id_token', None)}

@app.get("/api/me", response_model=UserProfileResponse, summary="Check Authentication Status", tags=["Authentication"])
async def get_me(request: FastAPIRequest): # Changed 'Request' to 'FastAPIRequest'
    logger.debug("Checking user authentication status (/api/me).")
    creds_dict = user_sessions.get('credentials')
    if not creds_dict:
        logger.info("User is not authenticated (no credentials in session).")
        raise HTTPException(status_code=401, detail="Not authenticated")
    logger.info("User is authenticated. Returning (simulated) profile.", extra={"props": {"client_id": creds_dict.get('client_id')}})
    return UserProfileResponse(message="User is authenticated (simulated).", data=CredentialsModel(**creds_dict))

# --- Helper to get Google Drive Service ---
def get_drive_service(request: FastAPIRequest): # Changed 'Request' to 'FastAPIRequest'
    logger.debug("Attempting to get Google Drive service instance.")
    creds_dict = user_sessions.get('credentials')
    if not creds_dict:
        logger.warning("Credentials not found in session. User needs to authenticate.")
        raise HTTPException(status_code=401, detail="User not authenticated. Please login first via /api/auth/login/google")

    credentials = Credentials.from_authorized_user_info(creds_dict)
    if credentials.expired and credentials.refresh_token:
        logger.info("Token is expired, attempting (simulated) refresh.", extra={"props": {"client_id": credentials.client_id}})
        try:
            # credentials.refresh(GoogleAuthRequest()) # Real refresh
            if credentials.token == 'dummy_access_token': # Simulate refresh
                credentials.token = 'refreshed_dummy_access_token'
                user_sessions['credentials'] = credentials_to_dict(credentials)
            logger.info("Token refresh (simulated) successful.")
        except Exception as e:
            logger.error(f"Error refreshing token (simulated): {str(e)}", exc_info=True)
            user_sessions.pop('credentials', None)
            raise HTTPException(status_code=401, detail=f"Failed to refresh token, please re-authenticate: {str(e)}")

    if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
        logger.warning("Using placeholder Google Client ID. Drive API calls will be SIMULATED by MockDriveService.")
        # MockDriveService definition (simplified for brevity, assume it's complete from previous steps)
        class MockDriveService:
            def __init__(self): logger.debug("MockDriveService initialized.")
            def files(self): return self
            def list(self, **kwargs): logger.info("MockDriveService: files().list() called", extra={"props": kwargs}); return self
            def execute(self): logger.info("MockDriveService: ...execute() called"); return {'files': [{'id': 'sim_id_1', 'name': 'Simulated File.txt', 'mimeType': 'text/plain', 'size': '1024', 'modifiedTime': '2023-01-01T12:00:00Z', 'iconLink': 'sim_icon_link', 'webViewLink': 'sim_webview_link'}], 'nextPageToken': None}
            def create(self, **kwargs): body = kwargs.get("body", {}); logger.info("MockDriveService: files().create() called", extra={"props": {"body": body, "fields": kwargs.get("fields")}}); return {"id": "sim_created_id", "name": body.get("name", "sim_created_item"), 'mimeType': body.get('mimeType', 'text/plain')}
            def get(self, fileId, fields="*"): logger.info(f"MockDriveService: files().get(fileId='{fileId}') called", extra={"props":{"fileId":fileId, "fields":fields}}); class MG: execute=lambda: ({'id': fileId, 'name': 'Simulated Get File.txt', 'mimeType': 'text/plain'}); return MG()
            def get_media(self, fileId): logger.info(f"MockDriveService: files().get_media(fileId='{fileId}') called", extra={"props":{"fileId":fileId}}); class MGM: execute=lambda: (io.BytesIO(b"simulated file content")); return MGM()
            def delete(self, fileId): logger.info(f"MockDriveService: files().delete(fileId='{fileId}') called", extra={"props":{"fileId":fileId}}); class MD: execute=lambda: (None); return MD()
            def update(self, fileId, body): logger.info(f"MockDriveService: files().update(fileId='{fileId}') called", extra={"props":{"fileId":fileId, "body":body}}); class MU: execute=lambda: ({'id': fileId, 'name': body.get('name', 'updated_name.txt')}); return MU()
        return MockDriveService()

    logger.info("Building real Google Drive service instance.")
    try:
        service = build('drive', 'v3', credentials=credentials)
        logger.info("Successfully built real Google Drive service instance.")
        return service
    except HttpError as error:
        logger.error(f"HttpError building Drive service: {error.resp.status} - {error._get_reason()}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build Google Drive service: {error.resp.status} - {error._get_reason()}")
    except Exception as e:
        logger.error(f"General error building Drive service: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"General error building Google Drive service: {str(e)}")

# --- Google Drive API Endpoints (with logging) ---
@app.get("/api/drive/files", response_model=FileListResponse, summary="List Files and Folders", tags=["Drive Operations"])
async def list_files(
    request: FastAPIRequest,
    folder_id: str = Query('root', description="ID of the folder to list.", example="root"),
    page_size: int = Query(10, description="Items per page.", example=20, ge=1, le=100)
):
    logger.info(f"Listing files for folder_id: {folder_id}", extra={"props": {"folder_id": folder_id, "page_size": page_size}})
    service = get_drive_service(request)
    try:
        q = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(q=q, pageSize=page_size, fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, iconLink, webViewLink, webContentLink)").execute()
        items = results.get('files', [])
        logger.info(f"Found {len(items)} files/folders in folder_id: {folder_id}", extra={"props": {"item_count": len(items), "folder_id": folder_id, "has_next_page": bool(results.get('nextPageToken'))}})
        return FileListResponse(items=[DriveFile(**item) for item in items], nextPageToken=results.get('nextPageToken'))
    except HttpError as error:
        logger.error(f"HttpError listing files for folder '{folder_id}': {error.resp.status} - {error._get_reason()}", exc_info=True, extra={"props": {"folder_id": folder_id, "status_code": error.resp.status}})
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        logger.error(f"Unexpected error listing files for folder '{folder_id}': {str(e)}", exc_info=True, extra={"props": {"folder_id": folder_id}})
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/drive/folders", response_model=CreatedFolderResponse, summary="Create New Folder", tags=["Drive Operations"])
async def create_folder(
    request: FastAPIRequest,
    folder_name: str = Form(..., description="Name for the new folder.", example="My Project")
):
    logger.info(f"Attempting to create folder: {folder_name}", extra={"props": {"target_folder_name": folder_name}})
    service = get_drive_service(request)
    try:
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            folder = service.files().create(body=file_metadata, fields='id, name')
        else:
            folder = service.files().create(body=file_metadata, fields='id, name').execute()
        logger.info(f"Folder '{folder.get('name')}' created successfully with ID '{folder.get('id')}'", extra={"props": {"created_folder_id": folder.get('id'), "created_folder_name": folder.get('name')}})
        return CreatedFolderResponse(**folder)
    except HttpError as error:
        logger.error(f"HttpError creating folder '{folder_name}': {error.resp.status} - {error._get_reason()}", exc_info=True, extra={"props": {"folder_name": folder_name, "status_code": error.resp.status}})
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        logger.error(f"Unexpected error creating folder '{folder_name}': {str(e)}", exc_info=True, extra={"props": {"folder_name": folder_name}})
        raise HTTPException(status_code=500, detail=f"Error creating folder: {str(e)}")


@app.post("/api/drive/files/upload", response_model=UploadedFileResponse, summary="Upload File", tags=["Drive Operations"])
async def upload_file(
    request: FastAPIRequest,
    file: UploadFile = File(..., description="The file to upload."),
    folder_id: str = Form(None, description="Optional ID of the folder to upload into.", example="folder_id_example")
):
    logger.info(f"Attempting to upload file: {file.filename}", extra={"props": {"filename": file.filename, "content_type": file.content_type, "target_folder_id": folder_id}})
    service = get_drive_service(request)
    media_body_for_create = None
    try:
        file_metadata = {'name': file.filename}
        if folder_id: file_metadata['parents'] = [folder_id]
        contents = await file.read()
        media_body_for_create = io.BytesIO(contents)

        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            created_file = service.files().create(body=file_metadata, media_body=media_body_for_create, fields='id, name, webViewLink')
        else:
            media_upload = MediaIoBaseUpload(media_body_for_create, mimetype=file.content_type, resumable=True)
            created_file = service.files().create(body=file_metadata, media_body=media_upload, fields='id, name, webViewLink').execute()

        logger.info(f"File '{created_file.get('name')}' uploaded successfully with ID '{created_file.get('id')}'", extra={"props": {"uploaded_file_id": created_file.get('id'), "uploaded_file_name": created_file.get('name'), "size": len(contents)}})
        return UploadedFileResponse(id=created_file.get('id'), name=created_file.get('name'), link=created_file.get('webViewLink'))
    except HttpError as error:
        logger.error(f"HttpError uploading file '{file.filename}': {error.resp.status} - {error._get_reason()}", exc_info=True, extra={"props": {"filename": file.filename, "status_code": error.resp.status}})
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        logger.error(f"Unexpected error uploading file '{file.filename}': {str(e)}", exc_info=True, extra={"props": {"filename": file.filename}})
        raise HTTPException(status_code=500, detail=f"An error occurred during upload: {str(e)}")
    finally:
        if media_body_for_create: media_body_for_create.close()
        if file: await file.close()


@app.get("/api/drive/files/{file_id}/download", summary="Download File", tags=["Drive Operations"], responses={200: {}, 202: {"model": DownloadSimulatedResponse}})
async def download_file(
    request: FastAPIRequest,
    file_id: str = Path(..., description="ID of the file to download.", example="file_id_example")
):
    logger.info(f"Attempting to download file_id: {file_id}", extra={"props": {"file_id": file_id}})
    service = get_drive_service(request)
    try:
        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            file_metadata = service.files().get(fileId=file_id, fields="name, mimeType, webViewLink").execute()
        else:
            file_metadata = service.files().get(fileId=file_id, fields="name, mimeType, webViewLink, webContentLink").execute()
        file_name = file_metadata.get("name", "downloaded_file")
        mime_type = file_metadata.get('mimeType', '')

        if mime_type.startswith('application/vnd.google-apps'):
            logger.info(f"File '{file_name}' (ID: {file_id}) is a Google Workspace document. Returning info, direct download requires export.", extra={"props": {"file_id": file_id, "file_name": file_name, "mime_type": mime_type}})
            return JSONResponse(status_code=202, content=DownloadSimulatedResponse(message=f"File '{file_name}' is a Google Workspace document. Export is required.", name=file_name, file_id=file_id, webViewLink=file_metadata.get('webViewLink')).model_dump(exclude_none=True))

        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            simulated_content = service.files().get_media(fileId=file_id).execute()
            simulated_content.seek(0)
            logger.info(f"Simulated download for file_id: {file_id}, name: {file_name}", extra={"props": {"file_id": file_id, "file_name": file_name}})
            return StreamingResponse(simulated_content, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=sim_{file_name}"})

        api_request_obj = service.files().get_media(fileId=file_id)
        fh_download = io.BytesIO()
        downloader = MediaIoBaseDownload(fh_download, api_request_obj)
        done = False
        logger.info(f"Starting direct download for file_id: {file_id}, name: {file_name}", extra={"props": {"file_id": file_id, "file_name": file_name}})
        while not done:
            status, done = downloader.next_chunk()
            if status: logger.debug(f"Download progress for {file_id}: {int(status.progress() * 100)}%", extra={"props": {"file_id": file_id, "progress": status.progress()}})
        fh_download.seek(0)
        logger.info(f"Successfully downloaded file_id: {file_id}, name: {file_name}", extra={"props": {"file_id": file_id, "file_name": file_name, "size_bytes": fh_download.getbuffer().nbytes}})
        return StreamingResponse(fh_download, media_type=mime_type or "application/octet-stream", headers={"Content-Disposition": f"attachment; filename=\"{file_name}\""})
    except HttpError as error:
        logger.error(f"HttpError downloading file '{file_id}': {error.resp.status} - {error._get_reason()}", exc_info=True, extra={"props": {"file_id": file_id, "status_code": error.resp.status}})
        detail_message = str(error) # Default
        if error.resp.status == 404: detail_message = f"File not found: {file_id}"
        if error.resp.status == 403 : detail_message = f"Access denied for file {file_id}. If it's a Google Workspace file, export is needed."
        raise HTTPException(status_code=error.resp.status, detail=detail_message)
    except Exception as e:
        logger.error(f"Unexpected error downloading file '{file_id}': {str(e)}", exc_info=True, extra={"props": {"file_id": file_id}})
        raise HTTPException(status_code=500, detail=f"An error occurred during download: {str(e)}")

@app.delete("/api/drive/files/{file_id}", response_model=MessageResponse, summary="Delete File or Folder", tags=["Drive Operations"])
async def delete_file_endpoint( # Renamed to avoid conflict with 'delete_file' if used as a var
    request: FastAPIRequest,
    file_id: str = Path(..., description="ID of the file or folder to delete.", example="file_id_example")
):
    logger.info(f"Attempting to delete item_id: {file_id}", extra={"props": {"item_id": file_id}})
    service = get_drive_service(request)
    try:
        service.files().delete(fileId=file_id).execute()
        logger.info(f"Successfully deleted item_id: {file_id}", extra={"props": {"item_id": file_id}})
        return MessageResponse(message=f"File/Folder with ID: {file_id} deleted successfully.")
    except HttpError as error:
        logger.error(f"HttpError deleting item '{file_id}': {error.resp.status} - {error._get_reason()}", exc_info=True, extra={"props": {"item_id": file_id, "status_code": error.resp.status}})
        if error.resp.status == 404: raise HTTPException(status_code=404, detail=f"File/Folder not found: {file_id}")
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        logger.error(f"Unexpected error deleting item '{file_id}': {str(e)}", exc_info=True, extra={"props": {"item_id": file_id}})
        raise HTTPException(status_code=500, detail=f"Error deleting item: {str(e)}")


@app.patch("/api/drive/files/{file_id}/rename", response_model=DriveFile, summary="Rename File or Folder", tags=["Drive Operations"])
async def rename_file_endpoint( # Renamed
    request: FastAPIRequest,
    file_id: str = Path(..., description="ID of the file/folder to rename.", example="file_id_example"),
    new_name: str = Form(..., description="The new name.", example="Updated Project Name")
):
    logger.info(f"Attempting to rename item_id: {file_id} to '{new_name}'", extra={"props": {"item_id": file_id, "new_name": new_name}})
    service = get_drive_service(request)
    try:
        file_metadata_update = {'name': new_name}
        if config.GOOGLE_CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_HERE":
            updated_file_data = service.files().update(fileId=file_id, body=file_metadata_update, fields='id, name, mimeType, size, modifiedTime, iconLink, webViewLink, webContentLink').execute()
        else:
            updated_file_data = service.files().update(fileId=file_id, body=file_metadata_update, fields='id, name, mimeType, size, modifiedTime, iconLink, webViewLink, webContentLink').execute()
        logger.info(f"Successfully renamed item_id: {file_id} to '{updated_file_data.get('name')}'", extra={"props": {"item_id": file_id, "updated_name": updated_file_data.get('name')}})
        return DriveFile(**updated_file_data)
    except HttpError as error:
        logger.error(f"HttpError renaming item '{file_id}': {error.resp.status} - {error._get_reason()}", exc_info=True, extra={"props": {"item_id": file_id, "new_name": new_name, "status_code": error.resp.status}})
        if error.resp.status == 404: raise HTTPException(status_code=404, detail=f"File/Folder not found: {file_id}")
        raise HTTPException(status_code=error.resp.status, detail=str(error))
    except Exception as e:
        logger.error(f"Unexpected error renaming item '{file_id}': {str(e)}", exc_info=True, extra={"props": {"item_id": file_id, "new_name": new_name}})
        raise HTTPException(status_code=500, detail=f"Error renaming item: {str(e)}")

# --- Basic App Endpoints ---
@app.get("/", response_model=MessageResponse, summary="Root Endpoint", tags=["General"])
async def root():
    logger.info("Root endpoint '/' accessed.")
    return MessageResponse(message="FastAPI Backend for Google Drive")

@app.get("/api/status", response_model=StatusResponse, summary="API Status", tags=["General"])
async def get_status_endpoint():
    logger.info("API status endpoint '/api/status' accessed.")
    return StatusResponse(status="Backend is running with Drive integration")

# Redundant __init__.py check, should be handled by file creation in earlier step
# if not os.path.exists(os.path.join(os.path.dirname(__file__), "__init__.py")):
#     with open(os.path.join(os.path.dirname(__file__), "__init__.py"), "w") as f:
#         f.write("# Automatically created by main.py\n")
#         logger.info("Created backend/__init__.py as it was missing.")
