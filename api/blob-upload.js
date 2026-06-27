import { put } from '@vercel/blob';

async function readRequestBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

export default async function handler(request, response) {
  if (request.method !== 'POST') {
    response.status(405).json({ error: 'Method not allowed' });
    return;
  }

  const filename = request.query.filename || `upload-${Date.now()}.webp`;
  const body = await readRequestBody(request);
  const blob = await put(filename, body, {
    access: 'public',
    addRandomSuffix: true,
  });

  response.status(200).json(blob);
}
