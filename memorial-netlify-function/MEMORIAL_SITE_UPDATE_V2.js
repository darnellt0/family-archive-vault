// =============================================================================
// UPDATED MEMORIAL SITE UPLOAD CODE - Supports Large Videos!
// =============================================================================
//
// This version handles:
// - Small files (<5MB): Upload through Netlify function
// - Large files (>5MB): Direct upload to R2 using presigned URLs
//
// Replace your existing upload JavaScript with this code.
// =============================================================================

const photoInput = document.getElementById('photo-input');
const feedback = document.getElementById('upload-feedback');

// Size threshold for direct upload (5MB)
const DIRECT_UPLOAD_THRESHOLD = 5 * 1024 * 1024;

photoInput.addEventListener('change', async (e) => {
  const files = e.target.files;
  if (files.length === 0) return;

  feedback.style.display = 'block';
  feedback.style.color = '#666';
  feedback.innerText = `Uploading ${files.length} file(s) to the family archive...`;

  try {
    let uploaded = 0;
    const total = files.length;

    for (const file of files) {
      // Update progress
      feedback.innerText = `Uploading ${file.name} (${uploaded + 1}/${total})...`;

      if (file.size > DIRECT_UPLOAD_THRESHOLD) {
        // Large file: use presigned URL for direct upload
        await uploadLargeFile(file, (progress) => {
          feedback.innerText = `Uploading ${file.name}: ${progress}%`;
        });
      } else {
        // Small file: use Netlify function
        await uploadSmallFile(file);
      }

      uploaded++;
    }

    // Success!
    feedback.style.color = '#A68B67';
    feedback.innerText = `✓ ${uploaded} file(s) added to the family archive!`;

    // Clear the input so they can upload more
    photoInput.value = '';

  } catch (error) {
    console.error('Upload error:', error);
    feedback.style.color = '#c44';
    feedback.innerText = `Upload failed: ${error.message}. Please try again.`;
  }
});

// Upload small files through Netlify function
async function uploadSmallFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('contributor', 'Memorial_Guest');

  const response = await fetch('/.netlify/functions/upload', {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Upload failed');
  }

  return await response.json();
}

// Upload large files directly to R2 using presigned URL
async function uploadLargeFile(file, onProgress) {
  // Step 1: Get presigned URL from Netlify function
  const urlResponse = await fetch('/.netlify/functions/get-upload-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      contentType: file.type || 'application/octet-stream',
      size: file.size
    })
  });

  if (!urlResponse.ok) {
    const error = await urlResponse.json();
    throw new Error(error.error || 'Failed to get upload URL');
  }

  const { uploadUrl, objectKey } = await urlResponse.json();

  // Step 2: Upload directly to R2 using presigned URL
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        const percent = Math.round((e.loaded / e.total) * 100);
        onProgress(percent);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        console.log(`Uploaded: ${objectKey}`);
        resolve({ objectKey, size: file.size });
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}`));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'));
    });

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload was cancelled'));
    });

    xhr.open('PUT', uploadUrl);
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.send(file);
  });
}

// =============================================================================
// END OF UPLOAD CODE
// =============================================================================
