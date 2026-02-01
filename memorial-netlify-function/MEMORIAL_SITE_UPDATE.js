// =============================================================================
// REPLACE the existing photo upload JavaScript on ruthtomlinsonbrown.com
// with this code. This will actually upload photos to the Family Archive.
// =============================================================================

// Find this section in your memorial site HTML and replace it:

/*
OLD CODE (delete this):
----------------------------------------
const photoInput = document.getElementById('photo-input');
const feedback = document.getElementById('upload-feedback');

photoInput.addEventListener('change', (e) => {
  if (e.target.files.length > 0) {
    feedback.style.display = 'block';
    feedback.innerText = `Preparing ${e.target.files.length} photo(s) for the family archive...`;
    setTimeout(() => {
      feedback.innerText = "✓ Photos added to archive project.";
      feedback.style.color = "#A68B67";
    }, 2000);
  }
});
----------------------------------------
*/

// NEW CODE (add this instead):
// ----------------------------------------

const photoInput = document.getElementById('photo-input');
const feedback = document.getElementById('upload-feedback');

photoInput.addEventListener('change', async (e) => {
  const files = e.target.files;
  if (files.length === 0) return;

  feedback.style.display = 'block';
  feedback.style.color = '#666';
  feedback.innerText = `Uploading ${files.length} photo(s) to the family archive...`;

  try {
    // Upload each file
    let uploaded = 0;

    for (const file of files) {
      // Create form data
      const formData = new FormData();
      formData.append('file', file);
      formData.append('contributor', 'Memorial_Guest'); // You can customize this

      // Update progress
      feedback.innerText = `Uploading photo ${uploaded + 1} of ${files.length}...`;

      // Send to Netlify Function
      const response = await fetch('/.netlify/functions/upload', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Upload failed');
      }

      uploaded++;
    }

    // Success!
    feedback.style.color = '#A68B67';
    feedback.innerText = `✓ ${uploaded} photo(s) added to the family archive!`;

    // Clear the input so they can upload more
    photoInput.value = '';

  } catch (error) {
    console.error('Upload error:', error);
    feedback.style.color = '#c44';
    feedback.innerText = `Upload failed: ${error.message}. Please try again.`;
  }
});

// ----------------------------------------
// END OF NEW CODE
