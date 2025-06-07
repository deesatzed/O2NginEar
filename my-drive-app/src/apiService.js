// my-drive-app/src/apiService.js

// Helper function for API requests
const request = async (url, options = {}) => {
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: response.statusText }));
      throw new Error(errorData.detail || errorData.message || `HTTP error! status: ${response.status}`);
    }
    // For 204 No Content or similar, response.json() will fail.
    if (response.status === 204) {
        return null;
    }
    return await response.json();
  } catch (error) {
    console.error("API request error:", error);
    throw error; // Re-throw to be caught by the caller
  }
};

export const loginWithGoogle = () => {
  // The backend handles the redirect to Google and then the callback.
  // The frontend just needs to navigate to this backend endpoint.
  window.location.href = '/api/auth/login/google';
};

export const checkAuthStatus = async () => {
  // This endpoint will tell us if we have credentials stored in the backend's mock session
  return request('/api/me');
};

export const listFiles = async (folderId = 'root', pageSize = 10) => {
  return request(`/api/drive/files?folder_id=${folderId}&page_size=${pageSize}`);
};

export const createFolder = async (folderName) => {
  const formData = new FormData();
  formData.append('folder_name', folderName);
  return request('/api/drive/folders', {
    method: 'POST',
    body: formData,
  });
};

export const uploadFile = async (file, folderId = null) => {
  const formData = new FormData();
  formData.append('file', file);
  if (folderId) {
    formData.append('folder_id', folderId);
  }
  return request('/api/drive/files/upload', {
    method: 'POST',
    body: formData,
  });
};

export const deleteItem = async (itemId) => {
  return request(`/api/drive/files/${itemId}`, {
    method: 'DELETE',
  });
};

export const renameItem = async (itemId, newName) => {
  const formData = new FormData();
  formData.append('new_name', newName);
  return request(`/api/drive/files/${itemId}/rename`, {
    method: 'PATCH',
    body: formData,
  });
};

export const downloadFile = async (fileId, fileName) => {
    try {
        const response = await fetch(`/api/drive/files/${fileId}/download`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: response.statusText }));
            throw new Error(errorData.detail || errorData.message || `HTTP error! status: ${response.status}`);
        }

        // For Google Workspace files, backend might return JSON message instead of blob
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            const jsonData = await response.json();
            alert(jsonData.message || "Could not download. This might be a Google Workspace file requiring export.");
            return; // Or handle differently
        }

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = fileName || 'downloaded_file'; // Use provided filename
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
    } catch (error) {
        console.error("Download error:", error);
        alert(`Download failed: ${error.message}`);
        throw error;
    }
};
