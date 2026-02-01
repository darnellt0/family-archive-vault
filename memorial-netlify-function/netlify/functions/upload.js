// Netlify Function to upload photos to Cloudflare R2
// This connects the memorial site to the Family Archive storage

const { S3Client, PutObjectCommand } = require("@aws-sdk/client-s3");

// R2 Configuration - these must be set in Netlify Environment Variables
const R2_ACCOUNT_ID = process.env.R2_ACCOUNT_ID;
const R2_ACCESS_KEY_ID = process.env.R2_ACCESS_KEY_ID;
const R2_SECRET_ACCESS_KEY = process.env.R2_SECRET_ACCESS_KEY;
const R2_BUCKET_NAME = process.env.R2_BUCKET_NAME || "family-archive-uploads";

// Initialize R2 client
const r2Client = new S3Client({
  region: "auto",
  endpoint: `https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
  credentials: {
    accessKeyId: R2_ACCESS_KEY_ID,
    secretAccessKey: R2_SECRET_ACCESS_KEY,
  },
});

exports.handler = async (event, context) => {
  // CORS headers
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
  };

  // Handle preflight
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 200, headers, body: "" };
  }

  if (event.httpMethod !== "POST") {
    return {
      statusCode: 405,
      headers,
      body: JSON.stringify({ error: "Method not allowed" }),
    };
  }

  try {
    // Check R2 credentials
    if (!R2_ACCOUNT_ID || !R2_ACCESS_KEY_ID || !R2_SECRET_ACCESS_KEY) {
      console.error("Missing R2 credentials");
      return {
        statusCode: 500,
        headers,
        body: JSON.stringify({ error: "Storage not configured" }),
      };
    }

    // Parse the multipart form data
    const contentType = event.headers["content-type"] || event.headers["Content-Type"];

    if (!contentType || !contentType.includes("multipart/form-data")) {
      return {
        statusCode: 400,
        headers,
        body: JSON.stringify({ error: "Content-Type must be multipart/form-data" }),
      };
    }

    // For Netlify Functions, we need to handle base64 encoded body
    const body = event.isBase64Encoded
      ? Buffer.from(event.body, "base64")
      : Buffer.from(event.body);

    // Parse multipart form data manually (simplified)
    const boundary = contentType.split("boundary=")[1];
    const parts = parseMultipart(body, boundary);

    const uploadedFiles = [];
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const contributorName = parts.contributor || "Memorial_Guest";
    const folderName = `${contributorName.replace(/[^a-zA-Z0-9]/g, "_")}_UPLOADS`;

    for (const part of parts.files) {
      const safeFilename = part.filename.replace(/[^a-zA-Z0-9._-]/g, "_");
      const objectKey = `${folderName}/${timestamp}_${safeFilename}`;

      // Upload to R2
      const command = new PutObjectCommand({
        Bucket: R2_BUCKET_NAME,
        Key: objectKey,
        Body: part.data,
        ContentType: part.contentType,
      });

      await r2Client.send(command);

      uploadedFiles.push({
        filename: part.filename,
        objectKey: objectKey,
        size: part.data.length,
      });

      console.log(`Uploaded: ${objectKey} (${part.data.length} bytes)`);
    }

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        success: true,
        message: `${uploadedFiles.length} photo(s) uploaded successfully`,
        files: uploadedFiles,
      }),
    };

  } catch (error) {
    console.error("Upload error:", error);
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: "Upload failed: " + error.message }),
    };
  }
};

// Simple multipart parser
function parseMultipart(body, boundary) {
  const result = { files: [], contributor: "Memorial_Guest" };

  const boundaryBuffer = Buffer.from(`--${boundary}`);
  const parts = [];

  let start = 0;
  let idx = body.indexOf(boundaryBuffer, start);

  while (idx !== -1) {
    const nextIdx = body.indexOf(boundaryBuffer, idx + boundaryBuffer.length);
    if (nextIdx === -1) break;

    const partData = body.slice(idx + boundaryBuffer.length, nextIdx);
    parts.push(partData);

    idx = nextIdx;
  }

  for (const part of parts) {
    const headerEnd = part.indexOf(Buffer.from("\r\n\r\n"));
    if (headerEnd === -1) continue;

    const headers = part.slice(0, headerEnd).toString();
    const content = part.slice(headerEnd + 4);

    // Remove trailing \r\n
    const cleanContent = content.slice(0, content.length - 2);

    // Check if it's a file
    const filenameMatch = headers.match(/filename="([^"]+)"/);
    const nameMatch = headers.match(/name="([^"]+)"/);

    if (filenameMatch && filenameMatch[1]) {
      const contentTypeMatch = headers.match(/Content-Type:\s*([^\r\n]+)/i);
      result.files.push({
        filename: filenameMatch[1],
        contentType: contentTypeMatch ? contentTypeMatch[1] : "application/octet-stream",
        data: cleanContent,
      });
    } else if (nameMatch && nameMatch[1] === "contributor") {
      result.contributor = cleanContent.toString().trim() || "Memorial_Guest";
    }
  }

  return result;
}
