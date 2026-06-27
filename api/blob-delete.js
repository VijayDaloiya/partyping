import { del } from '@vercel/blob';

export default async function handler(request, response) {
  if (request.method !== 'POST') {
    response.status(405).json({ error: 'Method not allowed' });
    return;
  }

  const url = request.query.url;
  if (!url) {
    response.status(400).json({ error: 'Missing url' });
    return;
  }

  await del(url);
  response.status(200).json({ ok: true });
}
