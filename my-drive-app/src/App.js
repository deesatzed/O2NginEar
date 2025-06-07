// my-drive-app/src/App.js
import React, { useState, useEffect, useCallback } from 'react';
import * as api from './apiService'; // Import API service
import './App.css'; // Assuming index.css has @tailwind directives

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [files, setFiles] = useState([]);
  const [currentFolderId, setCurrentFolderId] = useState('root');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showCreateFolderModal, setShowCreateFolderModal] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [fileToUpload, setFileToUpload] = useState(null);

  // Check auth status on mount
  useEffect(() => {
    const checkStatus = async () => {
      setIsLoading(true);
      try {
        await api.checkAuthStatus();
        setIsAuthenticated(true);
      } catch (e) {
        setIsAuthenticated(false);
        // No error display needed if just not logged in
        console.log("User not authenticated or session expired.");
      } finally {
        setIsLoading(false);
      }
    };
    checkStatus();
  }, []);

  const fetchFiles = useCallback(async (folderId) => {
    if (!isAuthenticated) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.listFiles(folderId);
      setFiles(data.items || []);
    } catch (err) {
      setError(err.message);
      setFiles([]); // Clear files on error
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]); // Recreate if isAuthenticated changes

  useEffect(() => {
    if (isAuthenticated) {
      fetchFiles(currentFolderId);
    } else {
      setFiles([]); // Clear files if not authenticated
    }
  }, [isAuthenticated, currentFolderId, fetchFiles]);

  const handleLogin = () => {
    api.loginWithGoogle(); // This will redirect
  };

  const handleCreateFolder = async ()_ => {
    if (!newFolderName.trim()) {
      alert("Folder name cannot be empty.");
      return;
    }
    setIsLoading(true);
    try {
      await api.createFolder(newFolderName);
      setShowCreateFolderModal(false);
      setNewFolderName('');
      fetchFiles(currentFolderId); // Refresh file list
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFileUpload = async () => {
    if (!fileToUpload) {
      alert("Please select a file to upload.");
      return;
    }
    setIsLoading(true);
    try {
      await api.uploadFile(fileToUpload, currentFolderId === 'root' ? null : currentFolderId);
      setFileToUpload(null); // Clear selection
      document.getElementById('fileUploadInput').value = ''; // Reset file input
      fetchFiles(currentFolderId); // Refresh file list
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (itemId, itemName) => {
    if (window.confirm(`Are you sure you want to delete "${itemName}"?`)) {
      setIsLoading(true);
      try {
        await api.deleteItem(itemId);
        fetchFiles(currentFolderId);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleRename = async (itemId, currentName) => {
    const newName = prompt("Enter new name:", currentName);
    if (newName && newName.trim() !== "" && newName !== currentName) {
      setIsLoading(true);
      try {
        await api.renameItem(itemId, newName.trim());
        fetchFiles(currentFolderId);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleDownload = async (fileId, fileName) => {
    setIsLoading(true);
    setError(null);
    try {
        await api.downloadFile(fileId, fileName);
    } catch (err) {
        setError(err.message);
    } finally {
        setIsLoading(false);
    }
  };

  const handleNavigate = (folderId) => {
    setCurrentFolderId(folderId);
  };

  // Simple breadcrumb logic (very basic)
  // In a real app, you'd want to store folder names for the path
  const isNotRoot = currentFolderId !== 'root';


  if (isLoading && !files.length && !error && !isAuthenticated) { // Initial loading state before auth check
    return <div className="text-center p-10">Loading application...</div>;
  }

  return (
    <div className="container mx-auto p-4 font-sans">
      <header className="bg-blue-600 text-white p-4 rounded-md mb-6 shadow-lg flex justify-between items-center">
        <h1 className="text-3xl font-bold">My Drive Explorer</h1>
        {!isAuthenticated && !isLoading && ( // Show login only if not authenticated and not in initial load
          <button
            onClick={handleLogin}
            className="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded transition duration-150 ease-in-out"
          >
            Login with Google
          </button>
        )}
      </header>

      {error && <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative mb-4" role="alert">Error: {error}</div>}

      {isAuthenticated ? (
        <>
          <nav className="mb-6 flex flex-wrap gap-2 items-center">
            <button
              onClick={() => setShowCreateFolderModal(true)}
              className="bg-indigo-500 hover:bg-indigo-700 text-white font-bold py-2 px-4 rounded shadow transition duration-150"
            >
              Create Folder
            </button>
            <div className="flex items-center">
              <input
                type="file"
                id="fileUploadInput"
                onChange={(e) => setFileToUpload(e.target.files[0])}
                className="block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100 p-1 border rounded-md"
              />
              <button
                onClick={handleFileUpload}
                disabled={!fileToUpload || isLoading}
                className="ml-2 bg-purple-500 hover:bg-purple-700 text-white font-bold py-2 px-4 rounded shadow disabled:opacity-50 transition duration-150"
              >
                Upload File
              </button>
            </div>
          </nav>

          {/* Breadcrumbs */}
          {isNotRoot && (
            <div className="mb-2">
                <button onClick={() => handleNavigate('root')} className="text-blue-500 hover:underline">Root</button>
                <span> / ... / {files.find(f => f.id === currentFolderId)?.name || currentFolderId} </span> {/* Improved breadcrumb */}
            </div>
          )}

          {isLoading && <div className="text-center p-4">Loading files...</div>}

          <main className="bg-white shadow-md rounded-lg p-4">
            <ul className="divide-y divide-gray-200">
              {files.map((file) => (
                <li key={file.id} className="py-3 flex justify-between items-center hover:bg-gray-50 transition duration-150">
                  <div
                    className={`flex items-center cursor-pointer ${file.mimeType === 'application/vnd.google-apps.folder' ? 'font-semibold text-blue-700' : 'text-gray-700'}`}
                    onClick={() => file.mimeType === 'application/vnd.google-apps.folder' ? handleNavigate(file.id) : null}
                    title={file.mimeType === 'application/vnd.google-apps.folder' ? `Open folder ${file.name}` : file.name}
                  >
                    <img src={file.iconLink || 'https://ssl.gstatic.com/docs/doclist/images/icon_10_generic_list.png'} alt="icon" className="w-6 h-6 mr-3"/>
                    <span>{file.name}</span>
                    {file.mimeType === 'application/vnd.google-apps.folder' && <span className="ml-2 text-xs text-gray-500">(Folder)</span>}
                  </div>
                          <div className="space-x-2">
                            {file.mimeType !== 'application/vnd.google-apps.folder' && (
                                <button onClick={() => handleDownload(file.id, file.name)} className="text-sm bg-green-500 hover:bg-green-600 text-white py-1 px-2 rounded shadow">Download</button>
                            )}
                            <button onClick={() => handleRename(file.id, file.name)} className="text-sm bg-yellow-500 hover:bg-yellow-600 text-white py-1 px-2 rounded shadow">Rename</button>
                            <button onClick={() => handleDelete(file.id, file.name)} className="text-sm bg-red-500 hover:bg-red-600 text-white py-1 px-2 rounded shadow">Delete</button>
                          </div>
                        </li>
                      ))}
              {files.length === 0 && !isLoading && <li className="py-3 text-center text-gray-500">No files or folders found in '{currentFolderId === 'root' ? 'Root' : currentFolderId}'.</li>}
            </ul>
          </main>

                  {showCreateFolderModal && (
                    <div className="fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full flex items-center justify-center z-50">
                      <div className="bg-white p-5 rounded-lg shadow-xl w-11/12 md:w-1/3">
                        <h3 className="text-lg font-medium mb-4">Create New Folder</h3>
                        <input
                          type="text"
                          value={newFolderName}
                          onChange={(e) => setNewFolderName(e.target.value)}
                          placeholder="Folder Name"
                          className="border p-2 rounded w-full mb-4"
                        />
                        <div className="flex justify-end space-x-2">
                          <button onClick={() => setShowCreateFolderModal(false)} className="bg-gray-300 hover:bg-gray-400 text-black py-2 px-4 rounded">Cancel</button>
                          <button onClick={handleCreateFolder} className="bg-blue-500 hover:bg-blue-700 text-white py-2 px-4 rounded">Create</button>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                !isLoading && ( // Only show login prompt if not loading and not authenticated
                  <div className="text-center p-10">
                    <p className="text-xl mb-4">Please log in to access your Google Drive.</p>
                    <button
                      onClick={handleLogin}
                      className="bg-green-500 hover:bg-green-700 text-white font-bold py-3 px-6 rounded text-lg transition duration-150 ease-in-out"
                    >
                      Login with Google
                    </button>
                  </div>
                )
              )}

              <footer className="mt-10 pt-6 border-t text-center text-sm text-gray-600">
                <p>&copy; {new Date().getFullYear()} My Drive App. (Simulated Google Drive)</p>
              </footer>
            </div>
          );
        }

        export default App;
